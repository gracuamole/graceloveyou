# graceloveyou surf review bot

Surfline data → coded report → reviewer feedback → Gemini revision → fresh approval → channel publication.

Drafts go to the configured review group. Either allowlisted reviewer can reply with feedback ending in `change`; include `remember` to save instructions for future reports. Reply exactly `correct` to the newest approval prompt to publish. Gemini applies explicit corrections over baseline surf rules and is instructed to preserve unrelated details. Code retains date, numeric and daylight checks. `/memory` lists remembered instructions and `/forget ID` disables one.

## Current operation

- Daily generation opens at **3:07 AM Bali/Singapore time** for the following day's forecast. Cloudflare checks every minute; GitHub's daily backup is `7 19 * * *` UTC.
- Reports display 12-hour AM/PM times. Calculations use complete daylight hours, sunrise rounded up and sunset rounded down.
- Batu Bolong baseline uses nearshore wave energy: below 80 kJ excludes all levels; 80 to below 1,000 permits all subject to other rules; 1,000 or above permits advanced only.
- Beginners use the inside break when breaking-surf height is below 2.5 m and tide rounded half-up to one decimal is at least 0.8 m. Intermediate/advanced use the outside break, with no mid-tide requirement.
- Poor to fair permits all levels; Poor permits beginners only; Very poor excludes all. Missing required data does not qualify.
- Wind/gust km/h values round upward before threshold checks. Wind at least 20 km/h remains eligible with timed windy warnings; beginners get a coach recommendation. Pre-sunrise gusts at least 17 km/h can add a choppiness caution.
- The unused consistency API request is skipped. Bundled fields from needed endpoints are retained.
- Only the report and approval prompt are sent. No detailed-analysis packet is sent.

## Active files

| Path | Role |
|---|---|
| `review_bot.py` | Review state, Gemini feedback/memory, manual rebuild, Telegram approval and delivery |
| `recommendations.py` | Surf rules, daylight windows and report formatting |
| `phase2.py` | Report blocks, splitting and preview entry point |
| `forecast_sources.py` | Forecast validation and provider boundary |
| `main4_pkge_indi.py` | Active Surfline transport and surf-mcp integration; required despite its historical filename |
| `webhook_setup.py` | Inspect, enable or disable the Telegram webhook |
| `surfline_check.py` | Live forecast diagnostic without Telegram delivery |
| `requirements.txt` | Pinned runtime dependencies |
| `review_state.example.json` | Empty setup example, never a replacement for live state |
| `cloudflare/` | Worker webhook/cron, D1 schema, deployment configuration and tests |
| `tests/` | Active offline regressions and forecast fixtures |
| `Archive/` | Retired scripts, workflows, analysis helper and historical guides |

## Active GitHub workflows

- `.github/workflows/surf-review.yml`: generate, process feedback and publish approved reports.
- `.github/workflows/configure-webhook.yml`: manual webhook configuration/inspection.
- `.github/workflows/surfline-check.yml`: manual forecast diagnostic.
- `.github/workflows/phase2-tests.yml`: Python and Worker regression checks.

Run locally without external calls:

```sh
python3 -m unittest discover -s tests -v
node --test cloudflare/worker.test.mjs
```

## Setup and manual runs

See [review operation](REVIEW_WORKFLOW.md), [Cloudflare hosting](FREE_HOSTING.md), and [review-group migration](GROUP_REVIEW.md). Older release-specific instructions are historical and are catalogued in [Archive/README.md](Archive/README.md).

For a manual test, start a new workflow from main with `resend_published` ticked and `move_review_chat` unticked. Reports with saved forecasts rebuild under current rules and reapply report feedback. Already pending revisions/sends complete first. New approval is mandatory; approving a manual repeat can publish a date again intentionally. Scheduled runs do not reopen published reports.

Leave both boxes unticked to retry pending work. Only use `move_review_chat` for an actual destination migration. Do not reset live review state to resolve failures.

## Applying this cleanup

This cleanup moves files; uploading new copies alone will not remove the old GitHub paths. Apply the moves listed in [Archive/README.md](Archive/README.md) on main in the same commit as the updated documentation. In particular, remove the seven archived workflow files from `.github/workflows` after retaining their copies under `Archive/workflows`.

Do not alter the separate `review-state` branch, secrets, Cloudflare configuration or scheduled delivery time. This local cleanup has not been pushed or deployed.
