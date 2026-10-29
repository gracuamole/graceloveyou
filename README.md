# graceloveyou
Automated posts for leo


## Phase 2 surf recommendations

Run `python phase2.py` for a preview using the existing Surfline/curl_cffi integration.
Direct publishing is disabled. Reports now require Leo’s review before channel publication.
See [PHASE2.md](PHASE2.md) for rules, assumptions, tests and operational limits.

## Telegram human review

See [REVIEW_WORKFLOW.md](REVIEW_WORKFLOW.md) for the private draft → Leo feedback →
revision → exact `correct` approval → channel workflow, deployment setup, durable
state and uncertain-delivery recovery. It is disabled until explicitly configured.

Run `python3 -m unittest discover -s tests -v` for offline verification.
