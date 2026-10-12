1. **Goal, scale and non-goals.** What the system must do, for how many users or messages or records, at what cost and by when. What is left out.
2. **Constraints.** The hard limits that shape the design: external providers and their rules and quotas, compliance, existing systems it must fit, team size.
3. **Current state.** What already exists in this directory that the design builds on or replaces. Name the files you opened.
4. **Design.** The components, what each owns, how data moves between them, and where state lives. Include the main flows step by step and the data model.
5. **Key decisions.** Each important choice (build or buy, which store, sync or queue), the options considered, and why this one. Say what would make you change it.
6. **Numbers.** Capacity, throughput, storage and running cost at the target scale, with the arithmetic shown.
7. **Failure and operations.** What breaks first under load or bad input, how it is detected, and what happens to data in flight.
8. **Build order.** Vertical slices, the first being the thinnest end-to-end path that proves the riskiest assumption. Each with a checkable acceptance step.
9. **Assumptions and open questions.** What you did not verify, and decisions only the human can make.
