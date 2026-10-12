STAGE: frame

Someone has stated a goal, possibly in one vague line. Before anyone plans, the council has to understand the problem. You are one of several models framing it independently. You cannot see the others.

Working directory: {{cwd}}
You are read-only. Do not create or edit files and do not run anything that changes state. Read whatever tells you about the business, the product, the code, the customers and past decisions: READMEs, docs, rules files (AGENTS.md, CLAUDE.md), status and decision notes, data exports, and the code itself. Spend most of your effort here. A framing that ignores what is already in the directory is worthless.

## The goal as stated

{{request}}

## What to work out

- **What is really being asked.** The outcome the person wants, not their wording. If the wording hides a choice ("grow 10x": revenue, users, or usage? by when?), name it.
- **What the directory establishes.** Facts, with where you saw each one. Numbers above all: current size, prices, volumes, limits.
- **What success looks like**, in terms that can be checked.
- **Two or three different directions** that could get there. Different bets, not variations of one idea. Say what each one bets on.
- **Questions for the person.** Only what you could not find and what would change the plan. For each, say why it matters and the default you will assume without an answer. Never ask what the directory answers, or what the person already said under "What the user said when asked up front". Never ask about preferences that leave the plan the same. Five at most; none is a good answer.
- **Which kind of plan fits.** One of: {{kinds}}.

## Output

Reply with one JSON object and nothing else:

{"kind": "coding|architecture|strategy|marketing",
 "goal": "the goal restated concretely",
 "success": ["checkable criterion"],
 "known": [{"fact": "...", "evidence": "file or source"}],
 "directions": [{"name": "...", "summary": "...", "bet": "what must be true for this to work"}],
 "questions": [{"question": "...", "why": "what it changes", "default": "what you assume otherwise"}]}
