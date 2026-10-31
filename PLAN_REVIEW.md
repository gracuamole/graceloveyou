# Review of the alternative free hosting plan

The plan has useful suggestions. This implementation adopts them incrementally:
Cloudflare Workers Free + D1 receive Telegram webhooks and wake the existing public
GitHub Actions workflow; the working Python Surfline integration and Gemini remain.
It is prepared locally, not deployed. Your Mac can be off once setup is complete.
The existing spot (Old Man's / Batu Bolong), one report a day and 09:07 Bali generation
time are preserved. Follow [FREE_HOSTING.md](FREE_HOSTING.md) for setup.

| Suggestion | Decision and implementation |
| --- | --- |
| Free Worker, authenticated Telegram webhook and cron | Keep the prepared Worker and its recovery/daily cron. Updates are stored before acknowledging Telegram, then wake GitHub immediately. Runner setup still adds delay; this is not a three-minute response guarantee. |
| KV or D1 for state | Use D1 for the inbox and atomic wakeup claims. Keep the existing report/approval/publication ledger in `review-state`, serialized by one Actions concurrency group. KV's delayed visibility and lack of atomic transactions are unsuitable for deduplication/approval decisions. |
| Rewrite all report logic into a TypeScript Worker | Defer. The working Surfline transport uses Python `surf-mcp` and `curl_cffi` with browser impersonation. Worker `fetch` access and provider compatibility have not been validated. Porting everything would also require migrating the publication ledger. The Worker uses plain JavaScript modules; TypeScript is not needed for this transport. |
| Deterministic initial report | Already used, with all three skill tiers and daylight intervals. Initial generation and `/dryrun` need no LLM. Do not invent a best time or offshore wind call without calibrated spot rules. |
| Source adapter and explicit fetch failures | Added `forecast_sources.py`, reusing the existing spot/transport. Missing forecast date, daylight or any daylight breaking-surf sample blocks a new draft and queues one private error notice per forecast date after `/start`. Unknown secondary inputs stay labeled N/A/unknown, preserving the existing conservative recommendations. |
| Automatic Open-Meteo fallback | Do not substitute it for breaking-surf heights. Its marine significant wave height and sea-level variables do not supply the same breaking-surf/energy/rating inputs. A separately labeled reference report would need its own rules and license check. No Open-Meteo calls or fallback are enabled. |
| Workers AI or another free LLM | Keep the Gemini free-tier project already configured. No new provider or paid fallback is called. Workers AI is an optional future alternative with its own quota and model restrictions, not an unlimited free replacement. |
| Constrain LLM facts | Added a numeric-value guard against the saved draft, forecast and explicit reviewer feedback. Reject missing date, spot/source/safety removal, unsupported numbers and incomplete output. Number membership is only a sanity check: it cannot prove correct units, meaning, associations or truth of a reviewer correction. Human review remains mandatory. |
| Deterministic edits | Added `note: your note change` as a Reply to the latest final prompt. It appends a clearly attributed reviewer note without an LLM, retains existing report facts, and requires fresh approval. Arbitrary spot swapping/removal of safety data is not enabled. |
| `/status`, `/dryrun`, failure messages | Added private commands and a durable private-message outbox. Status shows saved state; dryrun fetches tomorrow's deterministic preview without opening a review cycle. Source/revision failures send deduplicated notices. An uncertain Telegram send stops delivery instead of attempting an unsafe error message. |
| Approval matching | Preserve exact lowercase `correct`, with no spaces/newline, only as a Reply to the latest final prompt. Preserve feedback ending in lowercase `change`. Do not adopt case folding or treat all messages as edits. Numeric user AND private chat checks remain. |
| One active draft, expiry, reminders | Enforce one active report, preserve expiry at the start of its forecast date in Bali, and never auto-publish. Timed reminder messages are not added. |

## Using the additions

After uploading the updated files and completing webhook setup:

1. Send `/start` in the bot's private chat if not already recorded.
2. Send `/status` to see the saved report state. No Reply is needed for commands.
3. Send `/dryrun` to receive a private forecast preview. It cannot be approved and
   has no final review prompt. A run processing only these commands does not start
   a daily approval cycle; independent daily scheduling still operates normally.
4. On the real draft's latest FINAL prompt, use Telegram **Reply** with
   `note: Ask a coach about the current change` to test a free deterministic edit.
   A new draft and prompt arrive; the original facts remain and the note is marked
   as the reviewer's observation rather than Surfline data.
5. For a factual correction, Reply with explicit values, for example
   `Wind should be 15 km/h from the east; mark that as my correction change`.
   Gemini must use supplied numbers. Conversions/new estimates are rejected unless
   supplied explicitly. Check the resulting report yourself.
6. Only Reply with exactly `correct` to the newest final prompt when ready to
   publish to the configured channel. Test using a private test channel first.

A pending failed revision cannot be approved. You can send replacement feedback
ending in `change` on the same still-current final prompt, including a `note:` edit
that avoids Gemini. The replacement must be saved before the next attempt. Once a
revised prompt arrives, the older prompt is invalid. No previous approval carries over.

Private notices use the same persisted intent/message-ID protocol as report sends.
They are not resent on duplicate updates or successful retries. If a notice send is
uncertain, its `intent` is inside `outbox` in state; reconcile actual delivery and
`notice_ids` using [REVIEW_WORKFLOW.md](REVIEW_WORKFLOW.md). Do not reset the state.
No notices can be guaranteed when Telegram itself or persistence is unavailable.

## Current free-tier constraints

Checked against provider documentation on 2026-10-30; recheck when deploying:

* [Workers Free pricing](https://developers.cloudflare.com/workers/platform/pricing/)
  and [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/) provide
  bounded allowances. D1 Free currently includes 5 million rows read/day,
  100,000 written/day and 5 GB total storage. Stay on Free; quota failure is not
  permission to upgrade or enable overages.
* [KV consistency](https://developers.cloudflare.com/kv/concepts/how-kv-works/)
  permits delays of 60 seconds or more across locations and does not provide atomic
  multi-step updates. This is why the inbox uses D1 rather than KV.
* [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
  includes 10,000 neurons/day; excess usage needs a paid plan, and some models
  require a paid billing method. No Workers AI binding is configured here.
* [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) lists free-tier
  model access, subject to project quotas and data terms. Keep the existing project
  without paid billing when zero extra spend is required.
* [Open-Meteo pricing](https://open-meteo.com/en/pricing) restricts its free hosted
  service to non-commercial use. Its [marine variable definitions](https://open-meteo.com/en/docs/marine-weather-api)
  distinguish significant marine waves and sea level; they must not be relabeled
  as the existing spot's breaking surf. This implementation does not use that API.

The free public GitHub standard runner remains part of this implementation. No
paid VM, paid hosting plan, OpenAI credits or new LLM subscription is required.
Live account eligibility, Surfline access from production and end-to-end latency
still need a private-channel deployment test. No deployment, push, real Telegram
message or live LLM call was performed while preparing these changes.
