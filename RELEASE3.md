# Release 3 — saved forecasts during review

Upload the files from this ZIP to main at their existing paths, including .github/workflows/surfline-check.yml. Install on top of Release 2. No Cloudflare deploy, new secrets or state migration is required.

In the review chat send /status to see the capture time in Bali time. For Release 2 snapshots this is the oldest input capture. For older snapshots the bot uses the stored fetch time if available. An unknown time is labelled explicitly.

Send /dryrun to preview tomorrow’s saved forecast under the current rules, with active remembered instructions applied. It cannot approve or publish a report. If there is no saved forecast for tomorrow, the bot explains this in the review chat. Manual resends use the saved snapshot and preserve feedback history. A legacy published report without a snapshot cannot be rebuilt.

In Actions, open “Surfline forecast check (no Telegram)”. Select main, leave live unchecked, and choose a forecast date with a saved snapshot. This checks saved coverage without spending any Surfline requests. Selecting live explicitly uses Release 2’s shared daily request budget and cooldowns for tomorrow’s forecast.

The scheduled generation path still opens at 3:07 AM Bali time. To roll back, restore the previous Python files, tests and diagnostic workflow together. Keep the review-state branch intact.
