// Free-tier Telegram inbox and GitHub wakeup only. No LLM or channel publishing here.
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff' },
});
const safeId = (id) => Number.isSafeInteger(id) && id >= 0;
const baliDay = (timestamp) => new Date(timestamp + 8 * 3600_000).toISOString().slice(0, 10);

async function equalSecret(actual, expected) {
  if (typeof expected !== 'string' || expected.length < 32 || typeof actual !== 'string') return false;
  const encode = (value) => new TextEncoder().encode(value);
  const [left, right] = await Promise.all([
    crypto.subtle.digest('SHA-256', encode(actual)), crypto.subtle.digest('SHA-256', encode(expected)),
  ]);
  const a = new Uint8Array(left), b = new Uint8Array(right);
  let difference = 0;
  for (let index = 0; index < a.length; index++) difference |= a[index] ^ b[index];
  return difference === 0;
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > 64_000) throw new Error('Body too large');
  return JSON.parse(text);
}

function reviewerIds(env) {
  const user = Number(env.LEO_TELEGRAM_USER_ID);
  const rawOwner = String(env.OWNER_TELEGRAM_USER_ID ?? '').trim();
  const owner = rawOwner ? Number(rawOwner) : user;
  if (![user, owner].every((id) => Number.isSafeInteger(id) && id > 0 && id <= 2 ** 52)) return [];
  return [...new Set([user, owner])];
}

function authorizedUpdate(update, env) {
  const message = update?.message;
  const user = Number(env.LEO_TELEGRAM_USER_ID), chat = Number(env.LEO_TELEGRAM_CHAT_ID);
  const reviewers = reviewerIds(env);
  const validChat = Number.isSafeInteger(chat) && (chat < 0 || (chat === user && reviewers.length === 1));
  const validType = chat > 0 ? message?.chat?.type === 'private'
    : ['group', 'supergroup'].includes(message?.chat?.type);
  return validChat && validType && safeId(update?.update_id)
    && reviewers.includes(message?.from?.id) && message?.chat?.id === chat
    && !message?.from?.is_bot && !message?.sender_chat
    && !message?.forward_origin && typeof message?.text === 'string';
}

function groupIdRequest(update, env) {
  const message = update?.message, reviewers = reviewerIds(env);
  // Read-only setup help from the already allowlisted reviewer. Telegram routes
  // addressed commands to this bot; no chat is enrolled and no work is dispatched.
  return safeId(update?.update_id)
    && reviewers.includes(message?.from?.id) && !message?.from?.is_bot
    && !message?.forward_origin && !message?.sender_chat
    && Number.isSafeInteger(message?.chat?.id) && message.chat.id < 0
    && ['group', 'supergroup'].includes(message.chat.type)
    && typeof message?.text === 'string'
    && /^\/review_group_id(?:@[A-Za-z0-9_]+)?$/.test(message.text);
}

export function createWorker(fetcher = globalThis.fetch, clock = Date.now) {
  async function wake(env, dailyDay = '') {
    const repo = env.GITHUB_REPOSITORY, workflow = env.GITHUB_WORKFLOW || 'surf-review.yml';
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo || '')
        || !/^[A-Za-z0-9_.-]+\.ya?ml$/.test(workflow) || !env.GITHUB_ACTIONS_TOKEN) {
      console.error('GitHub wakeup configuration is incomplete. Inbox remains saved.');
      return false;
    }
    const now = clock();
    // D1 atomic compare/update serializes simultaneous webhook and cron wakeups.
    const claimed = await env.DB.prepare(
      `UPDATE control SET wake_at = ?, wake_attempts = wake_attempts + 1,
       next_wake_at = ? + CASE WHEN wake_attempts = 0 THEN 60000
                              WHEN wake_attempts = 1 THEN 120000
                              WHEN wake_attempts = 2 THEN 240000 ELSE 900000 END
       WHERE id = 1 AND wake_at <= ? AND next_wake_at <= ? RETURNING id`,
    ).bind(now, now, now - 30_000, now).first();
    if (!claimed) return false;
    try {
      const response = await fetcher(
        `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`, {
          method: 'POST', headers: {
            Authorization: `Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
            Accept: 'application/vnd.github+json', 'User-Agent': 'surf-review-webhook',
            'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json',
          },
          body: JSON.stringify({ ref: env.GITHUB_REF || 'main' }),
          // Workers rejects redirect:'error' before sending a request. Manual
          // returns 3xx to the status check below without forwarding the PAT.
          signal: AbortSignal.timeout(15_000), redirect: 'manual',
        },
      );
      if (response.status !== 204 && response.status !== 200) {
        console.error(`GitHub wakeup failed (HTTP ${response.status}). Inbox remains saved.`);
        await env.DB.prepare('UPDATE control SET wake_at = 0 WHERE id = 1 AND wake_at = ?').bind(now).run();
        return false;
      }
      if (dailyDay) {
        await env.DB.prepare('UPDATE control SET daily_day = ?, work_pending = 1 WHERE id = 1')
          .bind(dailyDay).run();
      }
      return true;
    } catch {
      console.error('GitHub wakeup unavailable. Inbox remains saved for the next cron attempt.');
      await env.DB.prepare('UPDATE control SET wake_at = 0 WHERE id = 1 AND wake_at = ?').bind(now).run();
      return false;
    }
  }

  return {
    async fetch(request, env, ctx) {
      try {
        const url = new URL(request.url);
        if (url.pathname === '/telegram' && request.method === 'POST') {
          if (env.WEBHOOK_ENABLED !== 'true') return json({ error: 'Webhook paused' }, 503);
          if (!await equalSecret(request.headers.get('X-Telegram-Bot-Api-Secret-Token'),
                                 env.TELEGRAM_WEBHOOK_SECRET)) return json({ error: 'Unauthorized' }, 401);
          let update;
          try { update = await readJson(request); } catch { return json({ error: 'Invalid update' }, 400); }
          if (groupIdRequest(update, env)) {
            console.info(`Review group chat ID: ${update.message.chat.id}`);
            return json({ ok: true });
          }
          // Unauthorized users never enter the inbox or trigger GitHub jobs.
          if (!authorizedUpdate(update, env)) return json({ ok: true });
          const saved = await env.DB.prepare('INSERT OR IGNORE INTO inbox (update_id, payload) VALUES (?, ?)')
            .bind(update.update_id, JSON.stringify(update)).run();
          if (saved.meta.changes) {
            await env.DB.prepare('UPDATE control SET work_pending = 1, next_wake_at = 0 WHERE id = 1').run();
            ctx.waitUntil(wake(env));
          }
          return json({ ok: true });
        }
        if (!await equalSecret(request.headers.get('Authorization'), `Bearer ${env.SURF_WEBHOOK_TOKEN || ''}`)
            || !env.SURF_WEBHOOK_TOKEN || env.SURF_WEBHOOK_TOKEN.length < 32) {
          return json({ error: 'Unauthorized' }, 401);
        }
        if (url.pathname === '/status' && request.method === 'GET') {
          const state = await env.DB.prepare('SELECT * FROM control WHERE id = 1').first();
          const count = await env.DB.prepare('SELECT count(*) AS pending FROM inbox WHERE acked = 0').first();
          return json({ enabled: env.WEBHOOK_ENABLED === 'true', pending: count.pending,
            last_wake_at: state.wake_at, next_wake_at: state.next_wake_at, daily_day: state.daily_day, last_completed_at: state.completed_at });
        }
        if (env.WEBHOOK_ENABLED !== 'true') return json({ error: 'Webhook paused' }, 503);
        if (url.pathname === '/inbox' && request.method === 'GET') {
          const rows = await env.DB.prepare(
            'SELECT payload FROM inbox WHERE acked = 0 ORDER BY update_id LIMIT 100',
          ).all();
          return json({ updates: rows.results.map((row) => JSON.parse(row.payload)) });
        }
        if (url.pathname === '/ack' && request.method === 'POST') {
          let body;
          try { body = await readJson(request); } catch { return json({ error: 'Invalid acknowledgement' }, 400); }
          if (!Array.isArray(body.ids) || !body.ids.length || body.ids.length > 100
              || !body.ids.every(safeId)) return json({ error: 'Invalid acknowledgement' }, 400);
          const placeholders = body.ids.map(() => '?').join(',');
          // Keep only tombstones to suppress Telegram retries; erase acknowledged feedback payloads.
          await env.DB.prepare(`UPDATE inbox SET acked = 1, payload = '{}' WHERE update_id IN (${placeholders})`)
            .bind(...body.ids).run();
          return json({ ok: true });
        }
        if (url.pathname === '/complete' && request.method === 'POST') {
          await env.DB.prepare(`UPDATE control SET completed_at = ?, work_pending = 0, wake_attempts = 0, next_wake_at = 0
            WHERE id = 1 AND NOT EXISTS (SELECT 1 FROM inbox WHERE acked = 0)`)
            .bind(clock()).run();
          return json({ ok: true });
        }
        return json({ error: 'Not found' }, 404);
      } catch {
        // Never expose exception messages, request headers, feedback or PATs.
        console.error('Webhook service failed. Check the D1 binding/schema and free-tier limits.');
        return json({ error: 'Inbox temporarily unavailable' }, 503);
      }
    },

    async scheduled(_event, env, _ctx) {
      if (env.WEBHOOK_ENABLED !== 'true') return;
      try {
        const now = clock(), day = baliDay(now);
        const state = await env.DB.prepare('SELECT * FROM control WHERE id = 1').first();
        const pending = await env.DB.prepare('SELECT 1 AS pending FROM inbox WHERE acked = 0 LIMIT 1').first();
        const baliMinute = new Date(now + 8 * 3600_000).getUTCHours() * 60
          + new Date(now).getUTCMinutes();
        if (baliMinute >= 9 * 60 + 7 && state.daily_day !== day) {
          await wake(env, day);
        } else if (pending || state.work_pending) {
          // Recovers dispatch errors, GitHub pending-run coalescing and failed revisions.
          await wake(env);
        }
      } catch {
        console.error('Webhook recovery check failed. Saved inbox is preserved.');
      }
    },
  };
}

export default createWorker();
