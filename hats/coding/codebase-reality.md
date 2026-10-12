# Codebase reality: does the plan match the code that exists?

Open the files the plan names and the ones it should have named. Look for:

- Things the plan says exist that do not, or that work differently (functions, tables, routes, config, env vars).
- Existing code the plan rebuilds instead of reusing.
- Callers, tests or other modules that the planned change breaks and the plan does not mention.
- Project conventions the plan ignores (framework, folder layout, naming, how similar features were built).

Cite file paths and lines. A finding without a path you opened is "unverified".
