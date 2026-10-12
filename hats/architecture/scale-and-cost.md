# Scale and cost: do the numbers work?

Redo the arithmetic. Look for:

- Capacity claims with no calculation, or a calculation that is wrong. Recompute throughput, storage and concurrency at the target scale.
- Provider quotas, rate limits and per-unit prices the design would exceed or that make it uneconomic. Cite the limit.
- The cost per user, message or record at target scale, and how it compares to what the business earns from one.
- A component sized for a scale far above or far below what the goal states.
- Growth that is not linear: fan-out, retries, indexes, logs.

Show your numbers. A finding without arithmetic is "unverified".
