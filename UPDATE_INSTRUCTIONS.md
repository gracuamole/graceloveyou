# Upload the matching surf-report update

This updates an already configured repository. The archive contains matching
Python source, tests, documentation and `.github/workflows/surf-review.yml`.
The reviewed workflow gains a manual test checkbox. Cloudflare settings and
the other GitHub workflows stay in place.

This version minimizes commentary: good conditions show just the times, essential
restrictions stay short, and cautions appear only when they apply. Sunrise rounds
up and sunset rounds down to whole hours within daylight. Gemini receives only
the target day's complete daylight rows; revised time ranges are checked against
the same window.

## Testing after a report was published

After uploading this update, go to **Actions → Reviewed next-day surf report →
Run workflow**, select **main**, and tick **Send another private draft after
publication (testing; fresh correct posts again)**. Then click **Run workflow**.

If tomorrow's report is already published, you receive a fresh **TEST DRAFT** and
new final review prompt in your configured private chat. Feedback ending in
`change` revises it. Reply exactly `correct` to the newest final prompt to post
that version to the configured channel again. Leave it unapproved to keep it private.

The checkbox defaults to off. Automated runs cannot create another test draft;
after a version is published they leave it alone. The earlier publication remains
in state. Rerunning the same Actions run resumes its work without opening another
cycle; a different test needs a new **Run workflow**. An already active review is
not replaced. `/dryrun` is still available for a preview that cannot publish.

## Fix for the pasted test errors

* `ModuleNotFoundError: No module named 'surfline_check'`: add `surfline_check.py`
  at the repository root, beside `review_bot.py`. The forecast tests import it.
* Three webhook inspection tests failing: replace the root `webhook_setup.py`
  with this version. Its inspection now reports transport, Worker status and a
  classified Telegram delivery error, as required by the matching tests.

These failures happen in offline tests. They do not require state edits, new
secrets, Telegram messages or a Cloudflare redeployment.

## Upload steps

1. Set repository variable `SURF_REVIEW_ENABLED=false`. Wait for any active review
   run to finish.
2. Extract the supplied `surf-report-manual-test-update` ZIP on your computer.
3. In GitHub, open `gracuamole/graceloveyou`, choose branch **main**, then choose
   **Add file → Upload files** at the repository root.
4. Drag in the **contents** of the extracted folder, including its `tests/` and
   `.github/` folders. On Mac, press **Command + Shift + .** to show `.github`.
   Upload the extracted files, not the ZIP or an extra enclosing folder.
   `review_bot.py`, `surfline_check.py` and `webhook_setup.py` must be at the root;
   the test files must be directly under `tests/`. Replace the existing
   `.github/workflows/surf-review.yml`; do not put that YAML file at the root.
   If the rest of the latest daylight update is already uploaded, the required
   changes are just `review_bot.py`, `tests/test_review_bot.py` and that workflow.
5. Commit these files to **main**. The **Phase 2 rules tests** check should pass
   with 118 Python tests. The tests use mocks rather than live Telegram/LLM calls.
6. Set `SURF_REVIEW_ENABLED=true`. Start a **new** **Reviewed next-day surf report**
   run with branch **main**. Tick the new checkbox to test an already published
   report. Leave it unchecked for normal processing. Do not rerun an old workflow checkout.
7. Saved future-dated pending feedback will be retried. A report already awaiting
   review needs a Reply on its latest final prompt, such as
   `Use the shorter format and full daylight hours change`. Every revised draft still needs
   fresh approval before publication.

Do not modify `review-state/state.json` or reset its history for these test errors.
The archive contains no saved state, credentials, Git repository or Worker settings.
The implementation has not been pushed, deployed or used to send live messages.

## Included Python files

At the repository root:

* `recommendations.py`
* `review_bot.py`
* `forecast_sources.py`
* `phase2.py`
* `surfline_check.py`
* `webhook_setup.py`
* `main4_pkge_indi.py`
* `requirements.txt`

Tests:

* `tests/test_forecast_sources.py`
* `tests/test_phase2.py`
* `tests/test_recommendations.py`
* `tests/test_review_bot.py`
* `tests/test_surfline_transport.py`
* `tests/test_webhook.py`

The remaining files are the README, setup/rule guides and an offline format example.
The included workflow is `.github/workflows/surf-review.yml`.
