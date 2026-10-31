# graceloveyou

Reports use the simple grouped format: forecast date, spot and qualifying
beginner/intermediate/advanced time windows. Good windows show just the times;
the coached beginner inside-break exception keeps its short restriction.
Cautions use full sentences. Conditional/poor-to-fair periods are omitted from
recommended times and explained in Leo's private analysis. Analysis uses full hours inside sunrise–sunset,
rounding sunrise up and sunset down. See [PHASE2.md](PHASE2.md) for grouping
rules and [REVIEW_WORKFLOW.md](REVIEW_WORKFLOW.md) to update an existing deployment.
Use [UPDATE_INSTRUCTIONS.md](UPDATE_INSTRUCTIONS.md) for the complete matching
source/test file list, including the required forecast-check and webhook helpers.

Automated posts for leo


## Phase 2 surf recommendations

Run `python phase2.py` for a preview using the existing Surfline/curl_cffi integration.
Direct publishing is disabled. Reports now require Leo’s review before channel publication.
See [PHASE2.md](PHASE2.md) for rules, assumptions, tests and operational limits.

## Telegram human review

See [REVIEW_WORKFLOW.md](REVIEW_WORKFLOW.md) for the private draft → Leo feedback →
revision → exact `correct` approval → channel workflow, deployment setup, durable
state and uncertain-delivery recovery. It is disabled until explicitly configured.

Each initial or revised draft is followed privately by **Detailed surf analysis**
and a **Surfline data summary**, then the final approval prompt. The analysis
explains included/excluded hours for each skill level. The data summary shows
hourly values from the unchanged saved forecast, including actual rating labels
such as **Poor to fair**. Feedback ending in `change` can Reply to any current
review message; exact `correct` must Reply to the newest final prompt. Only the
report is published. See [REVIEW_PACKET_EXAMPLE.md](REVIEW_PACKET_EXAMPLE.md) for
an example generated from the saved 1 November forecast.

Run `python3 -m unittest discover -s tests -v` for offline verification.

To test again after publication, start a new **Reviewed next-day surf report** run
from `main` and tick **Send another private draft after publication**. It sends a
fresh next-day test draft to the configured reviewer. Only a new exact `correct`
Reply on its final prompt can post it to the channel again. The checkbox defaults
to off; scheduled runs and ordinary webhook dispatches never reopen published
reports. Earlier publications stay in state, and rerunning the same GitHub run
does not start another test cycle. See [UPDATE_INSTRUCTIONS.md](UPDATE_INSTRUCTIONS.md).

## Faster replies with free hosting

[FREE_HOSTING.md](FREE_HOSTING.md) describes the prepared Cloudflare Workers Free +
D1 webhook option. Telegram replies wake the existing GitHub workflow; Gemini and
approval/publication state remain in the existing deployment. Nothing requires a
paid server. Account/free-tier limits apply. Hosting is not activated automatically.

[PLAN_REVIEW.md](PLAN_REVIEW.md) explains the adopted improvements and why the
working Surfline/Gemini workflow is retained. Private `/status` and `/dryrun`,
LLM-free `note:` edits, numeric checks and durable failure notices are included.
