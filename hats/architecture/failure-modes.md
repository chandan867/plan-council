# Failure modes: what breaks first, and what happens then?

Assume the design is built as written and runs at the target scale for a month. Look for:

- The component that fails first under load, a slow dependency, or bad input, and what the user sees when it does.
- Work in flight when something dies: is it lost, duplicated, or stuck? Is there a retry, and is the operation safe to retry?
- An outside provider changing a limit, a price or a rule, or blocking the account. What stops working?
- Things that fail silently, where nobody would know for days.
- A flow the design describes only for the happy path.

Rank by likelihood times damage. Skip remote hypotheticals.
