# Release 7 installation

Extract this update ZIP. On the repository’s main branch, upload all included files in one commit, preserving the tests directory. Release 3 is the prerequisite. Existing workflows, Worker, secrets and review-state branch require no setup.

After tests pass, use /dryrun on a saved forecast to inspect the numbered tiers and daylight wave-height line. The next scheduled draft will use the new rules. An already delivered draft retains its original approval prompt.

## What reviewers will see

For Batu Bolong, apply the >15 km/h windy threshold for poor-family ratings and >=20 km/h for fair-family ratings after rounding wind upward. A rounded tide of 0.8 m or more needs at least 400 kJ. Above 0.2 m and below 0.8 m, 60 through 400 kJ inclusive meets the tide/energy requirement for all three tiers. Other known rating, height and energy restrictions still apply.

A feedback acknowledgement confirms the bot saved the correction and is asking the AI. The revised draft and new approval prompt signal success. On a revision failure, reply retry or cancel change directly to the failure message. After cancellation, give replacement feedback on the original approval prompt. Publish by replying correct to the new approval prompt after the revision.

When complete observations have no defined recommendation, the bot asks a question before delivering the draft. Either reviewer can answer in plain English. Gemini interprets which tiers can surf in those conditions. Ambiguous answers or instructions it cannot represent trigger a follow-up. The saved decision applies to the matching rounded tide, nearshore energy, rating, rounded wind and maximum breaking height at Batu Bolong. This conservative scope avoids applying an answer to different conditions without guidance. Known exclusions and missing data follow their existing paths. Explicitly defined physical limits still apply.

Publications and saved Telegram send intents retain their existing protections. If Telegram delivery is uncertain, check the workflow log for the failed step before attempting recovery.

For rollback restore the previous versions of the included scripts and tests together. Keep review-state intact. Resolve an outstanding rule question with Release 7 before rolling back so its reply remains actionable.
