# Upload the matching surf-report update

This updates an already configured repository. The archive contains matching
Python source, tests and documentation for the simple grouped report format.
Existing GitHub workflows and Cloudflare settings stay in place.

This version minimizes commentary: good conditions show just the times, essential
restrictions stay short, and cautions appear only when they apply. Sunrise rounds
up and sunset rounds down to whole hours within daylight. Gemini receives only
the target day's complete daylight rows; revised time ranges are checked against
the same window.

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
2. Extract the supplied `surf-report-update` ZIP on your computer.
3. In GitHub, open `gracuamole/graceloveyou`, choose branch **main**, then choose
   **Add file → Upload files** at the repository root.
4. Drag in the **contents** of the extracted folder, including its `tests/`
   folder. Upload the extracted files, not the ZIP or an extra enclosing folder.
   `review_bot.py`, `surfline_check.py` and `webhook_setup.py` must be at the root;
   the test files must be directly under `tests/`.
5. Commit these files to **main**. The **Phase 2 rules tests** check should pass
   with 106 Python tests. The tests use mocks rather than live Telegram/LLM calls.
6. Set `SURF_REVIEW_ENABLED=true`. Start a **new** **Reviewed next-day surf report**
   run with branch **main**. Do not rerun an old workflow checkout.
7. Saved future-dated pending feedback will be retried. A report already awaiting
   review needs a Reply on its latest final prompt, such as
   `Use the shorter format and full daylight hours change`. Every revised draft still needs
   fresh approval before publication.

Do not modify `review-state/state.json` or reset its history for these test errors.
The archive contains no saved state, credentials, Git repository or Worker settings.

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
