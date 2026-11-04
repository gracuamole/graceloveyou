# Wind warning and all-day format — 2 November 2026

Wind at exactly 20 km/h or above no longer excludes Batu Bolong sessions. Other conditions must still qualify. All-day means every complete daylight hour, not night hours.

All-day headings use “All day is surfable - Inside break” for beginners and “All day is surfable - Outside break” for intermediate/advanced. Otherwise explicit qualifying time windows remain.

Windy hours are merged without bridging excluded hours. Under each level, warnings use the requested wording:
15:00 - 16:00 - forecasted to be windy, coach recommended
15:00 - 16:00 - forecasted to be windy, but up to your personal preference if you want to surf

Pre-sunrise gust and general windy cautions remain conditional on the saved data. Forecast dates are not hardcoded to the example. The 06:07 schedule, remembered feedback, group authorization and approval protections remain.

Upload this complete ZIP to main preserving folders, including matching tests. Do not replace live review-state/state.json. No Cloudflare deployment is necessary if the 06:07 Worker is already installed. For a fresh manual test select resend_published only; existing feedback-pending work may defer regeneration. Nothing is published without fresh approval.

211 Python tests pass, including exact 20 km/h, higher winds, full-day wording and non-bridging gaps. Tests use mocked external services; no live Telegram messages or deployment performed.
