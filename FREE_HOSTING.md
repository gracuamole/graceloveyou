# Free hosted Telegram replies

Use **Cloudflare Workers Free + D1 Free**, the existing public GitHub repository's
standard Ubuntu Actions runner, and your Gemini project's free tier. Your Mac can be
off. No Render subscription, persistent disk, custom domain, paid Worker plan,
OpenAI credits or always-running Python server is needed.

This implementation is prepared locally. Nothing has been deployed, purchased,
pushed or sent to Telegram during preparation. The previous paid Render blueprint
was removed. Free tiers have limits and can stop service; this is not a paid uptime
or response-time guarantee. Stay on the Free plans; do not enable paid upgrades or
link Gemini to paid billing if you require no extra charges. Keep Actions spending
blocked at zero if you later make the repository private. Standard Ubuntu runners
are free in public repositories; larger runners are billed. This setup uses no
billable Actions artifacts or extra caches.

## How it works

Telegram sends replies directly to the Worker. The Worker verifies Telegram's
secret header and the configured private reviewer IDs, writes each update once to
D1, and requests a run of `surf-review.yml` on `main`. GitHub reads the saved inbox,
persists processing in the existing `review-state` Git branch, and only then
acknowledges the inbox item. Gemini revises the report in that same workflow.

A one-minute Cloudflare recovery cron retries pending work and requests the daily
draft after 09:07 Bali time. It only wakes GitHub when there is work. Repeated
uncompleted work backs off from one minute to two, four, then fifteen minutes.
The regular daily GitHub cron remains a backup. The five-minute GitHub poll job is
skipped in webhook mode. Incoming replies request an immediate workflow start,
which still depends on GitHub runner availability, dependency setup and Gemini.

The existing approval and uncertain-send protections remain. Cloudflare never
publishes a report, invokes Gemini, or receives your bot token/Gemini key. Queue
items survive coalesced GitHub pending runs. Duplicate Telegram deliveries do not
create duplicate queue items. Acknowledged payloads are erased from D1, leaving ID
tombstones for deduplication. Report/publication history stays on `review-state`.
This transport change does not add the previously discussed reusable lesson memory.

The alternative plan review and adopted improvements are in
[PLAN_REVIEW.md](PLAN_REVIEW.md): private `/status` and `/dryrun`, an LLM-free
`note:` edit, numeric revision checks, required-source validation and private
failure notices. Initial reports remain deterministic; Gemini is only for free-form
edits. This remains a Worker + GitHub design, so runner startup still adds delay.

## 1. Upload the prepared files

Upload these files/folders to matching locations on GitHub's `main` branch:

* `review_bot.py` (updated)
* `forecast_sources.py` (new required forecast adapter)
* `webhook_setup.py` (new)
* `.github/workflows/surf-review.yml` (updated)
* `.github/workflows/configure-webhook.yml` (new)
* `.github/workflows/phase2-tests.yml` (updated tests)
* `cloudflare/` (new Worker, SQL schema, config and offline tests)
* `tests/` (all offline Python tests, including the new source/review tests)
* `.gitignore`, `REVIEW_WORKFLOW.md`, `PLAN_REVIEW.md`, and this guide

Keep the existing forecast files and dependencies. Never upload actual tokens,
`.dev.vars`, `.env`, or `.wrangler` state. Do not replace `review-state/state.json`.

## 2. Create the free Cloudflare resources

1. Create/sign in to a [Cloudflare account](https://dash.cloudflare.com/).
2. Choose **Workers Free**. Do not upgrade to Workers Paid or create paid resources.
3. Under **Workers & Pages**, create a Worker named `graceloveyou-surf-review`.
   A starter/Hello World Worker is fine initially.
4. Open its code editor, replace the starter with the ENTIRE contents of
   `cloudflare/worker.mjs`, and deploy that code. It stays paused until configured.
5. Copy the Worker's HTTPS `workers.dev` URL. No custom domain is required. Use the
   origin only, with no `/telegram` suffix, query string or credentials.
6. Create a **D1** database named `surf-review-inbox`. Open its SQL console and run
   the contents of `cloudflare/schema.sql`. Keep this database across deployments.
7. In the Worker **Bindings**, add a D1 binding named exactly **`DB`**, selecting
   `surf-review-inbox`. Save/deploy the binding.

Dashboard labels can change; Cloudflare's [dashboard quickstart] and [D1 guide]
show the current resource-creation screens. You can use the dashboard throughout;
there is no need to install Wrangler. `cloudflare/wrangler.jsonc` is supplied for
CLI users, who must replace its database ID before deployment and set secrets
separately. The dashboard method doesn't use that config file automatically.

## 3. Give the Worker narrow permission to wake GitHub

In GitHub account settings, open **Developer settings → Personal access tokens →
Fine-grained tokens → Generate new token**.

* Name: `Surf webhook wakeup`.
* Select only the `graceloveyou` repository.
* Repository permission: **Actions → Read and write**. Metadata read is automatic.
* Do not grant Contents write, administration, organization or other permissions.
* Set an expiration you can maintain, and save the token securely.

This token authorizes the Worker to start workflows on this one repository. Enter
it ONLY as the Cloudflare secret `GITHUB_ACTIONS_TOKEN`. Never paste it into chat,
source code, the Worker URL, or repository files. Rotate it before expiration.

## 4. Configure the Worker

In the Worker's **Settings → Variables and Secrets**, add these plain variables:

| Name | Exact value |
| --- | --- |
| `WEBHOOK_ENABLED` | `false` initially |
| `GITHUB_REPOSITORY` | `gracuamole/graceloveyou` |
| `GITHUB_WORKFLOW` | `surf-review.yml` |
| `GITHUB_REF` | `main` |
| `LEO_TELEGRAM_USER_ID` | The SAME numeric reviewer ID already configured in GitHub |
| `LEO_TELEGRAM_CHAT_ID` | The SAME numeric private-chat ID already configured in GitHub |

Add these as **secrets**:

| Name | Value |
| --- | --- |
| `GITHUB_ACTIONS_TOKEN` | The fine-grained token from step 3 |
| `TELEGRAM_WEBHOOK_SECRET` | A new random secret, 32+ letters/digits/underscores/hyphens |
| `SURF_WEBHOOK_TOKEN` | A SECOND, different random secret, 32+ characters |

For each random secret, you can generate a fresh value locally with:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Keep those values private. You will copy the two shared secrets into GitHub in the
next step. Cloudflare does not need `TELEGRAM_BOT_TOKEN` or `GEMINI_API_KEY`.

Add a Worker **Cron Trigger** using the expression `* * * * *`. This is the
one-minute recovery/daily check, not a constantly billed server. New cron settings
can take up to fifteen minutes to propagate. Save/deploy the Worker settings.

## 5. Switch delivery safely

1. In GitHub Actions variables, set **`SURF_REVIEW_ENABLED=false`** and wait for any
   running review workflow to finish. The setup workflow uses the same concurrency
   group to avoid changing Telegram routing during an active review run.
2. Keep your existing Telegram IDs/token, Gemini settings, and state branch.
3. Add GitHub Actions variable **`SURF_REVIEW_TRANSPORT`** = **`webhook`**.
4. Add GitHub Actions variable **`SURF_WEBHOOK_URL`** = the Worker origin copied in
   step 2 (for example, your actual HTTPS `workers.dev` URL, without `/telegram`).
5. Add GitHub Actions secret **`SURF_WEBHOOK_TOKEN`** = the SAME value stored in
   Cloudflare under that name.
6. Add GitHub Actions secret **`TELEGRAM_WEBHOOK_SECRET`** = the SAME value stored
   in Cloudflare under that name.
7. In Cloudflare, change **`WEBHOOK_ENABLED=true`** and save/deploy it. GitHub review
   remains paused for now; any queued replies are kept in D1.
8. In GitHub **Actions → Configure free Telegram webhook → Run workflow**, select
   branch **`main`**, action **`enable`**, and run it. This is an explicit Telegram
   configuration change. It sends no chat message and preserves pending updates.
   It refuses to replace an unrelated existing webhook.
9. Confirm the setup log says **Webhook registered and verified**.
10. Set GitHub's **`SURF_REVIEW_ENABLED=true`**. Run **Reviewed next-day surf report**
    manually once from `main` to process any existing queue and verify setup.
11. Reply to the latest FINAL review prompt for a future forecast date, ending your
    feedback with lowercase `change`. The Worker should request a new Actions run
    without waiting for the old GitHub five-minute schedule. Exact `correct` still
    publishes only to the configured channel. Use your private test channel first.
12. Send `/status` to see saved state, or `/dryrun` for a private forecast preview.
    These commands do not need a Telegram Reply. To test edits without Gemini,
    Reply to the latest real final prompt with `note: Your observation change`.
    A preview cannot approve or publish anything. Previously pending work and the
    independent daily schedule continue operating normally.

Keep Gemini on the free-tier project/model. Its quota can still be exhausted; the
bot preserves pending work rather than switching to a paid provider.

## Diagnosis and recovery

* **No new Actions run:** Check Cloudflare Worker logs, D1 binding/schema,
  `WEBHOOK_ENABLED`, GitHub token expiration/repository permission, and that the
  workflow file exists on `main` with `workflow_dispatch`. A successful dispatch
  appears as **Manually run** in GitHub even when the Worker initiated it.
* **Webhook setup fails:** Run **Configure free Telegram webhook** with action
  **inspect**. It reports registration and pending-delivery count without printing
  secrets or raw Telegram error messages. A mismatched shared secret produces HTTP
  401; D1 failure/paused Worker produces HTTP 503 and Telegram retries delivery.
* **Revision fails:** Inspect the review workflow logs. The durable state retains
  feedback; the Worker retries uncompleted work with increasing delay. If Gemini's
  free quota is exhausted, wait for its quota reset; don't enable paid billing.
  The bot sends one private failure notice per draft version when possible.
  Replacement feedback ending in `change` can be sent on the same current prompt;
  `note:` works without an LLM. Numeric corrections must be stated explicitly.
* **Uncertain send intent:** Pause `WEBHOOK_ENABLED` and `SURF_REVIEW_ENABLED` to stop
  retries. Follow `REVIEW_WORKFLOW.md` to reconcile Telegram delivery. Never reset
  `state.json`, delete D1, or blindly clear a send intent.
* **Returning to polling:** First drain the inbox through a successful review run.
  Pause review and Worker dispatch, run the setup workflow with action **disable**
  to remove the Telegram webhook, then set `SURF_REVIEW_TRANSPORT=poll` and re-enable
  review. Do not run `getUpdates` while a webhook is registered. Keep D1/history.
* **Privacy:** D1 holds pending feedback privately; acknowledged queue payloads are
  erased. Existing reports/feedback on your public `review-state` branch remain
  public, as before. GitHub and Cloudflare credentials are secrets, never files.

## Verification and practical limits

Offline tests mock all Telegram, Gemini, Cloudflare HTTP and GitHub dispatch calls.
The Worker tests use a local SQLite database with the exact D1 schema:

```sh
python3 -m unittest discover -s tests -v
node --test cloudflare/worker.test.mjs
```

Tests verify identity checks, authentication, durable acknowledgement order,
duplicate suppression, GitHub coalesced wakeups, dispatch failures, delayed retries,
Bali daily timing, and retention of approval/publication guards. No live deployment,
free-tier CPU measurement, account permission check or delivery test has been run
by the implementation task. An incoming webhook can wake GitHub immediately, but
runner startup/setup and Gemini still add delay. There is no exact latency SLA.

Sources: [Workers Free pricing], [D1 Free pricing], [GitHub runner billing],
[workflow dispatch API], [Telegram webhook API], [Gemini pricing].

[dashboard quickstart]: https://developers.cloudflare.com/workers/get-started/dashboard/
[D1 guide]: https://developers.cloudflare.com/d1/get-started/
[Workers Free pricing]: https://developers.cloudflare.com/workers/platform/pricing/
[D1 Free pricing]: https://developers.cloudflare.com/d1/platform/pricing/
[GitHub runner billing]: https://docs.github.com/en/billing/concepts/product-billing/github-actions
[workflow dispatch API]: https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
[Telegram webhook API]: https://core.telegram.org/bots/api#setwebhook
[Gemini pricing]: https://ai.google.dev/gemini-api/docs/pricing
