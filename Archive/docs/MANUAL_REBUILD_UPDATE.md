# Manual resend rebuild fix — 2 November 2026

For reports with a saved daily forecast, resend_published now rebuilds from that snapshot using current rules, even when previous feedback exists or the report was published. It archives the complete old report and feedback, supplies the dated feedback log (or legacy latest feedback) to Gemini, and explicitly gives current application rules priority over conflicting edits or standing memory. Compatible edits are reapplied. It does not fetch new observations when a saved daily snapshot exists.

The rebuilt draft is durably saved before revision. Reapplication failure leaves it pending and sends no partial report. A successful revision requires new approval; old approval IDs do not apply. Existing uncertain-send checks and per-run deduplication remain. This is a prompt-guided reapplication with existing numeric/date/daylight validation, not a guarantee of perfect LLM interpretation; reviewers still assess the new draft.

Legacy pending drafts without daily observations retain their previous text with an explicit diagnostic; published legacy reports may fetch a forecast. A report with an already pending revision/send/publication still defers manual rebuilding until that operation finishes.

Install the two code/test files in this patch on main: review_bot.py and tests/test_manual_rebuild.py. Keep the latest wind-rule recommendations.py and other matching tests already installed. No Cloudflare or workflow change is required. Do not edit/reset review-state/state.json.

Start a new workflow from main, tick resend_published, leave move_review_chat unticked. Look for: Manual draft rebuilt from saved forecast using latest rules. The report goes to the review group for fresh approval. Approving a manual repeat can intentionally publish an already-published date again.

Verified locally: 214 Python tests passed. No Telegram messages, live LLM calls, deployment or remote push performed.
