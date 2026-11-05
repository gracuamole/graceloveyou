# Editable location display
Upload review_bot.py and tests/test_review_bot.py to their existing paths on main.
Requires the installed Release 1 files, including run_log.py. No Worker deployment.
Location labels are editable by Gemini under reviewer feedback; the underlying saved
forecast identity and source are unchanged. Date, numeric/daylight validation and fresh
approval safeguards remain. Gemini is instructed to preserve the current label on later
unrelated edits. Use remember change if the instruction should apply to future reports.
After tests pass, start a NEW Reviewed next-day surf report workflow run from main with
both manual boxes unticked. Existing pending feedback is retried; do not reset state or
clear delivery intents. The revised report still needs fresh correct approval.
Offline verification: 218 Python tests and 26 Worker tests passed. No live messages sent.
