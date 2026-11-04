# Remember feedback for future reports

Reply to the current report or final review prompt with, for example:

> Please remember to keep cautions in full sentences change

Either Leo or the configured owner can do this in the review group. The whole
word `remember` can appear anywhere and is case-insensitive; the last word must
be lowercase `change`. Ordinary feedback ending in `change` revises only its
current report. Unauthorized, stale, unthreaded and expired replies cannot save
instructions. Previous feedback is not automatically imported.

The bot saves the instruction immediately when accepted, alongside its author,
forecast date and update ID in `review-state/state.json`. It survives workflow
runs and a failed LLM revision. Do not reset or manually replace that state file.
This is persistent application memory, not model training.

Future reports use fresh Surfline data plus active remembered instructions.
Instructions are supplied oldest to newest, with newer instructions taking priority
in conflicts and explicit current feedback taking priority for the current draft.
Date-specific measurements must not be reused as another day's forecast. The
existing date, numeric and daylight validation remains; human review is still
needed to assess the analysis. Memory never grants publication approval.
Each revised report still requires a fresh exact `correct` Reply to its final prompt.

Use `/memory` in the review group to see numbered instructions. Use `/forget 1`
to disable instruction 1 for future reports. Both commands accept the bot suffix,
for example `/forget@YourBot 1`. Only the two authorized reviewers can use them.
Forgetting preserves the audit history and does not rewrite an existing draft.

With active memory, each new daily report and `/dryrun` preview uses Gemini to
apply it to the template. This uses the existing API quota. If that step fails,
the draft stays pending instead of sending a report without its saved instructions.
A successful retry still needs human approval. No new service or secret is required.

## Install

1. Set repository variable `SURF_REVIEW_ENABLED=false` and let active runs finish.
2. Extract `surf-memory-update-2026-10-31.zip` and upload the matching files to
   branch **main**, preserving folder paths. Do not upload to the state branch.
3. If the previous two-reviewer update is already installed, the functional change
   is `review_bot.py`; also add `tests/test_memory.py` and the updated documentation.
   The complete package includes the matching tests and workflows for earlier versions.
4. Keep `OWNER_TELEGRAM_USER_ID=6723114444` in GitHub Actions secrets and the
   Cloudflare Worker configuration, Leo's existing user ID, and
   `LEO_TELEGRAM_CHAT_ID=-1003835479548` in both services. If two-reviewer support is
   already deployed, no Worker redeployment or database change is needed.
5. Set `SURF_REVIEW_ENABLED=true`. Reply to an active report with the example above.
   Use `/memory` to inspect what was saved. Already published dates are not
   automatically reopened; use the existing manual test checkbox if needed.

On Mac, Command + Shift + . shows `.github` and `.gitignore` when uploading the
complete package. Preserve existing secrets and live review state.

Verification uses mocked Telegram and LLM calls; no live messages, API requests,
remote pushes or deployments are performed while preparing this update.

All **202 Python tests and 24 Worker tests pass**.
