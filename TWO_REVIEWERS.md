# Let you or Leo review the surf report

Either of the two configured people can request corrections or approve the current
report in the review group. A single person's exact `correct` Reply is sufficient;
you do not both need to approve. The bot records the actual approver's numeric ID.
Repeated approvals do not publish another copy of the same approved version.

## Install and enable

1. Set GitHub repository variable `SURF_REVIEW_ENABLED=false` and wait for running
   review jobs to finish.
2. Extract `surf-two-reviewers-update-2026-10-31.zip`. On **main**, replace these
   matching files at their existing paths:
   * `review_bot.py`
   * `tests/test_review_bot.py`
   * `.github/workflows/surf-review.yml`
   * `cloudflare/worker.mjs`
   * `cloudflare/worker.test.mjs`
   The complete package includes the matching earlier source/tests/docs too.
   On Mac, **Command + Shift + .** reveals `.github`.
3. Add GitHub Actions **secret** `OWNER_TELEGRAM_USER_ID` containing your positive
   personal numeric Telegram user ID. Keep `LEO_TELEGRAM_USER_ID` as Leo's ID.
   Keep `LEO_TELEGRAM_CHAT_ID` as the negative review group ID in both services.
4. In Cloudflare, replace the Worker's code with `cloudflare/worker.mjs`, add
   **variable** `OWNER_TELEGRAM_USER_ID` with the same personal ID, and deploy.
   Keep the existing D1 database, webhook secrets and cron. No webhook
   re-registration is needed if its URL and secret are unchanged.
5. Set GitHub `SURF_REVIEW_ENABLED=true` and run **Reviewed next-day surf report**
   from **main**, leaving both manual checkboxes off. Either person can Reply to
   the current report or final prompt with feedback ending in lowercase `change`,
   or to the latest final prompt with exactly lowercase `correct`.

If review is already in the correct group, no state migration or new `/start` is
needed just to add you. An existing prompt remains usable, even if its old wording
mentions only Leo. New prompts say that either of you can reply. If still moving
from a private chat to the group, follow [GROUP_REVIEW.md](GROUP_REVIEW.md) with this
latest package. Two distinct reviewers require a group destination.

An ordinary run sends nothing extra when the report and prompt were already
delivered or the report was published. For a new test copy, start a separate run
with only **Send report again for testing** checked. Approving that test can
deliberately publish a second report for an already published forecast date.

If `OWNER_TELEGRAM_USER_ID` is unset, existing Leo-only review keeps working.
Invalid owner IDs stop processing safely. The sender must be one of the exact
numeric IDs in the exact configured group, using their own account; bots,
anonymous admins, forwards, edited messages and other members are ignored.
Removing a reviewer also prevents their saved, unfinished approval from publishing.

## Feedback from both people

Every accepted correction is saved in the dated report's `feedback_log` on the
existing `review-state` branch, including sender ID, group ID, Telegram update ID,
report version and original text. The log survives workflow restarts and later
revisions. It follows the repository/state branch's access permissions.

If both people reply before a revision runs, both people's pending corrections go
into that revision. Each person's latest pending message replaces only their own
earlier pending instruction; it does not erase the other person's correction.
The complete correction log still retains the replaced messages. All-note edits
(`note: ... change`) from both people remain LLM-free. Every revision needs a new
approval on its new final prompt. An approval received after feedback has made the
current version pending cannot approve the older draft.

## Does it remember feedback for future reports?

Feedback containing the whole word `remember` (case-insensitive) and ending in
`change` is now saved for future reports. Ordinary feedback stays with its current
report. See [REMEMBER_FEEDBACK.md](REMEMBER_FEEDBACK.md) for installation, examples,
and the `/memory` and `/forget ID` commands. Old feedback is not automatically
converted into standing instructions.

The original two-reviewer release verification follows; see the memory guide for
the latest verification.

Offline verification: **181 Python tests and 24 Worker tests pass**. No Telegram
messages, real LLM requests, deployments or remote pushes were made during preparation.
