# Pre-mortem: it shipped and failed, why?

Assume the plan was followed exactly and three weeks later the result is a failure. Work backwards to the most likely causes. Look for:

- The step most likely to take far longer than planned, and why.
- Behaviour at the edges the plan is silent on: empty state, errors, slow network, concurrent users, large inputs, old data.
- A dependency (service, library, permission, another team) that the plan assumes will just work.
- An assumption that, if false, makes most of the plan wasted work. Say how to test it first, cheaply.

Rank by likelihood times damage. Skip remote hypotheticals.
