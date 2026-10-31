# Leo's surf report review

Implementation is local until approved for deployment. No Telegram messages, LLM calls,
remote branch creation, or pushes are needed to run the offline tests.

## Behavior

One workflow (`surf-review.yml`) replaces all five legacy scheduled publishers.
Their schedule definitions remain, but jobs are explicitly disabled, including manual
runs. Legacy forecast builders remain available; direct send paths and Phase 2
`--send` are disabled. `phase2.py` still previews tomorrow's Surfline report.

At or after 09:07 Bali time (01:07 UTC), generate tomorrow's daylight report once
using the existing Surfline integration and Phase 2 recommendations in the simple
grouped format. Poll Telegram
every five minutes; GitHub scheduling can be delayed, so this is not a latency SLA.
No draft is generated until the configured Leo has sent `/start` in private.

Draft delivery is ordered: report parts, private **Detailed surf analysis**, private
**Surfline data summary**, then the final approval prompt. The analysis explains
each skill level's included/excluded windows and compares the current draft with
the source-rule result. The summary shows actual saved hourly values, source
ratings such as `Poor to fair`, sunrise/sunset and daylight tide events. Derived
tide bands, conversions and unconfirmed energy units are labelled. No extra LLM
call is needed for these deterministic notes. The usual one-part report produces
one analysis message and one data message. Longer documents are split within
Telegram's limit, with all their IDs recorded before the final prompt.

Leo uses Telegram **Reply**:

* Exactly `correct` (lowercase, no extra spaces, punctuation or newline) on the
  newest final prompt approves the complete current report. The analysis/data
  messages must already be recorded as delivered. Publish only the exact report
  text, without draft labels, to the channel. Private analysis/data are never
  included in channel delivery. Each report part is delivered once on successful runs.
* Feedback whose final word is lowercase `change` (optional trailing whitespace)
  can Reply to the current report, analysis, data summary or final prompt and goes
  to Gemini. For example: `Wind should be 15 km/h change`.
  Bare `change` is ignored. The LLM receives the saved forecast, draft and feedback,
  and returns a complete revised report. It cannot authorize publication. Each new
  version gets fresh private analysis/data and a fresh prompt requiring Leo's
  approval again. Reviewer corrections appear separately from unchanged original
  source values. Any draft/source-rule disagreement is explicitly flagged for review.
* Wrong users, groups, forwards, edited messages, stale prompt replies and unrelated
  text are ignored. Usernames are never identity credentials. No unthreaded approvals.
* Reports expire at the start of their forecast date in Bali. Late approvals cannot
  publish yesterday's next-day report. A failure never substitutes invented data.

### Manual testing after publication

Start a **new** **Reviewed next-day surf report** run from `main` and tick
**Send another private draft after publication (testing; fresh correct posts again)**.
The `resend_published` input defaults to **false**. Ordinary manual runs, scheduled
runs and the Worker's automatic dispatches continue to skip already published
reports. No Worker change is required: it dispatches with only `ref`, without this
input. The CLI accepts `--resend-published` only in a GitHub `workflow_dispatch`
run with a numeric `GITHUB_RUN_ID`; the workflow passes it only for an explicitly
checked input.

For a next-day report already marked `published`, the option fetches a fresh
Surfline forecast and creates a new version using the current format, even if
the earlier version has identical text. It sends labeled **TEST DRAFT** messages
privately to the configured reviewer, followed by the two private evidence documents
and a final prompt warning that a new exact
`correct` will post to the configured channel again. Feedback ending in `change`
continues through the normal revision loop. Earlier approvals and old prompts
cannot approve the new version. Publication needs a fresh Reply on its newest
final prompt and is delivered once for that approved version. After publication,
normal scheduled/webhook runs send no extra draft or channel post.

The original published report is retained in `publication_history`, including its
parts, approval, forecast and Telegram message IDs. The new version starts with
empty delivery IDs and no approval. A `manual_retest_requests` entry and new draft
are saved together before sending. The GitHub run ID deduplicates retries, including
**Re-run jobs** after successful publication; choose **Run workflow** to deliberately
start another test. Pending tests resume normally without opening another cycle.
An already active review is not replaced, source failures retain the earlier
publication, and uncertain sends still require reconciliation. Do not clear state
or delivery IDs to test again. `/dryrun` remains a preview that cannot be approved.

`/status` and `/dryrun` work as regular private commands from the configured
reviewer. `/status` returns saved status without private feedback text. `/dryrun`
fetches a fresh deterministic next-day preview without creating a report/version,
prompt or approval. A preview cannot be approved. A command-only run does not open
a daily approval cycle, although existing pending work and the independent daily
schedule continue. These private responses are persisted in `outbox` before sending.

Reply `note: Your observation change` on the latest real final prompt to append an
attributed reviewer note without Gemini. All existing facts remain, the version
increments and a fresh final prompt needs fresh approval. Other feedback continues
through Gemini. Numeric output must come from the draft, source snapshot or explicit
feedback. This is a conservative sanity check, not proof of accuracy, correct units
or associations. The displayed header is a written-out forecast date (for example,
`Forecast date: 30 October 2026`), then a blank line and `📍OLD MAN'S / BATU BOLONG`.
The report groups matching windows under 🟢 BEGINNER, 🟡 INTERMEDIATE and 🔵 ADVANCED,
with just the times when conditions qualify. Preserve the coached beginner inside
exception for over-limit outside height/period when energy is at most 600, wind
at most 20 km/h and the rating at least Fair. Other conditional, poor-to-fair,
missing-data or flat periods are omitted from recommended times; the private
analysis explains them. Use `No qualifying window.` when nothing qualifies.
Merging never bridges an excluded gap. Advanced good windows do not list heights.
Display ⚠️ CAUTIONS in full sentences only when recommended daylight windows
trigger one; omit generic warnings. An actual-inside-height reminder remains when the inside exception
applies. Telegram headings
are bold through entities; the exact text and approval hash stay unchanged.
The WITA label, source-attribution line and generic safety-guarantee disclaimer are
omitted at the user's request. All forecast times still use Bali time internally;
conditions, skill advice and coach cautions remain in the report.
Analysis begins at sunrise rounded up to the next hour and ends at sunset rounded
down to the previous hour (05:48–18:12 becomes 06:00–18:00). Exact-hour endpoints
stay unchanged. Only those complete daylight rows enter recommendations and
cautions. Gemini receives a normalized target-day daylight snapshot rather than
the original multi-day/night feed. Revised time ranges must be whole hours inside
that same window, even when feedback supplies additional out-of-window times.
The full source snapshot remains in state for diagnosis. Older draft-only states
with no daily source metadata can use the draft without extra source observations;
an invalid daily sunlight record stops the revision before an LLM request.
The model receives the saved spot name as required text. Old banner wording is
removed from revision input/output (including note-only revisions), so existing
saved drafts can adopt this format through a new reviewed version. Harmless spot-name
typography (curly apostrophes, case and whitespace around `/`) is recognized and
the original spot label retained. A missing/different location, unsupported
numbers, missing date, or blocked/truncated output still fails. Every resulting
revision needs a fresh exact approval on its new final prompt.
Already approved text and existing message/publication IDs are not rewritten.

To update an existing deployment, pause `SURF_REVIEW_ENABLED`, wait for active runs,
then upload `recommendations.py`, `review_bot.py`, the new `review_context.py`,
`surfline_check.py`, `webhook_setup.py` and the updated `tests/` files (including
`tests/fixtures/november_1_2026.json`) to `main`. The forecast tests
import `surfline_check.py`, and webhook inspection tests require the matching
`webhook_setup.py`; an older/missing helper makes the tests fail before any bot run.
For the complete matching source/test upload set, see
[UPDATE_INSTRUCTIONS.md](UPDATE_INSTRUCTIONS.md).
Re-enable review and start a NEW **Reviewed next-day surf report** run from
`main`. Saved future-dated pending feedback uses the updated Gemini instructions.
For a report already awaiting review, Reply to its latest final prompt with
`Use the shorter format and full daylight hours change` to request a fresh version. A note-only
edit keeps the current layout and appends the note; it does not regenerate an old
hourly report. Never reset state to change presentation.

An older pending review without private context receives only the missing analysis,
data and a new final prompt; its already delivered report parts are not resent or
silently rewritten. Its old `correct` cannot approve the new review bundle. Ask for
the new good-window format through feedback as above. Already published reports
receive no automatic context upgrade or new messages. Existing recorded approvals
are not changed. Older states without a daily snapshot get explicit data-unavailable
notes rather than invented observations; a fresh manual test can fetch a new snapshot.

The required-source adapter blocks generation when next-day daylight or breaking
surf coverage is missing. Unknown secondary fields still produce explicit N/A and
unknown recommendations. After `/start`, source/revision failures queue one private
notice per forecast date/version respectively. Telegram/persistence failures may
prevent such notices. A pending failed revision cannot be approved, but replacement
feedback ending in `change` on its current prompt can replace the pending feedback.

## Setup after deployment approval

1. Deploy these changes to the default branch. All legacy scheduled publishers must
   be disabled before enabling the review workflow; do not run an older checkout with
   channel credentials. Keep `SURF_REVIEW_ENABLED` unset until setup is complete.
2. Create a durable `review-state` branch in this repository, containing `state.json`
   at its root with the contents of `review_state.example.json`. A normal branch
   from the default branch is fine. This is a one-time initialization: **never reset
   it on later runs**, since it contains the publication ledger. Branch creation and
   any remote pushes require approval and have not been performed here.
3. Set repository Actions secrets:
   * `TELEGRAM_BOT_TOKEN`: the bot's token.
   * `LEO_TELEGRAM_USER_ID` and `LEO_TELEGRAM_CHAT_ID`: Leo's verified positive numeric
     ID, the same number for his private chat. Confirm with Leo through a trusted
     route and the bot's incoming `/start` metadata; do not infer from
     `@@Leonardosinaga`, auto-enroll the first sender, or use a third-party ID bot.
   * `TELEGRAM_CHANNEL_ID`: the verified negative numeric ID of graceloveyou.
     Make the bot a channel administrator with permission to post.
   * `GEMINI_API_KEY`: your Google AI Studio Gemini API key. This is a secret, not a variable.
4. Set Actions variable `GEMINI_MODEL` to exactly `gemini-3.5-flash-lite` (without
   quotes). The workflow sets `LLM_PROVIDER=gemini`. No model is silently selected
   or substituted, and there is no automatic fallback to paid OpenAI calls.
5. Leo must open this bot's private conversation and send `/start`. Bots cannot
   initiate private conversations from a username alone. If Leo already started
   the bot long ago, ask him to send `/start` again for the new workflow.
6. Use this as the bot's **only** update consumer. Remove any webhook through the
   Telegram API before enabling polling; the bot refuses to run if one is present.
   Do not run another poller with this token. Telegram retains updates only for a
   limited period (currently 24 hours), so monitor Actions failures.
7. Allow Actions `contents: write` on `review-state`, including repository branch
   rules. The workflow uses its scoped `GITHUB_TOKEN`, a separate checkout and one
   concurrency group. Do not manually edit state while a run is active. Default
   branch source checkout does not retain git credentials; state checkout does.
8. Set `SURF_REVIEW_ENABLED=true`, then run the workflow manually and monitor its
   first real draft/review. This enables real Telegram and Gemini API calls. Free-tier availability and limits
   depend on your Google API project.

State contains report text, forecast snapshots, Leo's feedback, numeric IDs, approval
hashes and message IDs. It contains no API credentials. If this repository is public,
state branch history is public too: obtain consent for feedback retention or use a
private repository before enabling. Restrict repository write access; writers can
change code/state and are part of the trust boundary. Never commit `.env` or tokens.

## Durability and uncertain delivery

Every processed update and state transition is committed and pushed to `review-state`.
Inbox offsets advance only after handling; the next poll acknowledges saved updates.
A revision failure retains the feedback for a future retry. Successful report,
analysis and data IDs allow resuming partial private/channel delivery without
resending acknowledged parts. The private documents are saved before the first
report send. Content/input hashes bind them to the report revision; new approvals
include the bundle hash as well as the exact public-report hash. Modified
source/report/context cannot silently reuse a delivered approval.

Telegram `sendMessage` has no idempotency key. Strict automatic exactly-once delivery
across a network timeout cannot be guaranteed. This implementation chooses to stop
instead of risking a duplicate: **before every send**, persist an `intent`; after
success persist the returned message ID and clear it. A timeout, crash or failed push
after delivery can leave an intent. Future runs halt before any further delivery.
Even a known rejection is conservative and requires operator reconciliation.

To recover: disable the workflow variable, wait for any active run to stop, inspect
`state.json` on `review-state` and Telegram's actual private/channel messages. The
intent records `kind` and a text hash. If the send succeeded, append its Telegram
message ID to `draft_ids`, `analysis_ids`, `source_ids`, `prompt_ids`, or `publish_ids`
as appropriate, then clear
`intent`. Private command/failure sends store intents in the relevant `outbox` entry;
append the verified ID to that entry's `notice_ids`, then clear its intent. For a
published part its index is the current length of `publish_ids`.
If you can establish that no message was delivered, clear the intent without
adding an ID. Commit/push only the verified correction, then re-enable. If uncertain,
leave it halted; never delete publication history or blindly rerun sends. Never change
report parts after approval. Changing Leo/destination IDs also stops the workflow
until the stored `binding` is deliberately reconciled by an operator.

## Local verification

```sh
python3 -m unittest discover -s tests -v
python3 review_bot.py  # no network, no sends, no state mutation
python3 phase2.py      # live Surfline preview only; no Telegram
```

All unit tests mock Telegram/LLM calls; they cover authorization, exact approval,
revision/reapproval, stale replies, restart persistence, expiry, hash mismatch,
checkpoint failure and ambiguous sends. Existing root `test_*.py` are live probes
and are deliberately excluded. Surfline feed availability and the provisional energy
units in `PHASE2.md` remain live validation items. Leo reviews the final report;
LLM revisions are not independent confirmation of forecast accuracy.

The original Surfline request methods remain in `main4_pkge_indi.py`, including the
independent minimal `spotId`/`days=2` request used in `test_curl.py`. A failed package
request tries that same standard-requests call and then the minimal Firefox call.
Response unit metadata is checked before passing measurements to the parser, which
expects FT/KTS/F. This avoids relabeling metric default responses. The tested
library/transport versions are pinned in `requirements.txt`. For a live source
check with no Telegram, LLM or state writes, run `python3 surfline_check.py` locally
or **Surfline forecast check (no Telegram)** from `main` in GitHub Actions. That
workflow is manual only, requests no secrets and cannot approve or publish reports.

References: [Telegram Bot API](https://core.telegram.org/bots/api),
[Telegram polling FAQ](https://core.telegram.org/bots/faq#getting-updates),
[Gemini text generation](https://ai.google.dev/gemini-api/docs/text-generation),
[Gemini models](https://ai.google.dev/gemini-api/docs/models), and
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Diagnosing a stopped run

The bot prints a safe reason for configuration/state errors and HTTP status codes
for Telegram/Gemini/OpenAI failures. Raw service response bodies, HTTP exception URLs and
Git output are suppressed because they can contain credentials. HTTP 401 indicates
rejected credentials, 403 denied access, 409 a Telegram polling conflict, and 429
rate/quota limits. A Git error requires checking Actions write permission, branch
rules and concurrent edits. An `intent` still requires the manual reconciliation
above; diagnostics never clear it or retry a possibly delivered message.

## Switching an existing deployment to Gemini

1. Temporarily set `SURF_REVIEW_ENABLED=false` and let an active run finish.
2. Upload updated `review_bot.py`, `.github/workflows/surf-review.yml`,
   `tests/test_review_bot.py`, and this guide to the default branch. Keep the existing
   state branch and all publication/message history intact.
3. Confirm the Actions secret is named exactly `GEMINI_API_KEY`.
4. Create Actions variable `GEMINI_MODEL` with the exact value
   `gemini-3.5-flash-lite`. `OPENAI_API_KEY` and `OPENAI_MODEL` are unused by the
   Gemini workflow and may be removed if no other workflow needs them.
5. Set `SURF_REVIEW_ENABLED=true` and start a NEW manual run from the default branch.
   Saved revision-pending feedback is retried when its forecast date is still future.
   Expired reports stay expired; the next-day draft is generated after 09:07 Bali time.
6. Reply to the latest final prompt with feedback ending in `change`. After the
   revised draft arrives, only exact `correct` on its new prompt approves publication.

If an older deployment reports **LLM revision removed the spot, source attribution
or safety caution**, pause `SURF_REVIEW_ENABLED`, let any active review run finish,
and upload updated `review_bot.py`, `recommendations.py` and the updated `tests/`
files to `main`. The updated application removes the
retired banner and protects the spot and supplied numbers. Re-enable review and start
a **new** Reviewed next-day surf report run from `main`. Existing future-dated
`revision_pending` feedback is retried without resending it; do not edit `state.json`
or clear an intent for this validation error. This is separate from an uncertain
Telegram send. Location changes or unsupported facts still need corrected feedback.

Gemini uses the same existing `requests` dependency; no new SDK is needed. It receives
forecast data, report text and reviewer feedback, never API credentials. Truncated,
blocked, empty and malformed output leaves feedback pending, with no publication.
Google currently lists a free tier for this model, subject to project quotas. Free-tier
content may be used to improve Google's products; review Google's data terms before
sending private feedback. API availability, account access and live delivery have
not been tested by the offline tests.

The optional OpenAI adapter remains available for local use by explicitly setting
`LLM_PROVIDER=openai`, `OPENAI_API_KEY` and `OPENAI_MODEL`; the shipped workflow
selects Gemini only. The existing state format needs no reset; optional outbox
entries are added automatically. This provider
switch does not implement the previously discussed cross-report lesson memory.

## Green run but no Telegram reply

A successful run can be idle. Read the workflow's **Inspect saved review status
(read-only)** step, then **Poll reviews and advance durable workflow**. The status
step never contacts Telegram or the LLM and never changes state. The polling step
now logs a fixed reason for each processed message, without printing message text,
API keys or numeric user IDs. Reasons include wrong reviewer/chat, a regular message
instead of Telegram Reply, stale review prompt, expired forecast, invalid command,
accepted approval, accepted feedback, or no newly returned messages. The last outcome
is saved for future diagnosis. This is an additive field; no state reset is required.

Use Reply on the latest FINAL prompt for a forecast date that is still in the future.
A report for a date that has already started in Bali cannot accept corrections or
approval. New reports are generated after 09:07. Exact `correct` publishes to the
configured channel; this implementation does not send a private success confirmation.
After uploading diagnostics, send a fresh reply to the valid prompt, then start one
new manual workflow run to see the result. Old ignored messages have already been
acknowledged and are not replayed. If the job is skipped, verify
`SURF_REVIEW_ENABLED=true`; an overall green run alone does not mean the bot job ran.

For a local state checkout, `python3 review_bot.py --status --state
review-state/state.json` provides the same read-only summary without credentials.

## Optional free webhook transport

See [FREE_HOSTING.md](FREE_HOSTING.md) for Cloudflare Workers Free + D1 setup.
`SURF_REVIEW_TRANSPORT=webhook` reads the authenticated durable webhook inbox instead
of calling Telegram `getUpdates`. The root report state format stays compatible;
webhook processed IDs are added for crash-safe replay handling. Git commits still
precede each inbox acknowledgement and Telegram side effect. `--status` remains
read-only. In this mode the GitHub five-minute cron job is skipped, webhook updates
request a workflow dispatch, and the daily cron remains as a backup. The Cloudflare
one-minute recovery check also wakes the daily draft after 09:07 Bali time. Setting
`SURF_REVIEW_TRANSPORT=poll` preserves the original polling mode, provided the
Telegram webhook is removed first. Both transports must never run concurrently.
