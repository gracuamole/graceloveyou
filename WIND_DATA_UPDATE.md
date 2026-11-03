# Wind rounding and unused data — 3 November 2026

Wind and gust knots are converted to km/h then rounded upward (ceiling) before threshold checks. 19.6 becomes 20; 19.01 also becomes 20; exactly 19 stays 19. Pre-sunrise gusts 16.1 become 17 and trigger the existing caution. Raw knots remain unchanged in saved observations; Gemini receives additional explicitly named rounded km/h values.

The consistency endpoint is no longer requested because its wave-count data is unused. Other feeds still provide needed data, so their bundled fields are retained unchanged: swell directions and power fields, swell probability, wind direction and energy components. No per-field pruning is performed. The package may still emit an empty wave_count field because the consistency feed is skipped.

Existing state and history remain unchanged. Gemini receives a copy of the saved forecast with rounded wind/gust km/h added for analysis; the saved raw knots are not overwritten.

Upload every file in this patch to main, preserving folders. No Worker deployment, schedule change, new secrets or state reset is needed. Use resend_published for a fresh review cycle; previously saved feedback can still change the report under the reviewer-led loop.

218 offline Python tests passed. No live Surfline or Telegram calls and no deployment were performed. Only the pinned adapter source was downloaded for inspection.
