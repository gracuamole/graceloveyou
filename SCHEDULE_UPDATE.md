# Daily draft at 06:07 Bali/Singapore time

Upload review_bot.py, .github/workflows/surf-review.yml, and the matching tests/docs from this patch to main. Replace the deployed Cloudflare Worker code with cloudflare/worker.mjs and deploy it. Keep the existing Cloudflare Cron Trigger * * * * * unchanged.

The Python generation gate and Worker daily wakeup now open at 06:07 UTC+8. GitHub's backup schedule is 22:07 UTC on the preceding day. Actual delivery depends on GitHub runner availability and forecast retrieval. This still generates tomorrow's report, requires human approval, and does not resend published reports automatically.

After installing, a manual run with both checkboxes unticked can generate a missing next-day draft after 06:07. Do not reset the review-state branch. No new secrets are needed.

Verified locally: 209 Python tests and 26 Worker tests. No deployment, Telegram messages or remote push performed.
