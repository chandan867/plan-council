# Data and security: what could be lost, leaked or left inconsistent?

Look for:

- Schema or data changes with no migration, no backfill, or no way back.
- Who is allowed to do the new thing, and where that is enforced (server side, not only in the UI).
- User input that reaches a query, a shell, a file path, a prompt or HTML without validation.
- Secrets, tokens or personal data that end up in code, logs, URLs or client bundles.
- Partial failure: what state is left if step two of three fails.

If the plan touches none of this, say so in the summary and return no findings.
