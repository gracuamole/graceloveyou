# Upload the matching surf-report update

This updates an already configured repository. The archive contains matching
Python source, tests, documentation and `.github/workflows/surf-review.yml`.
It includes the manual test checkbox and the new private analysis/data messages.
Cloudflare settings and the other GitHub workflows stay in place.

This version lists only qualifying good windows, keeping the agreed coached
beginner inside-break exception. Cautions use full sentences. Good windows show
just the times; essential restrictions stay short. Sunrise rounds
up and sunset rounds down to whole hours within daylight. Gemini receives only
the target day's complete daylight rows; revised time ranges are checked against
the same window.

## What Leo receives

1. The surf report, with the agreed short format and qualifying windows.
2. A private detailed analysis explaining the included and excluded hours for
   each skill level, with the measurements and thresholds behind the decision.
3. A private Surfline data summary showing saved hourly conditions, source ratings
   such as **Poor to fair**, sunrise/sunset and daylight tide events. Tide bands
   are derived, units/conversions are labelled and original values are preserved.
4. The final approval prompt. Leo must Reply exactly `correct` to this newest
   prompt to publish **only the report** to the channel.

Leo can Reply to the current report, analysis, data or final prompt with feedback
ending in `change`. A revised report is followed by fresh analysis/data and another
approval prompt. Old replies cannot approve the new version. Normal examples fit
one message per document; very long documents are split to respect Telegram's limit.
No additional LLM call is used to prepare the two private evidence documents.

See `REVIEW_PACKET_EXAMPLE.md` for the three messages generated locally from the
saved 1 November 2026 forecast. It contains no Telegram IDs, feedback or credentials.

## Testing after a report was published

After uploading this update, go to **Actions → Reviewed next-day surf report →
Run workflow**, select **main**, and tick **Send another private draft after
publication (testing; fresh correct posts again)**. Then click **Run workflow**.

If tomorrow's report is already published, you receive a fresh **TEST DRAFT**,
private analysis/data and a new final review prompt. Feedback ending in
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
2. Extract the supplied `surf-report-review-evidence-update` ZIP on your computer.
3. In GitHub, open `gracuamole/graceloveyou`, choose branch **main**, then choose
   **Add file → Upload files** at the repository root.
4. Drag in the **contents** of the extracted folder, including its `tests/` and
   `.github/` folders. On Mac, press **Command + Shift + .** to show `.github`.
   Upload the extracted files, not the ZIP or an extra enclosing folder.
   `review_bot.py`, the new `review_context.py`, `surfline_check.py` and
   `webhook_setup.py` must be at the root. Keep test modules under `tests/` and the
   supplied forecast fixture under `tests/fixtures/`. Replace the existing
   `.github/workflows/surf-review.yml`; do not put that YAML file at the root.
   If the manual-test update is already uploaded, the production changes are
   `recommendations.py`, `review_bot.py` and the new `review_context.py`; upload
   the matching `tests/` folder too. The workflow itself is unchanged in this update.
5. Commit these files to **main**. The **Phase 2 rules tests** check should pass
   with 141 Python tests. The tests use mocks rather than live Telegram/LLM calls.
6. Set `SURF_REVIEW_ENABLED=true`. Start a **new** **Reviewed next-day surf report**
   run with branch **main**. Tick the new checkbox to test an already published
   report. Leave it unchecked for normal processing. Do not rerun an old workflow checkout.
7. Saved future-dated pending feedback will be retried. An older pending review
   gets only the missing analysis/data and a new final prompt; its previously sent
   report is not silently rewritten or resent. To refresh it to the new rules,
   Reply to the newest prompt with:
   `Use only qualifying good windows, keep the coached beginner inside exception, and use full sentences in cautions change`
   Every revised draft still needs fresh approval. Already published reports stay
   untouched unless you explicitly tick the manual test checkbox.

Do not modify `review-state/state.json` or reset its history for these test errors.
The archive contains no saved state, credentials, Git repository or Worker settings.
The implementation has not been pushed, deployed or used to send live messages.

## Included Python files

At the repository root:

* `recommendations.py`
* `review_bot.py`
* `review_context.py`
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
* `tests/test_review_context.py`
* `tests/test_surfline_transport.py`
* `tests/test_webhook.py`
* `tests/fixtures/november_1_2026.json` (forecast-only regression fixture)

The remaining files are the README, setup/rule guides and locally generated examples.
The included workflow is `.github/workflows/surf-review.yml`.
