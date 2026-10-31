# Review the report in a group with you and Leo

Drafts, revised reports, approval prompts and bot notices can go to one Telegram
group containing you, Leo and the bot. Leo's numeric user ID is always allowlisted;
set `OWNER_TELEGRAM_USER_ID` in GitHub and Cloudflare to let you review too. Either
configured reviewer can start review, request corrections or approve. Publication
still goes to the separate graceloveyou channel after one reviewer replies exactly `correct` to the latest
final prompt. The group receives only the report and approval prompt, without
the retired detailed analysis or Surfline summary.

## Change an existing private review to a group

1. In GitHub repository Actions variables, set `SURF_REVIEW_ENABLED=false` and wait
   for running review jobs to finish. Keep the existing `review-state` branch.
2. From the latest `surf-two-reviewers-update-2026-10-31.zip`, upload these matching files to
   their existing locations on **main**:
   * `review_bot.py`
   * `tests/test_review_bot.py`
   * `.github/workflows/surf-review.yml`
   * `cloudflare/worker.mjs`
   * `cloudflare/worker.test.mjs`
   The package includes the matching earlier report-only source/tests/docs too.
   On Mac, **Command + Shift + .** reveals `.github`.
3. In Cloudflare, replace the Worker's code with `cloudflare/worker.mjs` and deploy.
   Keep the existing D1 database, cron, secrets and routing settings. The webhook
   can stay enabled while GitHub review is paused. No webhook re-registration is
   needed when its URL and secret are unchanged.
4. Create a Telegram group with you and Leo, add your existing bot, and allow the
   bot to send messages. Use an ordinary group, without forum topics for review.
5. Find the group's numeric chat ID. If you do not already have it, ask **Leo** to
   send `/review_group_id@YourBotUsername` in that group, replacing
   `YourBotUsername` with your actual bot username. In **Cloudflare → Worker →
   Observability → Logs**, open that webhook invocation and find
   `Review group chat ID: -100…` (a basic group can have another negative ID).
   This command only logs the ID: it sends no Telegram reply, changes no routing,
   saves no message content and does not wake GitHub. It works before you change
   the configured chat ID. Only an already allowlisted reviewer can request it.
6. Replace **`LEO_TELEGRAM_CHAT_ID`** with that same negative group ID in BOTH:
   * **GitHub → Settings → Secrets and variables → Actions → Secrets**.
   * **Cloudflare → Worker → Settings → Variables and Secrets**, then deploy.
   Keep `LEO_TELEGRAM_USER_ID` as Leo's positive user ID. Keep
   `TELEGRAM_CHANNEL_ID` as the separate channel ID. Never use the group ID as
   Leo's user ID or the publication channel ID.
   To allow either of you to review, also configure `OWNER_TELEGRAM_USER_ID` with
   your personal positive numeric ID in both services. See [TWO_REVIEWERS.md](TWO_REVIEWERS.md).
7. Set GitHub `SURF_REVIEW_ENABLED=true`. From **Actions → Reviewed next-day surf
   report → Run workflow**, select **main** and tick ONLY **Move review to the
   configured chat**. Leave the resend checkbox off. Run the workflow.
8. After the move succeeds, have either configured reviewer send `/start@YourBotUsername` in the group.
   The webhook requests another run. Any pending report is sent there with a new
   final prompt. Saved pending feedback is revised first. If `/start` was already
   queued after step 6, the move run can consume it and deliver immediately.
9. If the next-day report was **already published**, the move deliberately sends
   nothing extra. For your test, start a separate new run from **main**, tick only
   **Send report again for testing**, and leave the move checkbox off. The prompt
   warns that approving this test will publish another copy to the channel.
10. Either configured reviewer should use Telegram **Reply** on the current report or final prompt for
    feedback ending in `change`, and on the latest final prompt for exact
    `correct`. Other group members can read the report; their approvals and
    corrections are ignored. Send as your own account, not as an anonymous admin.

Keep Telegram's privacy mode enabled. Commands addressed to your bot and replies
to its messages are delivered in privacy mode; ordinary group conversation does
not need to be forwarded to the bot. See Telegram's
[official bot FAQ](https://core.telegram.org/bots/faq#what-messages-will-my-bot-get).
Use `/status@YourBotUsername` or `/dryrun@YourBotUsername` in the configured group
for status or a non-publishable preview. Those responses are visible to the group.

## What the move preserves

The explicit move checkpoints the new chat binding before any draft send. It keeps
the Telegram offset, processed update IDs, saved feedback and publication ledger.
Superseded pending reports and their original chat/message IDs remain in
`review_history`. Active pending reviews get a new version and empty delivery IDs;
no old approval is carried into the group. Every current report/approval records
its review chat because Telegram message IDs are only unique within a chat.

Published reports stay published, and automatic runs do not reopen them. Retrying
the move with the same configured chat does not create another version or reset
Leo's `/start`. A changed group ID, including conversion to a supergroup, requires
another explicit move. Do not edit the saved binding or reset state yourself.

An uncertain send, an approved/partly published report, or an unsent old-chat
notice blocks a move. Resolve that work with the original chat configuration
before trying again. The move cannot change the authorized reviewer or channel.

Offline verification: **181 Python tests and 24 Worker tests pass**, with Telegram,
Surfline and LLM calls mocked. No messages, deployments or remote pushes were made
while preparing this update.
