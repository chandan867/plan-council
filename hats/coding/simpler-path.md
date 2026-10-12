# Simpler path: what can be cut or reused?

Assume the plan is twice as large as it needs to be and find the half to remove. Look for:

- Work that does not serve the stated goal, or serves a future need nobody asked for.
- New abstractions, services, tables or config where a small change to existing code would do.
- A library or platform feature already in the project that replaces planned custom code.
- A smaller first version that would prove the idea before the rest is built.

For each cut, say what is lost and why that is acceptable.
