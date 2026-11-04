# Release 1 — 3:07 AM, measurements and dependency caching

## Prepared locally, not deployed

The working baseline is the cleaned local repository. Compared with public GitHub commit
`e65dc764e6388036516a24d561487d25217c8048`, the active Python implementation and
active workflows matched before this release. The local Worker already contained the
6:07 schedule and later diagnostic changes; GitHub still had 9:07. Local cleanup and
archive moves were also not reflected remotely. Existing local changes are preserved.
The live Cloudflare deployment and dashboard settings have not been inspected.

## Changes

- `review_bot.py`: one generation-time constant, 03:07 gate/status, timings for state
  saves, Git pushes, Telegram calls, and Gemini/OpenAI revisions; run summary on exit.
- `forecast_sources.py`: total fetch/validation timing.
- `main4_pkge_indi.py`: numeric per-request status, attempt, transport, request kind and
  duration. Request order, fallback behavior and retry counts are unchanged.
- `run_log.py`: allowlisted JSON events and GitHub Actions summary, without message
  content, URLs, response bodies, exception messages or credentials. Logging I/O failure
  does not change approval/delivery behavior. Endpoint duration excludes retry sleeps;
  full fetch duration includes them. State-save duration includes Git-push duration.
- `surfline_check.py`: writes the same summary, including on failure.
- `.github/workflows/surf-review.yml`: 19:07 UTC backup and matching webhook-mode
  condition, plus pip cache. Full runtime tests remain in this release.
- `.github/workflows/surfline-check.yml`: pip cache; still a live diagnostic for now.
- `cloudflare/worker.mjs` and its tests: daily gate at 03:07 Bali; one-minute trigger unchanged.
- `tests/test_run_log.py`: privacy, failure timing, summary, I/O resilience and real
  main-path generation boundary tests at 03:06 and 03:07.
- README and operational guides: current schedule updated. Archive documents remain historical.

There is no durable forecast cache or cooldown implementation yet. Summaries explicitly
mark those metrics unavailable until Release 2. No data, state schema, D1 schema, secrets,
report rules, reviewer identities, approval requirements or publication safeguards changed.

## Install after reviewing the update

1. Use `main`, never `review-state`. Back up the current source and deployed Worker.
2. Reconcile the existing cleanup first. A full ZIP upload does not remove old remote
   workflows; move the retired files listed in `Archive/README.md`, including their old
   workflow paths. Do not delete or replace live state, including any existing root
   `state.json`, as part of installing this ZIP.
3. Keep the schedule change in its own commit. The accompanying patch series is against
   the cleaned local baseline: apply `01-schedule.patch`, test and commit, then apply
   `02-measurements-cache.patch`, test and commit. Do not apply these patches blindly
   to the older remote tree. Alternatively upload the full ZIP as the reviewed final
   file set if separate commits are not practical.
4. Deploy the updated `cloudflare/worker.mjs` separately. Keep the existing D1 database,
   bindings, secrets, enablement settings and one-minute `* * * * *` trigger. No database
   migration or webhook re-registration is required. Do not replace live settings with
   the placeholder database ID or disabled example configuration in `wrangler.jsonc`.
5. Verify the deployed Worker gate is `3 * 60 + 7`. In GitHub, verify BOTH the cron
   and webhook-mode schedule condition use `7 19 * * *`.
6. After deployment, observe the next scheduled run rather than resending a report.
   Generation still requires recorded /start and no existing next-day report. A manual
   run after 03:07 can send a missing draft: it is not a harmless diagnostic.
7. Collect two or three mornings of measurements before Release 2. Check the Actions
   summary and installation step duration. A later run should show pip cache restoration.
   This caches downloads/builds, not installed environments or forecast data; install
   still runs and a pinned Git dependency may still require a clone.

3:07 AM Bali/Singapore is 19:07 UTC on the preceding day. This starts generation of
TOMORROW's report, not today's. Queueing and fetch time can delay delivery. The full
forecast may not yet be available at that hour; record failures without running repeated
live diagnostics. Until Release 2, existing retry behavior remains in place.

## Verification and rollback

Offline: `python3 -m unittest discover -s tests -v` and
`node --test cloudflare/worker.test.mjs` (Node with node:sqlite, as in CI).
New tests mock all services. No live Surfline, Gemini or Telegram requests are needed.

Rollback schedule with its isolated commit/patch AND restore the corresponding Worker
version. Roll back instrumentation/cache separately if needed. Never reset review-state
or clear send intents. No new runtime feature switch is needed for the schedule; logging
is passive and fail-open, and pip caching is controlled by the two workflow settings.

Local checks cannot confirm deployment, delivery, GitHub cache speed or morning data
availability. Those checks remain pending until you approve and perform rollout.
