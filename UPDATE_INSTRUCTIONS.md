# Install the report-only update

**Latest: remembered feedback.** Use `surf-memory-update-2026-10-31.zip` and
[REMEMBER_FEEDBACK.md](REMEMBER_FEEDBACK.md). No state reset is needed.

**Earlier update: you or Leo can review.** Use `surf-two-reviewers-update-2026-10-31.zip`
and [TWO_REVIEWERS.md](TWO_REVIEWERS.md). The five matching Python/Worker/workflow
files plus `OWNER_TELEGRAM_USER_ID` in both services allow either person to approve
or request changes. All accepted corrections are logged with their forecast date;
they do not automatically become rules for later days. This version passes
**181 Python tests and 24 Worker tests**. No state reset is needed.

**Earlier update: group review.** The
`surf-group-review-update-2026-10-31.zip` first added group support; see
[GROUP_REVIEW.md](GROUP_REVIEW.md) for the latest migration instructions.
That update includes the report-only behavior below plus matching Python/Worker
group support and an explicit state migration. Its complete suite passes
**164 Python tests and 20 Worker tests**. The older three-file instructions below
describe the report-only change for an existing private-chat deployment.

Leo now receives only the **surf report** followed by its **final approval prompt**.
No detailed surf analysis or Surfline data summary is generated or sent. The latest
report format and rules remain: qualifying windows only, the coached beginner
inside-break exception, full-sentence cautions and complete hours within daylight.

## Update an existing deployment

1. Set repository variable `SURF_REVIEW_ENABLED=false` and wait for active runs to finish.
2. Extract `surf-report-only-update-2026-10-31.zip`.
3. On GitHub branch **main**, replace these three files at their existing paths:
   * `review_bot.py`
   * `tests/test_review_bot.py`
   * `.github/workflows/surf-review.yml`
4. Commit to **main**. The complete matching package passes **148 Python tests**.
   The archive also contains the matching source/tests/docs if earlier updates were missed.
5. Set `SURF_REVIEW_ENABLED=true`.
6. For a private test, start a **new** **Actions → Reviewed next-day surf report →
   Run workflow** from **main** and tick **Send report again for testing
   (fresh approval required)**. Use **Run workflow**, not **Re-run jobs**.

On Mac, press **Command + Shift + .** to show the `.github` folder after extracting.
Keep the workflow at `.github/workflows/surf-review.yml`, not the repository root.
If uploading the complete package, upload its contents including `tests/` and
`.github/`, not the ZIP or an extra enclosing folder. Keep the forecast fixture
under `tests/fixtures/`. No secret, Cloudflare or hosting changes are required.

## Review and publish

* The manual checkbox resends the complete report and a new final prompt, whether
  the report was published or was still awaiting review. It is off by default.
* Reply to the current report or final prompt with feedback ending in lowercase
  `change` to request a revision. Every revised report gets a fresh approval prompt.
* Reply exactly `correct` to the newest final prompt to publish only that report.
* Automatic runs continue to avoid duplicate drafts and posts after publication.
  A retry of the same GitHub run also does not create another test cycle.

## Existing state remains compatible

Do not reset or edit `review-state/state.json` for this update. Existing reports,
feedback, approval records and publication/message history are retained. New approvals
require only complete report delivery and the newest final prompt. Optional old
analysis/data metadata does not block them. Existing recorded bundle approvals keep
their original verification; unresolved send intents still require reconciliation.
A partly delivered older draft skips any remaining optional notes and finishes the
report/prompt. A completed pending review receives nothing extra on an ordinary run.

The retired `review_context.py` and its tests may stay installed as offline reference
utilities. The bot no longer imports the helper, requires it, or calls it to send notes.
They are included in the complete package so existing test sets need no file deletion.
The sender refuses the retired analysis/source send types as an additional guard.

The archive contains no saved live state or credentials. Nothing has been pushed,
deployed or sent to Telegram by this local update.
