STAGE: present

The council has finished the plan below. Turn it into a short visual summary for the person who asked. They will see this before they read the plan, so it has to be faithful to it: add nothing the plan does not say, and leave out nothing that would change their decision.

Working directory: {{cwd}}
You are read-only. Do not create or edit files.

## Request

{{request}}

## Final plan

{{plan}}

## What to produce

- `headline`: one sentence saying what will be done and the result it should produce.
- `summary`: three to six short bullets with the substance of the plan.
- `numbers`: the three to six figures that matter most (target, baseline, capacity, cost, dates, counts), each as a short label and value. Only figures that are in the plan.
- `diagrams`: one to three diagrams in Mermaid, chosen for what explains this plan best. For an architecture: the components and how data moves between them, and the main flow. For a coding plan: the flow the change introduces, or how the slices build on each other. For a strategy or marketing plan: the funnel with its numbers, or how the bets lead to the target. Each needs a title and a one-line caption.
- `steps`: the steps or slices in order, each with a name, what happens, and how you know it is done.
- `decisions`: the key choices the plan makes and why.
- `risks`: the main risks and how the plan handles each.
- `open_questions`: what still needs the person's decision. Empty if nothing does.

Mermaid rules, so the diagram always draws:

- Start with `flowchart LR`, `flowchart TD` or `sequenceDiagram`. Nothing else.
- Node ids are plain letters and digits, like `A`, `Engine`, `DB1`.
- Put every label in double quotes: `A["Capacity engine"]`, `A -->|"admits lead"| B`. Inside a label use only letters, digits, spaces, commas, slashes, plus and minus. No parentheses, brackets, quotes, colons, semicolons or line breaks.
- At most 14 nodes per diagram. Group with `subgraph Name["Title"]` ... `end` only if it helps.
- In a `sequenceDiagram`, declare participants with `participant A as Short name` and keep message text to plain words.

## Output

Reply with one JSON object and nothing else:

{"headline": "...", "summary": ["..."], "numbers": [{"label": "...", "value": "..."}],
 "diagrams": [{"title": "...", "caption": "...", "mermaid": "flowchart LR\n  A[\"...\"] --> B[\"...\"]"}],
 "steps": [{"name": "...", "what": "...", "done_when": "..."}],
 "decisions": [{"decision": "...", "why": "..."}],
 "risks": [{"risk": "...", "handling": "..."}],
 "open_questions": ["..."]}
