# Build or buy: what should not be built at all?

Assume part of this design already exists as a product, a managed service or a library. Look for:

- Custom components that a well-known service or library provides, especially ones that are hard to run well (queues, auth, email delivery, search, billing).
- The opposite: a bought dependency for something small, which adds cost, lock-in or a failure point for little gain.
- A simpler design that meets the stated scale with fewer moving parts. Fewer services, one database, a cron job in place of a pipeline.
- Parts built for a future scale or feature nobody asked for.

For each, say what is saved and what is given up.
