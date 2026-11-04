# Archive inventory

These files were moved on 3 November 2026 after tracing the active workflow commands and Python imports. They are historical reference material, not part of the active bot. No live state or secrets were moved.

Archived workflows are intentionally outside `.github/workflows` and cannot be scheduled by GitHub. Do not restore them casually: older scripts may perform live requests or direct sends. Archived documents preserve their historical text and may contain obsolete paths or advice.

| Archived file | Original path | Original purpose | Why archived |
|---|---|---|---|
| [scripts/main.py](scripts/main.py) | `main.py` | Original Open-Meteo daily surf forecast and Telegram sender. | Replaced by Surfline data and the approval-gated review bot. |
| [scripts/main2.py](scripts/main2.py) | `main2.py` | Combined unofficial Surfline forecasts with Open-Meteo wave heights. | Replaced by the current Surfline-only adapter and durable review workflow. |
| [scripts/main3_package.py](scripts/main3_package.py) | `main3_package.py` | Early surf-mcp and curl_cffi transport plus forecast formatting. | Replaced by main4_pkge_indi.py; no current workflow or test imports it. |
| [scripts/test_curl.py](scripts/test_curl.py) | `test_curl.py` | Live comparison of requests and browser-impersonating HTTP transports. | Successful methods are implemented and regression-tested in the active adapter. |
| [scripts/test_surfline.py](scripts/test_surfline.py) | `test_surfline.py` | Live smoke test of package metadata and full forecast calls. | Superseded by surfline_check.py and its manual workflow. |
| [scripts/test_surfline2.py](scripts/test_surfline2.py) | `test_surfline2.py` | Exploration of wave/swells endpoint names. | Endpoint discovery is complete; current diagnostics use surfline_check.py. |
| [analysis/review_context.py](analysis/review_context.py) | `review_context.py` | Generated detailed reasoning and source-summary messages. | The Telegram product now sends only the report and approval prompt; retained here for offline reference. |
| [analysis/tests/test_review_context.py](analysis/tests/test_review_context.py) | `tests/test_review_context.py` | Regression tests for the retired analysis/source-summary helper. | Moved with the helper; not part of the active report-delivery suite. |
| [workflows/daily_forecast.yml](workflows/daily_forecast.yml) | `.github/workflows/daily_forecast.yml` | Scheduled an earlier bot or transport experiment. | Already disabled; surf-review.yml is the current approval-gated workflow. Archived workflows are outside GitHub Actions discovery. |
| [workflows/daily_forecast2.yml](workflows/daily_forecast2.yml) | `.github/workflows/daily_forecast2.yml` | Scheduled an earlier bot or transport experiment. | Already disabled; surf-review.yml is the current approval-gated workflow. Archived workflows are outside GitHub Actions discovery. |
| [workflows/daily_forecast3.yml](workflows/daily_forecast3.yml) | `.github/workflows/daily_forecast3.yml` | Scheduled an earlier bot or transport experiment. | Already disabled; surf-review.yml is the current approval-gated workflow. Archived workflows are outside GitHub Actions discovery. |
| [workflows/daily_forecast4.yml](workflows/daily_forecast4.yml) | `.github/workflows/daily_forecast4.yml` | Scheduled an earlier bot or transport experiment. | Already disabled; surf-review.yml is the current approval-gated workflow. Archived workflows are outside GitHub Actions discovery. |
| [workflows/test_curl.yml](workflows/test_curl.yml) | `.github/workflows/test_curl.yml` | Scheduled an earlier bot or transport experiment. | Already disabled; surf-review.yml is the current approval-gated workflow. Archived workflows are outside GitHub Actions discovery. |
| [workflows/test_surfline.yml](workflows/test_surfline.yml) | `.github/workflows/test_surfline.yml` | Manually ran the corresponding legacy Surfline probe. | Superseded by surfline-check.yml; moved with the probe script. |
| [workflows/test_surfline2.yml](workflows/test_surfline2.yml) | `.github/workflows/test_surfline2.yml` | Manually ran the corresponding legacy Surfline probe. | Superseded by surfline-check.yml; moved with the probe script. |
| [docs/PHASE2.md](docs/PHASE2.md) | `PHASE2.md` | Original phase-two recommendation design and thresholds. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/PLAN_REVIEW.md](docs/PLAN_REVIEW.md) | `PLAN_REVIEW.md` | Evaluation of the free-hosting architecture proposal. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/REVIEW_PACKET_EXAMPLE.md](docs/REVIEW_PACKET_EXAMPLE.md) | `REVIEW_PACKET_EXAMPLE.md` | Example of the retired report plus analysis/source packet. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/SIMPLE_REPORT_EXAMPLE.md](docs/SIMPLE_REPORT_EXAMPLE.md) | `SIMPLE_REPORT_EXAMPLE.md` | Earlier report-format example with superseded thresholds. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/UPDATE_INSTRUCTIONS.md](docs/UPDATE_INSTRUCTIONS.md) | `UPDATE_INSTRUCTIONS.md` | Incremental installation instructions for earlier report-only releases. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/BATU_RULES_UPDATE.md](docs/BATU_RULES_UPDATE.md) | `BATU_RULES_UPDATE.md` | First Batu Bolong-specific rule update and installation notes. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/FEEDBACK_LOOP_UPDATE.md](docs/FEEDBACK_LOOP_UPDATE.md) | `FEEDBACK_LOOP_UPDATE.md` | Release notes for reviewer-led Gemini revisions. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/MANUAL_REBUILD_UPDATE.md](docs/MANUAL_REBUILD_UPDATE.md) | `MANUAL_REBUILD_UPDATE.md` | Release notes for manual rebuild and feedback reapplication. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/SCHEDULE_UPDATE.md](docs/SCHEDULE_UPDATE.md) | `SCHEDULE_UPDATE.md` | One-time migration from 09:07 to 06:07. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/WIND_DATA_UPDATE.md](docs/WIND_DATA_UPDATE.md) | `WIND_DATA_UPDATE.md` | Release notes for whole-km/h rounding and unused request handling. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/WIND_UPDATE.md](docs/WIND_UPDATE.md) | `WIND_UPDATE.md` | Release notes for windy-period warnings and all-day wording. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/TWO_REVIEWERS.md](docs/TWO_REVIEWERS.md) | `TWO_REVIEWERS.md` | One-time release/setup notes adding the second reviewer. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |
| [docs/REMEMBER_FEEDBACK.md](docs/REMEMBER_FEEDBACK.md) | `REMEMBER_FEEDBACK.md` | One-time release/setup notes adding persistent feedback memory. | Historical release document, not a runtime dependency. Current operation is summarized in the root README; historical assumptions may be superseded. |

## Retained active files

`main4_pkge_indi.py` remains because forecast_sources.py imports its working Surfline adapter. `phase2.py` still builds report blocks and supports offline previews. Active tests and fixtures remain in tests/. The Cloudflare Worker, schema, deployment config and tests remain in cloudflare/. Operational guides FREE_HOSTING.md, REVIEW_WORKFLOW.md and GROUP_REVIEW.md remain available.

For optional archived analysis tests, from repository root run `PYTHONPATH=.:Archive/analysis python3 -m unittest discover -s Archive/analysis/tests -v`. These tests are not run by production workflows.

The archived analysis test fixture path was adjusted to use the retained tests/fixtures directory. Its original assertions are preserved.
