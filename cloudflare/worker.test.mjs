import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { createWorker } from './worker.mjs';

function fixture() {
  const sqlite = new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('./schema.sql', import.meta.url), 'utf8'));
  const DB = { prepare(sql) {
    const statement = sqlite.prepare(sql);
    const bound = (values) => ({
      bind: (...args) => bound(args),
      first: async () => statement.get(...values) ?? null,
      all: async () => ({ results: statement.all(...values) }),
      run: async () => ({ meta: { changes: Number(statement.run(...values).changes) } }),
    });
    return bound([]);
  } };
  const env = { DB, WEBHOOK_ENABLED: 'true', TELEGRAM_WEBHOOK_SECRET: 't'.repeat(40),
    SURF_WEBHOOK_TOKEN: 'a'.repeat(40), GITHUB_ACTIONS_TOKEN: 'PAT_SECRET',
    GITHUB_REPOSITORY: 'owner/repo', GITHUB_WORKFLOW: 'surf-review.yml', GITHUB_REF: 'main',
    LEO_TELEGRAM_USER_ID: '42', LEO_TELEGRAM_CHAT_ID: '42' };
  let now = Date.parse('2026-10-30T00:00:00Z'); // 08:00 Bali, before daily generation.
  const calls = [], responses = [];
  const worker = createWorker(async (...args) => {
    // Workers supports follow/manual only, unlike Node's fetch implementation.
    // Validate this runtime constraint even though outbound requests are mocked.
    const request = new Request(...args);
    if (!['follow', 'manual'].includes(request.redirect)) {
      throw new TypeError('Unsupported redirect mode in Cloudflare Workers');
    }
    calls.push(args);
    const response = responses.shift();
    if (response instanceof Error) throw response;
    return response ?? new Response(null, { status: 204 });
  }, () => now);
  const run = async (path, body, headers = {}) => {
    const pending = [];
    const response = await worker.fetch(new Request('https://surf.example' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${env.SURF_WEBHOOK_TOKEN}`,
        'X-Telegram-Bot-Api-Secret-Token': env.TELEGRAM_WEBHOOK_SECRET,
        'Content-Type': 'application/json', ...headers },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }), env, { waitUntil: (promise) => pending.push(promise) });
    await Promise.all(pending);
    return response;
  };
  const update = (id = 10, changes = {}) => ({ update_id: id, message: {
    from: { id: 42 }, chat: { id: 42, type: 'private' }, text: 'fix wind change',
    reply_to_message: { message_id: 100 }, ...changes,
  } });
  const advance = (ms = 60_000) => { now += ms; };
  return { worker, env, calls, responses, run, update, advance, sqlite };
}

test('authenticated Telegram update is persisted before waking the existing workflow', async () => {
  const f = fixture();
  assert.equal((await f.run('/telegram', f.update())).status, 200);
  assert.equal(f.calls.length, 1);
  const [url, options] = f.calls[0];
  assert.equal(url, 'https://api.github.com/repos/owner/repo/actions/workflows/surf-review.yml/dispatches');
  assert.equal(options.headers.Authorization, 'Bearer PAT_SECRET');
  assert.deepEqual(JSON.parse(options.body), { ref: 'main' });
  assert.equal(options.redirect, 'manual');
  assert.equal(url.includes('SECRET'), false);
  const inbox = await (await f.run('/inbox')).json();
  assert.deepEqual(inbox.updates, [f.update()]);
});

test('wrong secret, reviewer, group and forwarded updates cannot wake GitHub', async () => {
  const f = fixture();
  assert.equal((await f.run('/telegram', f.update(), {
    'X-Telegram-Bot-Api-Secret-Token': 'wrong',
  })).status, 401);
  for (const override of [{ from: { id: 99 } }, { chat: { id: 42, type: 'group' } },
    { forward_origin: { type: 'user' } }, { from: { id: 42, is_bot: true } }]) {
    assert.equal((await f.run('/telegram', f.update(10, override))).status, 200);
  }
  assert.equal(f.calls.length, 0);
  assert.equal((await (await f.run('/inbox')).json()).updates.length, 0);
});

test('retry delivery is idempotent even after inbox acknowledgement', async () => {
  const f = fixture();
  await f.run('/telegram', f.update());
  await f.run('/telegram', f.update());
  assert.equal(f.calls.length, 1);
  assert.equal((await f.run('/ack', { ids: [10] })).status, 200);
  await f.run('/telegram', f.update());
  assert.equal((await (await f.run('/inbox')).json()).updates.length, 0);
  assert.equal(f.sqlite.prepare('SELECT payload FROM inbox WHERE update_id = 10').get().payload, '{}');
});

test('configured review group accepts only Leo and preserves the usual dispatch inputs', async () => {
  for (const type of ['group', 'supergroup']) {
    const f = fixture();
    f.env.LEO_TELEGRAM_CHAT_ID = '-200';
    const update = f.update(10, { chat: { id: -200, type } });
    assert.equal((await f.run('/telegram', update)).status, 200);
    assert.deepEqual((await (await f.run('/inbox')).json()).updates, [update]);
    assert.equal(f.calls.length, 1);
    assert.deepEqual(JSON.parse(f.calls[0][1].body), { ref: 'main' });
    // Telegram retry must not dispatch or store twice.
    await f.run('/telegram', update);
    assert.equal(f.calls.length, 1);
  }
});

test('group routing rejects other members, other chats, channel and anonymous/forwarded messages', async () => {
  const f = fixture();
  f.env.LEO_TELEGRAM_CHAT_ID = '-200';
  for (const override of [{ from: { id: 99 } }, { from: { id: 42, is_bot: true } },
    { chat: { id: -201, type: 'supergroup' } }, { chat: { id: 42, type: 'private' } },
    { chat: { id: -200, type: 'private' } }, { chat: { id: -200, type: 'channel' } },
    { sender_chat: { id: -200 } }, { forward_origin: { type: 'user' } }]) {
    await f.run('/telegram', f.update(10, { chat: { id: -200, type: 'supergroup' }, ...override }));
  }
  assert.equal(f.calls.length, 0);
  assert.deepEqual((await (await f.run('/inbox')).json()).updates, []);
});

test('review chat config cannot point to another positive private user or an invalid ID', async () => {
  for (const chat of ['99', '0', '-200.5', 'not-an-id', '-9007199254740992']) {
    const f = fixture();
    f.env.LEO_TELEGRAM_CHAT_ID = chat;
    await f.run('/telegram', f.update());
    assert.equal(f.calls.length, 0);
  }
});

test('both explicitly configured reviewers can queue group replies and no one else can', async () => {
  const f = fixture();
  f.env.LEO_TELEGRAM_CHAT_ID = '-200';
  f.env.OWNER_TELEGRAM_USER_ID = '99';
  for (const [id, reviewer] of [[10, 42], [11, 99]]) {
    await f.run('/telegram', f.update(id, { chat: { id: -200, type: 'supergroup' },
      from: { id: reviewer }, text: 'correct' }));
  }
  const saved = (await (await f.run('/inbox')).json()).updates;
  assert.deepEqual(saved.map((update) => update.message.from.id), [42, 99]);
  assert.deepEqual(JSON.parse(f.calls[0][1].body), { ref: 'main' });
  for (const override of [{ from: { id: 100 } }, { from: { id: 99, is_bot: true } },
    { sender_chat: { id: -200 } }, { forward_origin: { type: 'user' } },
    { chat: { id: 99, type: 'private' } }, { chat: { id: -201, type: 'supergroup' } }]) {
    await f.run('/telegram', f.update(12, { chat: { id: -200, type: 'supergroup' }, from: { id: 99 }, ...override }));
  }
  assert.equal((await (await f.run('/inbox')).json()).updates.length, 2);
});

test('invalid owner ID fails closed and cannot fall back to an unexpected reviewer', async () => {
  for (const owner of ['0', '-100', '99.5', 'not-an-id', '9007199254740992']) {
    const f = fixture();
    f.env.LEO_TELEGRAM_CHAT_ID = '-200';
    f.env.OWNER_TELEGRAM_USER_ID = owner;
    await f.run('/telegram', f.update(10, { chat: { id: -200, type: 'supergroup' } }));
    assert.equal(f.calls.length, 0);
    assert.deepEqual((await (await f.run('/inbox')).json()).updates, []);
  }
});

test('two distinct reviewer IDs cannot enable a private review destination', async () => {
  const f = fixture();
  f.env.OWNER_TELEGRAM_USER_ID = '99';
  await f.run('/telegram', f.update());
  assert.equal(f.calls.length, 0);
});

test('owner can discover the review group ID without sending messages or waking GitHub', async (t) => {
  const logs = t.mock.method(console, 'info', () => {});
  const f = fixture();
  f.env.OWNER_TELEGRAM_USER_ID = '99';
  await f.run('/telegram', f.update(10, { chat: { id: -200, type: 'supergroup' },
    from: { id: 99 }, text: '/review_group_id@surf_test_bot' }));
  assert.deepEqual(logs.mock.calls[0].arguments, ['Review group chat ID: -200']);
  assert.equal(f.calls.length, 0);
  assert.deepEqual((await (await f.run('/inbox')).json()).updates, []);
});

test('Leo can discover a group ID in operator logs without changing routing or dispatching', async (t) => {
  const logs = t.mock.method(console, 'info', () => {});
  const f = fixture(); // Still configured for private chat.
  const update = f.update(10, { chat: { id: -200, type: 'supergroup', title: 'PRIVATE_TITLE' },
    text: '/review_group_id@surf_test_bot' });
  await f.run('/telegram', update);
  assert.deepEqual(logs.mock.calls[0].arguments, ['Review group chat ID: -200']);
  assert.equal(f.env.LEO_TELEGRAM_CHAT_ID, '42');
  assert.equal(f.calls.length, 0);
  assert.deepEqual((await (await f.run('/inbox')).json()).updates, []);
  assert.equal(f.sqlite.prepare('SELECT work_pending FROM control').get().work_pending, 0);
  assert.equal(logs.mock.calls.flatMap((call) => call.arguments).join('').includes('PRIVATE_TITLE'), false);
});

test('group ID discovery rejects wrong secrets, other members, forwards, bots and channels', async (t) => {
  const logs = t.mock.method(console, 'info', () => {});
  const f = fixture();
  const base = { chat: { id: -200, type: 'supergroup' }, text: '/review_group_id@surf_test_bot' };
  await f.run('/telegram', f.update(10, base), { 'X-Telegram-Bot-Api-Secret-Token': 'wrong' });
  for (const override of [{ from: { id: 99 } }, { from: { id: 42, is_bot: true } },
    { forward_origin: { type: 'user' } }, { sender_chat: { id: -200 } },
    { chat: { id: -200, type: 'channel' } }, { chat: { id: -200, type: 'private' } },
    { text: '/review_group_id@surf_test_bot PRIVATE_TEXT' }]) {
    await f.run('/telegram', f.update(10, { ...base, ...override }));
  }
  assert.equal(logs.mock.calls.length, 0);
  assert.equal(f.calls.length, 0);
});

test('inbox and acknowledgement endpoints require their own secret', async () => {
  const f = fixture();
  await f.run('/telegram', f.update());
  for (const [path, body] of [['/inbox', undefined], ['/ack', { ids: [10] }], ['/complete', {}]]) {
    assert.equal((await f.run(path, body, { Authorization: 'Bearer bad' })).status, 401);
  }
  assert.equal((await (await f.run('/inbox')).json()).updates.length, 1);
});

test('failed GitHub dispatch preserves inbox and cron retries it', async () => {
  const f = fixture();
  f.responses.push(new Response(null, { status: 403 }));
  await f.run('/telegram', f.update());
  assert.equal((await (await f.run('/inbox')).json()).updates.length, 1);
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
});

test('GitHub redirects are rejected without forwarding credentials or losing feedback', async (t) => {
  const logs = t.mock.method(console, 'error', () => {});
  const f = fixture();
  f.responses.push(new Response(null, {
    status: 302, headers: { Location: 'https://untrusted.example/dispatch' },
  }));
  assert.equal((await f.run('/telegram', f.update())).status, 200);
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0][1].redirect, 'manual');
  assert.deepEqual((await (await f.run('/inbox')).json()).updates, [f.update()]);
  assert.equal(f.sqlite.prepare('SELECT wake_at FROM control').get().wake_at, 0);
  const diagnostic = logs.mock.calls.flatMap((call) => call.arguments).join(' ');
  assert.match(diagnostic, /HTTP 302/);
  assert.doesNotMatch(diagnostic, /PAT_SECRET|untrusted\.example|fix wind/);
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
  assert.ok(f.calls.every(([url]) => url.startsWith('https://api.github.com/')));
});

test('a thrown dispatch error preserves feedback for recovery and hides raw exceptions', async (t) => {
  const logs = t.mock.method(console, 'error', () => {});
  const f = fixture();
  f.responses.push(new TypeError('PAT_SECRET and private feedback must never reach logs'));
  assert.equal((await f.run('/telegram', f.update())).status, 200);
  assert.deepEqual((await (await f.run('/inbox')).json()).updates, [f.update()]);
  const diagnostic = logs.mock.calls.flatMap((call) => call.arguments).join(' ');
  assert.match(diagnostic, /GitHub wakeup unavailable/);
  assert.doesNotMatch(diagnostic, /PAT_SECRET|private feedback/);
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
});

test('a coalesced GitHub wakeup cannot erase a second queued update', async () => {
  const f = fixture();
  await f.run('/telegram', f.update(10));
  await f.run('/telegram', f.update(11));
  assert.equal(f.calls.length, 1);
  await f.run('/ack', { ids: [10] });
  await f.run('/complete', {});
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
  assert.deepEqual((await (await f.run('/inbox')).json()).updates.map((u) => u.update_id), [11]);
  await f.run('/ack', { ids: [11] });
  await f.run('/complete', {});
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
});

test('acknowledged feedback still wakes a retry until the whole job completes', async () => {
  const f = fixture();
  await f.run('/telegram', f.update());
  await f.run('/ack', { ids: [10] }); // Git state persisted but Gemini subsequently failed.
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
  await f.run('/complete', {});
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
});

test('daily draft wakeup is once per Bali day after 09:07', async () => {
  const f = fixture();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 0);
  f.advance(67 * 60_000);
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 1);
  await f.run('/complete', {});
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 1);
  f.advance(24 * 3600_000);
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
});

test('paused worker never acknowledges Telegram updates or dispatches jobs', async () => {
  const f = fixture();
  f.env.WEBHOOK_ENABLED = 'false';
  assert.equal((await f.run('/telegram', f.update())).status, 503);
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 0);
});

test('invalid ack identifiers are rejected without changing the queue', async () => {
  const f = fixture();
  await f.run('/telegram', f.update());
  for (const ids of [[], ['10 OR 1=1'], [-1], Array(101).fill(10)]) {
    assert.equal((await f.run('/ack', { ids })).status, 400);
  }
  assert.equal((await (await f.run('/inbox')).json()).updates.length, 1);
});

test('database failure returns retryable HTTP error instead of losing the update', async () => {
  const f = fixture();
  f.env.DB = { prepare() { throw new Error('sensitive raw database error'); } };
  const response = await f.run('/telegram', f.update());
  assert.equal(response.status, 503);
  assert.equal((await response.text()).includes('sensitive'), false);
  assert.equal(f.calls.length, 0);
});

test('status exposes counts but no feedback or credentials', async () => {
  const f = fixture();
  await f.run('/telegram', f.update());
  const response = await (await f.run('/status')).text();
  assert.equal(JSON.parse(response).pending, 1);
  assert.equal(response.includes('fix wind'), false);
  assert.equal(response.includes('SECRET'), false);
});

test('unsuccessful work backs off instead of waking GitHub every minute forever', async () => {
  const f = fixture();
  await f.run('/telegram', f.update());
  await f.run('/ack', { ids: [10] });
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2);
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 2); // Next retry is two minutes after the second dispatch.
  f.advance();
  await f.worker.scheduled({}, f.env, {});
  assert.equal(f.calls.length, 3);
});
