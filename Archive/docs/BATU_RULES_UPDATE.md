# Batu Bolong rules — 1 November 2026

These spot-specific rules supersede the older Batu Bolong thresholds in prior guides.
Other spot names retain the previous policy. Names containing Batu Bolong select this policy.

- Wave energy uses energy.nearshore, not swell_power_total. The user confirmed the wave-energy interpretation in kJ.
- Below 80: no levels. 80 inclusive to below 1000: all levels subject to other rules. At least 1000: advanced only.
- Yellow/POOR_TO_FAIR permits all levels. Orange/POOR permits beginners inside only; it is not automatically described as too small. VERY_POOR still excludes all levels.
- Beginners: inside break, upper breaking-surf forecast strictly below 2.5 m, tide rounded half-up to one decimal at least 0.8 m. Thus 0.75 and 0.79 qualify, 0.749 does not. Inside wave height is not separately forecast.
- Intermediate/advanced: outside break. No intermediate mid-tide requirement or old 4 ft/period cutoff. Low tide excludes inside recommendations only.
- Wind at or above 20 km/h remains eligible when other conditions qualify. Each level lists merged windy periods: beginners coach recommended; intermediate/advanced personal preference. When all rounded daylight hours qualify, show All day is surfable with the inside/outside label. A rising wind/gust trend approaching 20 (at least 17 km/h wind), or any wind at least 20, adds the general windy caution.
- Target-date gusts at least 17 km/h before actual sunrise add a possible-choppiness caution. Evening and other-day gusts do not trigger it. Missing gusts are not invented.
- Sessions remain sunrise rounded up through sunset rounded down. No extra analysis messages are sent.
- Missing required height, energy, wind, tide or rating excludes a window. High energy cautions remain for advanced-only windows.
- LLM revisions and remembered instructions receive the same updated eligibility windows and cautions. Human approval and duplicate-post protections remain unchanged.

## Upload

1. Pause processing with SURF_REVIEW_ENABLED=false and let active runs finish.
2. Extract surf-batu-rules-2026-11-01.zip and upload its contents to main, preserving folders. Include the matching tests. Do not replace live review-state/state.json.
3. Re-enable processing. Start a new manual workflow from main with resend_published ticked and move_review_chat unticked to refresh an unedited pending or published report for testing.
4. A report with saved reviewer edits may retain those edits during manual testing. Future dates use the new rules. Every new draft still needs fresh correct approval; approving a manual repeat may deliberately publish that date again.

If the diagnostic Worker is already deployed, no Worker/settings change is needed for these Python rules. The ZIP includes the matching Worker for completeness.

Verified: 209 Python tests and 26 Worker tests, with mocked external services. The saved November 2 source reproduces 06:00–18:00 for all levels, inside for beginners and outside for others. No live messages, deployments or remote pushes were performed.
