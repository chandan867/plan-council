# plan-council

State a goal, as vague as "grow this business 10x" or "design the architecture for cold email". Several models from different vendors read your project and work out what is really being asked and the few questions worth asking you. They then compete on drafts, attack the winner through different lenses without seeing each other, and the planner has to answer every finding. You only read what they could not settle.

It drives the agent CLIs you already have (Claude Code, Codex, Pi, OpenCode), so each reviewer can open your files and check the plan against the real project.

## Requirements

- Python 3.9 or newer. No packages to install.
- At least one of these CLIs on your PATH, already logged in: `claude`, `codex`, `pi`, `opencode`. Two or more from different vendors is the point of the tool; with one it still runs.

## Install as a skill

```sh
git clone <this repo> plan-council
python3 plan-council/council.py install
```

`install` links the folder into the skills folder of every agent CLI it finds (`~/.claude/skills`, `~/.codex/skills`, `~/.config/opencode/skills`, `~/.pi/agent/skills`). Keep the cloned folder where it is; the links point at it. On Windows, copy the folder into the skills folder yourself.

Then, in Claude Code, Codex, OpenCode or Pi, ask for it in plain words:

> Use the plan-council skill to plan adding team invites with email links.

The first time, the agent runs `council detect`, shows you which CLIs and models it found, proposes who plans and who critiques, and asks you to confirm or change it. On every run it first asks you two to four quick questions about what you mean, then starts the council in the background, follows it, and comes back with a visual summary of the plan and only the points the models could not settle. `SKILL.md` is the script the agent follows.

Nothing needs configuring before the first run. With no saved lineup, the tool looks at which CLIs are installed and which models each offers, and builds a lineup on the spot.

### Which setups work

| You have | What the council does |
|---|---|
| Several CLIs (say Claude Code and Codex) | Planner on one, critics on the others. The strongest setup |
| One CLI with models from several vendors (OpenCode, Pi) | Planner and critics are different vendors' models inside that CLI |
| One CLI, one vendor (only Claude Code, or only Codex) | Different models of that vendor where the CLI offers them. Works, catches less |

Models are found per CLI: `pi --list-models`, `opencode models`, the default model in `~/.codex/config.toml`, and the `opus` / `sonnet` / `haiku` aliases for Claude Code. Any other model name can be typed in.

## Use from the terminal

The same tool works without an agent in front of it:

```sh
ln -s "$PWD/plan-council/council" ~/.local/bin/council   # or any folder on your PATH
council doctor                                            # shows which CLIs were found
council init                                              # optional: saves the suggested lineup
```

Without a saved config it builds a lineup from whatever CLIs it finds on each run.

Run it from the project the plan is about.

```sh
council frame "make this business grow 10x" --context notes.md   # vague goal: brief + questions for you
                                                                 # (--context: what you already know you want)
council plan --from latest --answers answers.md                  # then plan it with your answers
council plan "Add team invites with email links"                 # specific request: coding, two lenses
council plan "Add team invites" --depth full                     # all lenses, and competing drafts judged in an arena
council plan --kind architecture "Design the sending pipeline"   # also: strategy, marketing
council plan --kind marketing "Launch post for the invites feature"
council plan --plan docs/my-plan.md "Add team invites"           # review a plan you already wrote
council plan --file request.md --dry-run                         # show who would do what, run nothing
council plan --detach "Add team invites" && council status --wait 100   # background run, then follow it
```

A quick run starts five agent sessions and takes around ten minutes with large models. Framing adds up to four sessions, and a full run with an arena is about twelve.

### What you get

Everything lands in `.council/runs/<timestamp>-<slug>/` inside your project:

| File | What it is |
|---|---|
| `report.html` | The whole run on one page: the plan at a glance with diagrams, then every step model by model. Open it with `council view` |
| `summary.json` | The visual summary: headline, key figures, diagrams, steps, decisions, risks |
| `plan.md` | The final plan |
| `NEEDS-YOU.md` | Only present when something is unsettled. Read this first |
| `ledger.md` | Every finding, who raised it, what the planner decided and why, and the verifier's check |
| `ledger.json` | The same, for scripts |
| `brief.md`, `QUESTIONS.md` | From `council frame`: how the goal was understood, and what to ask you |
| `arena.md`, `candidates/` | The competing drafts, the judge's scores and what was combined |
| `plan.v1.md` | The plan before the critics saw it |
| `findings/`, `agents/` | Raw output per lens, and every prompt and reply |

Exit code: `0` ready, `3` something needs you, `1` the run failed.

### Watching a run

```sh
council view            # opens report.html for the latest run in this project
```

Every run, detached or foreground, prints a `watch` line with its live `report.html` at the start. Open it in a browser to follow the run model by model while it works.

The report opens with the plan at a glance: a headline, the key figures, diagrams of the design or flow, the steps in order, the key decisions and the main risks. Diagrams are drawn in the browser with Mermaid, loaded from a CDN; offline you see the diagram source instead.

Below that it shows each step in order with the CLI and model that did it and how long it took: how each model framed the goal, the brief and your answers, every competing draft, the judge's scores and chosen base, each critic's findings lens by lens, what the planner decided for every finding and why, the verifier's check, and the final plan. Each step links to the exact prompt sent and the raw reply. It is rebuilt after every model call and refreshes by itself while a run is going, so you can leave it open from the start.

## How it works

```
0 frame     up to three models read the project and frame the goal; the planner merges them into a brief,
            a rubric, and at most five questions for you            (council frame; skip for specific requests)
1 draft     the planner writes the plan. In an arena, up to three models each write one, a judge from
            another vendor scores them against the rubric, and the planner combines the best parts
2 critique  one lens per critic, in parallel, blind to each other
3 merge     matching claims folded without losing evidence or suggested fixes, sorted by severity, numbered F1, F2 ...
4 revise    planner answers each finding: accept, reject or defer, and rewrites the plan
5 verify    a different model checks how every blocker and high finding was handled
6 you       NEEDS-YOU.md lists what the verifier disputes, what went unanswered, and lenses that failed
7 present   the planner turns the final plan into a visual summary: key figures, diagrams, ordered steps
```

There is one revise round and one verify round. The models do not argue back and forth: that tends to make them agree with each other, which defeats the purpose. The arena is on by default after `frame` and at full depth; `--arena` and `--no-arena` override it.

Every finding needs a planner decision, including medium and low findings. Missing decisions go to `NEEDS-YOU.md`; independent verification covers blocker and high findings. Malformed critic replies are retried, then reported as a missing lens if they remain unusable. Only matching claims are merged, so similarly worded problems remain separate.

### Lenses

| Kind | For | Quick | Added at full depth |
|---|---|---|---|
| coding | a feature or change in this project | codebase-reality, premortem | simpler-path, slices-and-tests, data-and-security |
| architecture | designing a system | codebase-reality, failure-modes, scale-and-cost | build-vs-buy, data-and-security |
| strategy | a business goal such as growth | bottleneck, numbers, premortem | focus, customer-skeptic, measurement |
| marketing | a campaign, launch or content piece | customer-skeptic, claims-check | channel-evidence, brand-voice, measurement |

`council hats` lists them. Each is a short markdown file in `hats/<kind>/`.

## Configure

Config is looked up in this order: `--config FILE`, `.council/config.json` in the project, `~/.config/plan-council/config.json` (or the file named in `PLAN_COUNCIL_CONFIG`), then auto-detection.

```json
{
  "planner": {"harness": "claude", "model": "claude-opus-5-5"},
  "critics": {
    "gpt":  {"harness": "codex", "model": null},
    "grok": {"harness": "pi", "model": "your-provider/your-model"}
  },
  "verifier": "gpt",
  "assign": {"codebase-reality": "gpt", "premortem": "grok"},
  "limits": {"minutes": 20, "parallel": 4, "retries": 1}
}
```

Write it by hand, or with `council configure --planner claude:opus --critic gpt=codex --critic grok=pi:provider/model` (add `--local` for a project config).

- `model: null` means the CLI's own default.
- `assign` pins a lens to a critic. Lenses not listed are spread across the critics in turn.
- `args` on any role adds extra CLI flags, for example to allow an MCP tool.
- `profiles` overrides which lenses run per kind and depth.
- Any other CLI works through the `cmd` harness: `{"harness": "cmd", "cmd": ["my-agent", "--file", "{prompt_file}"]}`. It must print its answer to stdout.

Commit `.council/config.json` if the whole team should share one setup. `.council/runs/` is ignored by default.

### Your own lenses and plan types

- Change a lens for one project: put a file with the same name in `.council/hats/<kind>/` in that project.
- Add a lens: add `hats/<kind>/<name>.md` and list it under `profiles` in the config, or pass `--hats a,b,c`.
- Add a kind (say `research`): add `prompts/template-research.md`, a `hats/research/` folder, and a `profiles.research` entry.

### Is it earning its cost?

`council stats` shows, per lens and per critic, how many findings were raised and how many the planner accepted, across the runs in the current project. Drop lenses that never land.

## Safety

- Agents are started read-only: Codex with `-s read-only`, Claude Code with only read tools allowed and write tools denied, Pi with only `read,grep,find,ls`, OpenCode with its `plan` agent. In your project, only this script writes, and only under `.council/`. The CLIs may still keep their own logs or state in your home folder.
- The OpenCode guarantee is the weakest: its `plan` agent is read-only by default, but a customised OpenCode setup can change that. Prefer Codex or Claude Code as critics on a repo you care about.
- If the verifier ends up being the same CLI and model as the planner, the run says so. Its check is then a second look, not an independent one.
- In a git repo the working tree is compared before and after a run, and you get a warning if anything outside `.council/` changed.
- Your request, the plan and whatever files the agents open are sent to the model providers behind your CLIs, the same as using those CLIs directly.
- No keys are read or stored here. Each CLI uses its own login.

## Tests

```sh
python3 -m unittest discover -s tests
```

The tests run the whole flow against a fake agent, so they need no CLI and no network.
