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
    calls.push(args);
    return responses.shift() ?? new Response(null, { status: 204 });
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
  assert.equal(options.redirect, 'error');
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
