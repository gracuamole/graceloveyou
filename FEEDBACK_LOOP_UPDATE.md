# Reviewer-led feedback loop

The initial report is built from Surfline data and coded surf rules. Gemini receives the current report, current-day forecast, baseline rules, saved remembered instructions and current feedback. Explicit report corrections override baseline recommendations; newer corrections win conflicts. Gemini is instructed to change only what was requested and preserve unrelated timings, warnings and cautions.

Automatic wind-warning restoration and the rigid required-windy-line rejection were removed. Code no longer silently reverses an intentional change to a wind warning. Preservation of unrelated content is prompt-guided, not guaranteed; the next human review remains necessary. Numeric/date/spot/daylight checks and publication authorization still apply. Existing simple note: commands retain their append-only shortcut.

Feedback containing remember and ending in change remains stored for future reports. Ordinary feedback remains tied to the current report. Remembered instructions may override baseline recommendations but cannot substitute an old day's measurements for fresh observations. Manual rebuild starts from the saved forecast under current rules, then reapplies report-specific feedback with reviewer corrections taking priority. This supersedes the previous latest-rules-always-win behavior.

No changes to the 06:07 schedule, reviewer allowlist, exact correct approval, state persistence, publication deduplication or uncertain-send handling.

Upload the files in this patch to main, preserving folders. If a draft is pending from the old windy-warning validation failure, run a new workflow with both boxes unticked to retry it. For an already delivered draft, reply with new feedback or use resend_published to rebuild and reapply its feedback. Keep move_review_chat unticked. Do not reset saved state. No Cloudflare deployment needed.

216 offline Python tests passed. No live LLM request, Telegram message, remote push or deployment performed.
