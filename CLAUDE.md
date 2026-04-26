# Project rules for Claude

## Commit messages

- Always under 10 words.
- Never include a `Co-Authored-By:` trailer (or any other co-author attribution).
- Imperative mood, sentence case, no trailing period.

## User identity in the UI

- Never render a SuperTokens `user_id` (or a slice of it) in any user-facing surface.
- Always use the full `display_name`. If absent, use the full `email`. Don't slice the email's local part.
- If neither is available yet, show a placeholder like `Loading…` — never the ID.
