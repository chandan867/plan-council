---
name: plan-council
description: Turn a goal, however vague ("grow this business 10x", "design the architecture for X", "plan this feature"), into a checked plan using a council of AI models. Several models frame the goal and work out the few questions worth asking the user, compete on drafts, attack the winner through different lenses, and return only the disagreements they could not settle. Works for coding, architecture, business strategy and marketing, across Claude Code, Codex, Pi and OpenCode. Use when the user states a goal or asks for a plan, a spec, a strategy, an architecture, a second opinion on a plan, or a council, debate, swarm, arena or multi-model review, and before building anything large.
metadata:
  opencode/slash: "true"
---

# Plan council

You are the operator. The work is done by `council.py`, which sits next to this file. Below, `COUNCIL` means `python3 <folder containing this SKILL.md>/council.py`. Run it from the project the plan is about. Never edit files inside the skill folder.

## 1. Check the setup

Run `COUNCIL detect`. It prints JSON:

- `clis`: the agent CLIs installed on this machine and the models each can run.
- `config`: the saved lineup, or `null` if there is none yet.
- `suggested`: a lineup built from what is installed.
- `notes`: warnings about the suggestion, for example that only one model is known. Act on them in step 2.

If `config` is not null and the user has not asked to change models, say the lineup in one line and go to step 3.

## 2. Set the lineup (first use, or when the user asks to change models)

Show the user, briefly, which CLIs and models were found and the `suggested` lineup. Ask them to confirm or change it. Use your question tool if you have one. Guidance when they ask what to pick:

- **Planner:** their strongest model.
- **Critics:** two or three, from vendors other than the planner's where possible. Different vendors miss different things, which is the reason this exists.
- **One CLI, several models** (for example only OpenCode or only Pi): pick models from different vendors inside that CLI.
- **One CLI, one vendor** (for example only Claude Code): use different models of that vendor. It still helps, less.
- **Verifier:** a critic that is not the planner's model.
- A model the user names that is not in the list is fine; pass it as typed. Leaving the model out means that CLI's default.

Save it:

```
COUNCIL configure --planner claude:opus --critic gpt=codex --critic grok=pi:provider/model --verifier gpt
```

Each role is `CLI` or `CLI:MODEL`; each critic is `NAME=CLI[:MODEL]`. Add `--local` to save it for this project only (`.council/config.json`, which a team can commit) instead of for the user.

## 3. Ask the user a few questions first

Do this yourself, before any council command, so the models do not each guess a different meaning.

1. Take a quick look at the project (top-level files, README, rules files, status notes) and at what the user already said. One or two minutes, not a study.
2. Ask the user two to four short questions, in one go. Use your question tool if you have one, with a sensible option marked as the default. Ask only what you could not see for yourself, picking from:
   - **Outcome:** which reading of the goal they mean, and what result would make them say it worked ("10x" of what, by when).
   - **Scope:** which product, part of the system or audience this covers, and what is out.
   - **Constraints:** deadline, budget, team, and tools or vendors that must stay or must go.
   - **Already decided or tried:** choices that are fixed, and approaches that failed.
3. Write the questions and the user's answers, in their words, to a file such as `.council/intake.md`. If they skip one, write "no answer". If they say "just go", write that and move on.

Keep it short. The council asks deeper questions later, after it has read the project; this step only stops it from solving the wrong problem. Skip the step when the request is already specific and leaves nothing to interpret.

Pass the file to the next command with `--context .council/intake.md`.

## 4. Choose the path

- **The user stated a goal, not a task** ("grow 10x", "build the tech architecture for cold email", "fix our onboarding"), or success still needs defining: go to step 5.
- **The request is already specific** (a named feature, a bounded change) or the user has a plan to review: skip to step 6 and pass the request directly.

When unsure, frame. It costs a few minutes and stops the council from planning the wrong problem.

Pass the goal in the user's own words. Do not narrow or reinterpret it yourself; their answers from step 3 go in the context file. Put a long request in a file and use `--file FILE`.

## 5. Frame the goal and ask the deeper questions

```
COUNCIL frame --detach --context .council/intake.md "the goal in the user's words"
COUNCIL status --wait 100
```

The first command prints a `watch` line with the path of `report.html`. Give that path to the user straight away: opened in a browser, it shows every step as it finishes, model by model (each framing, each draft, the judge's scores, each critic's findings, what the planner decided and what the verifier said). It refreshes by itself while the run is going. `COUNCIL view` opens it for them.

Repeat `status` until its `state` line says `done` or `failed`. Up to three models read the project independently and the planner merges their framings into `brief.md` in the run folder.

Then:

1. Read `brief.md`. Tell the user in a few lines how the council understood the goal, what it found in the project, and the directions it sees.
2. If `QUESTIONS.md` exists, ask the user those questions, with the reason and the default for each. Use your question tool if you have one. These are the only things the council could not find out and that would change the plan. Do not add questions of your own and do not answer for the user.
3. Write the answers to a file, one per question, in the user's words. If the user skips a question, write "no answer". If they correct the brief itself, put that in the same file.

## 6. Run the council

Framed goal:

```
COUNCIL plan --detach --from latest --answers answers.md
```

Specific request, or an existing plan to review:

```
COUNCIL plan --detach --context .council/intake.md "the request"
COUNCIL plan --detach --plan FILE "what the plan is for"
```

Options:

- `--kind coding | architecture | strategy | marketing`. After `frame` the kind is already chosen; otherwise the default is coding.
- `--depth quick` (default) or `--depth full` for more lenses, when the task is large or risky or the user asks for thorough.
- `--arena`: several models each draft the plan, a judge from another vendor compares them and the planner combines the best parts. On by default after `frame` and at full depth. Use `--no-arena` to save time.

Follow it the same way:

```
COUNCIL status --wait 100
```

A quick run takes around ten minutes, a framed or full run longer. Keep `--wait` below your own command timeout; 100 seconds is safe everywhere. Between polls, tell the user in a few words which stage it is on.

If a command fails because of a sandbox, a blocked network, or a CLI that is not logged in: the council starts other agent CLIs, which need network access and their own login. Ask the user to allow the command or to log in to that CLI. Do not work around it.

## 7. Report back

The last lines of `status` give the run folder and the files in it.

0. Give the user the `report` path from `status` (or run `COUNCIL view` to open it). It is the full record, from the first framing to the final plan, with which model said what.
1. If `NEEDS-YOU.md` exists, read it first. For each item give the user the finding, the planner's answer and why they disagree, and ask for a decision. These are the only points where the models could not agree.
2. Read `summary.json` (and `plan.md` for detail) and present the plan visually, not as a wall of text: the headline, the key figures as a small table, the steps in order, the key decisions and the main risks. Show each diagram as a `mermaid` code block if your interface draws them; either way, tell the user the report shows them drawn at the top, under "The plan at a glance".
3. Say in one or two lines what the council did, from `arena.md` and `ledger.md`: which candidate became the base, how many findings were raised and how many were accepted.
4. After the user decides the open items, edit `plan.md` in the run folder to match. If they want the plan somewhere else in the project, copy it there.

Do not start carrying out the plan unless the user asks.

## Other commands

- `COUNCIL summarize`: rebuild the visual summary after `plan.md` was edited.
- `COUNCIL view`: open the latest run's report in the browser (`--run DIR` for another run).
- `COUNCIL doctor`: human-readable check of CLIs and lineup.
- `COUNCIL plan --dry-run ...`: show who would do what, run nothing.
- `COUNCIL hats`: list the lenses. A project can override one by placing a file of the same name in `.council/hats/<kind>/`.
- `COUNCIL stats`: how often each lens and critic produced a finding the planner accepted.
- `COUNCIL install`: link this skill into every agent CLI installed on the machine.
