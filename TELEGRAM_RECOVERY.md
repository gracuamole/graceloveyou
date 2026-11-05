# Telegram revision recovery
Upload review_bot.py and tests/test_review_bot.py to their existing paths on main.
Requires Release 1 including run_log.py. Includes the location-display edit fix.
No Cloudflare update or new secrets are needed: the existing webhook accepts authorised
text replies and wakes GitHub. Queueing can still delay processing.

Reply to the existing report/approval prompt (not the error notice):
- New feedback ending in change: replace your pending feedback and retry.
- retry: retry saved feedback unchanged.
- correct while revision is pending: explains why approval is blocked. After a recorded
  failure it waits for retry, replacement feedback or cancellation.
- cancel change: cancel the pending revision for this report, resend the previous report
  and a NEW approval prompt. Nothing publishes until correct replies to that new prompt.

Cancellation preserves history and remembered instructions. Use /memory and /forget ID
if a remembered instruction should also be removed. It cancels both reviewers' currently
pending corrections; either authorised reviewer can use it. Replies must target current
report/prompt IDs. Expired reports, unauthorised senders and stale prompts stay blocked.
Uncertain Telegram sends still require reconciliation; these commands cannot bypass it.

After upload and tests pass, reply retry to the existing pending report's approval message.
The webhook should trigger processing automatically. Do not reset state or use resend flags.
Already-sent error notices will not change; future failures display recovery instructions.

Offline verification: 221 Python tests and 26 Worker tests passed. No remote push,
deployment, live Telegram messages, LLM calls or Surfline requests were made.
