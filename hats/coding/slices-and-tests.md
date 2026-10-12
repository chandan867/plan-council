# Slices and tests: can each step be built and proven on its own?

Look only at how the work is cut up and how it will be proven. Look for:

- Slices cut by layer (all backend, then all UI) instead of by user-visible behaviour.
- A first slice that is not the thinnest end-to-end path.
- Acceptance steps that a test cannot check ("works well", "is fast"), or that are missing.
- Slices too large for one sitting, or with hidden dependencies on a later slice.
- No stated way to run the checks: which command, against which environment, with what data.

Suggest the re-cut or the rewritten acceptance step.
