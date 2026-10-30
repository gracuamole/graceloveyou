# Leo's surf report review

Implementation is local until approved for deployment. No Telegram messages, LLM calls,
remote branch creation, or pushes are needed to run the offline tests.

## Behavior

One workflow (`surf-review.yml`) replaces all five legacy scheduled publishers.
Their schedule definitions remain, but jobs are explicitly disabled, including manual
runs. Legacy forecast builders remain available; direct send paths and Phase 2
`--send` are disabled. `phase2.py` still previews tomorrow's Surfline report.

At or after 09:07 Bali time (01:07 UTC), generate tomorrow's daylight report once
using the existing Surfline integration and Phase 2 recommendations. Poll Telegram
every five minutes; GitHub scheduling can be delayed, so this is not a latency SLA.
No draft is generated until the configured Leo has sent `/start` in private.

Drafts can contain several labeled parts, followed by a review prompt. Leo must use
Telegram's **Reply** on that final prompt:

* Exactly `correct` (lowercase, no extra spaces, punctuation or newline) approves
  the complete current version. Publish its exact report text, without draft labels,
  to the configured channel. Each part is delivered once on successful runs.
* Feedback whose final word is lowercase `change` (optional trailing whitespace)
  goes to the configured Gemini model. For example: `Wind should be 15 km/h change`.
  Bare `change` is ignored. The LLM receives the saved forecast, draft and feedback,
  and returns a complete revised report. It cannot authorize publication. Each new
  version gets a fresh prompt and requires Leo's approval again.
* Wrong users, groups, forwards, edited messages, stale prompt replies and unrelated
  text are ignored. Usernames are never identity credentials. No unthreaded approvals.
* Reports expire at the start of their forecast date in Bali. Late approvals cannot
  publish yesterday's next-day report. A failure never substitutes invented data.

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
A revision failure retains the feedback for a future retry. Successful part IDs allow
resuming partial draft/channel delivery, without resending acknowledged parts.

Telegram `sendMessage` has no idempotency key. Strict automatic exactly-once delivery
across a network timeout cannot be guaranteed. This implementation chooses to stop
instead of risking a duplicate: **before every send**, persist an `intent`; after
success persist the returned message ID and clear it. A timeout, crash or failed push
after delivery can leave an intent. Future runs halt before any further delivery.
Even a known rejection is conservative and requires operator reconciliation.

To recover: disable the workflow variable, wait for any active run to stop, inspect
`state.json` on `review-state` and Telegram's actual private/channel messages. The
intent records `kind` and a text hash. If the send succeeded, append its Telegram
message ID to `draft_ids`, `prompt_ids`, or `publish_ids` as appropriate, then clear
`intent`. For a published part its index is the current length of `publish_ids`.
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

Gemini uses the same existing `requests` dependency; no new SDK is needed. It receives
forecast data, report text and reviewer feedback, never API credentials. Truncated,
blocked, empty and malformed output leaves feedback pending, with no publication.
Google currently lists a free tier for this model, subject to project quotas. Free-tier
content may be used to improve Google's products; review Google's data terms before
sending private feedback. API availability, account access and live delivery have
not been tested by the offline tests.

The optional OpenAI adapter remains available for local use by explicitly setting
`LLM_PROVIDER=openai`, `OPENAI_API_KEY` and `OPENAI_MODEL`; the shipped workflow
selects Gemini only. The existing state format needs no migration. This provider
switch does not implement the previously discussed cross-report lesson memory.
