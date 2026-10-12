1. **Goal and non-goals.** What is true for the user when this is done, and what is deliberately left out.
2. **Current state.** What already exists that this touches. Name the files you actually opened. Say what you looked for and did not find.
3. **Approach.** The design in enough detail that a different engineer could build it. List the alternatives you rejected and why.
4. **Slices.** Vertical slices, each one delivering something a user can see or call (UI, API, data, test together), never one layer at a time. The first slice is the thinnest end-to-end path. Each slice has acceptance steps that an automated test can check.
5. **Risks.** What could go wrong (data, security, performance, rollout) and what the plan does about each.
6. **Assumptions.** Everything you rely on but did not verify, marked as unverified.
7. **Open questions.** Decisions only the human can make.
