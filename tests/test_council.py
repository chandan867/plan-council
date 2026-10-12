import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import council

FAKE = {"harness": "cmd", "cmd": [sys.executable, os.path.join(HERE, "fake_agent.py"), "{prompt_file}"]}


class Parsing(unittest.TestCase):
    def test_json_is_found_inside_prose_and_fences(self):
        text = 'noise {"x": 1}\n```json\n{"findings": [{"claim": "c", "severity": "HIGH"}]}\n```\nbye'
        got = council.parse_findings(text)
        self.assertEqual(got["findings"][0]["severity"], "high")
        self.assertIsNone(council.parse_findings("no json here"))

    def test_bad_findings_are_dropped_and_unknown_severity_defaults(self):
        got = council.parse_findings(json.dumps({"findings": [{"claim": ""}, "x", {"claim": "real", "severity": "urgent"}]}))
        self.assertEqual([f["severity"] for f in got["findings"]], ["high"])

    def test_revision_needs_a_plan_block(self):
        self.assertIsNone(council.parse_revision('{"ledger": []}'))
        self.assertIsNone(council.parse_revision('<<<PLAN\n\nPLAN>>>'))
        self.assertIsNone(council.parse_plan('<<<PLAN\n  \nPLAN>>>'))
        plan, ledger = council.parse_revision('<<<PLAN\n# P\nPLAN>>>\n<<<LEDGER\n{"ledger":[{"id":"F1","decision":"Accept","reason":"r"}]}\nLEDGER>>>')
        self.assertEqual((plan, ledger["F1"]["decision"]), ("# P", "accept"))

    def test_merge_folds_duplicates_and_sorts_by_severity(self):
        a = {"critic": "one", "findings": [{"severity": "low", "claim": "Minor thing"}, {"severity": "medium", "claim": "Plan ignores the auth module"}]}
        b = {"critic": "two", "findings": [{"severity": "blocker", "claim": "Plan ignores the auth module."}]}
        merged = council.merge_findings({"h1": a, "h2": b})
        self.assertEqual([(f["id"], f["severity"]) for f in merged], [("F1", "blocker"), ("F2", "low")])
        self.assertEqual(merged[0]["also_raised_by"], ["h2"])


class Commands(unittest.TestCase):
    def test_every_real_harness_is_run_read_only(self):
        cmds = {h: council.build_cmd({"harness": h, "model": "m"}, "/p.md", "/repo", "/last", "/s.json") for h in council.HARNESSES}
        self.assertEqual(cmds["claude"][:2], ["claude", "-p"])
        self.assertIn("/p.md", cmds["claude"][2])
        self.assertIn("Write", cmds["claude"][cmds["claude"].index("--disallowedTools"):])
        self.assertEqual(cmds["codex"][cmds["codex"].index("-s") + 1], "read-only")
        self.assertIn("--output-schema", cmds["codex"])
        self.assertEqual(cmds["pi"][cmds["pi"].index("--tools") + 1], council.PI_READONLY)
        self.assertEqual(cmds["opencode"][cmds["opencode"].index("--agent") + 1], "plan")

    def test_model_flag_is_left_out_when_model_is_null(self):
        for h in council.HARNESSES:
            cmd = council.build_cmd({"harness": h, "model": None}, "/p.md", "/repo", "/last")
            self.assertFalse({"--model", "-m"} & set(cmd), h)


class EndToEnd(unittest.TestCase):
    def run_council(self, mode="ok", extra=()):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cwd = self.tmp.name
        cfg = os.path.join(cwd, "cfg.json")
        council.write_json(cfg, {"planner": FAKE, "critics": {"one": dict(FAKE, model="m1"), "two": dict(FAKE, model="m2")},
                                 "verifier": "two", "limits": {"minutes": 1}})
        os.environ["FAKE_MODE"] = mode
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        out = io.StringIO()
        with redirect_stdout(out):
            code = council.main(["plan", "Add login", "--cwd", cwd, "--config", cfg] + list(extra))
        runs = os.path.join(cwd, ".council", "runs")
        self.run_dir = os.path.join(runs, os.listdir(runs)[0])
        self.ledger = json.loads(council.read(os.path.join(self.run_dir, "ledger.json")))
        return code

    def has(self, name):
        return os.path.exists(os.path.join(self.run_dir, name))

    def test_clean_run_is_ready(self):
        self.assertEqual(self.run_council(), 0)
        self.assertIn("Plan v2", council.read(os.path.join(self.run_dir, "plan.md")))
        self.assertIn("Plan v1", council.read(os.path.join(self.run_dir, "plan.v1.md")))
        f = self.ledger["findings"]
        self.assertEqual([x["severity"] for x in f], ["high", "low", "low"])
        self.assertEqual(f[0]["also_raised_by"], ["premortem"])
        self.assertEqual((f[0]["decision"], f[0]["verify"]), ("accept", "resolved"))
        self.assertNotIn("verify", f[1])  # only blocker/high are verified
        self.assertFalse(self.has("NEEDS-YOU.md"))
        self.assertTrue(self.has("summary.json"))
        self.assertLess(council.read(os.path.join(self.run_dir, "report.html")).index("The plan at a glance"),
                        council.read(os.path.join(self.run_dir, "report.html")).index("Critique, lens by lens"))
        self.assertEqual(council.read(os.path.join(self.tmp.name, ".council", ".gitignore")), "runs/\n")

    def test_verifier_disagreement_goes_to_the_human(self):
        self.assertEqual(self.run_council("unresolved"), 3)
        self.assertEqual(self.ledger["needs_you"], ["F1"])
        self.assertIn("## F1", council.read(os.path.join(self.run_dir, "NEEDS-YOU.md")))

    def test_unanswered_major_finding_goes_to_the_human(self):
        self.assertEqual(self.run_council("silent"), 3)
        self.assertEqual(self.ledger["findings"][0]["decision"], "unanswered")

    def test_failed_lens_is_reported_as_a_gap(self):
        self.assertEqual(self.run_council("garbage"), 3)
        self.assertEqual(self.ledger["gaps"], ["premortem"])
        self.assertTrue(self.has("agents/critique-premortem.retry1.out"))
        self.assertIn("premortem", council.read(os.path.join(self.run_dir, "NEEDS-YOU.md")))

    def test_full_depth_runs_an_arena_and_all_lenses(self):
        self.assertEqual(self.run_council(extra=["--depth", "full"]), 0)
        self.assertEqual(sorted(os.listdir(os.path.join(self.run_dir, "candidates"))), ["A.md", "B.md", "C.md"])
        self.assertIn("Base B", council.read(os.path.join(self.run_dir, "arena.md")))
        self.assertIn("combined", council.read(os.path.join(self.run_dir, "plan.v1.md")))
        self.assertEqual(len(os.listdir(os.path.join(self.run_dir, "findings"))), 5)
        self.assertFalse(self.has("agents/draft.prompt.md"))

    def test_quick_depth_has_no_arena_and_borrowed_lenses_load(self):
        self.assertEqual(self.run_council(extra=["--kind", "architecture"]), 0)
        self.assertFalse(self.has("arena.md"))
        self.assertEqual(sorted(os.listdir(os.path.join(self.run_dir, "findings"))),
                         ["codebase-reality.json", "failure-modes.json", "scale-and-cost.json"])

    def test_vague_goal_is_framed_then_planned_with_the_users_answers(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd, cfg = tmp.name, os.path.join(tmp.name, "cfg.json")
        council.write_json(cfg, {"planner": FAKE, "critics": {"one": dict(FAKE, model="m1")}, "limits": {"minutes": 1}})
        answers = os.path.join(cwd, "answers.md")
        council.write(answers, "MRR is 42k.")
        intake = os.path.join(cwd, "intake.md")
        council.write(intake, "Only the EU market. Budget is fixed.")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(council.main(["frame", "make this business grow 10X", "--context", intake, "--cwd", cwd, "--config", cfg]), 0)
            self.assertIn("Only the EU market.", council.read(os.path.join(council.find_run(cwd, "latest"), "agents", "frame-A.prompt.md")))
            run_dir = council.find_run(cwd, "latest")
            self.assertIn("What is MRR today?", council.read(os.path.join(run_dir, "QUESTIONS.md")))
            self.assertIn("Assume 10k.", council.read(os.path.join(run_dir, "brief.md")))
            framed = council.read(os.path.join(run_dir, "report.html"))
            self.assertIn("waiting for your answers", framed)
            self.assertEqual(framed.count("This run has only been framed"), 4)  # drafts, critique, decisions, result
            self.assertEqual(council.main(["plan", "--from", "latest", "--answers", answers, "--cwd", cwd, "--config", cfg]), 0)
        self.assertEqual(len(os.listdir(os.path.join(cwd, ".council", "runs"))), 1)  # same run folder
        ledger = json.loads(council.read(os.path.join(run_dir, "ledger.json")))
        self.assertEqual((ledger["kind"], ledger["request"]), ("strategy", "make this business grow 10X"))
        self.assertTrue(os.path.exists(os.path.join(run_dir, "findings", "bottleneck.json")))
        self.assertTrue(os.path.exists(os.path.join(run_dir, "arena.md")))  # framed goals get an arena
        prompt = council.read(os.path.join(run_dir, "agents", "draft-A.prompt.md"))
        self.assertIn("MRR is 42k.", prompt)
        self.assertIn("Only the EU market.", prompt)  # intake answers carry over from frame to plan
        self.assertIn("Kill criteria", prompt)  # strategy template
        self.assertIn("Names the bottleneck", council.read(os.path.join(run_dir, "agents", "judge.prompt.md")))
        page = council.read(os.path.join(run_dir, "report.html"))
        for expected in ("make this business grow 10X", "Framing A", "cmd/m1", "Candidate B", "MRR is 42k.", "Base: B",
                         "bottleneck", "The plan ignores the existing auth module.", "Final plan", "Plan v2", 'class="state ok">done<',
                         "The plan at a glance", "Build login on the existing auth module", '<pre class="diagram">flowchart LR',
                         "mermaid.esm.min.mjs", "Only the EU market.", "Done when: Test passes"):
            self.assertIn(expected, page)
        self.assertNotIn("http-equiv", page)  # finished runs do not auto-refresh

    def test_report_escapes_model_output_and_renders_markdown(self):
        import report
        page = report.markdown("# T\n\n- a **b** `c`\n- <script>x</script>\n\n| h | i |\n|---|---|\n| 1 | 2 |\n\n```\n<raw>\n```")
        self.assertIn("<li>a <b>b</b> <code>c</code></li>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("<td>1</td><td>2</td>", page)
        self.assertIn("<pre>&lt;raw&gt;</pre>", page)

    def test_existing_plan_can_be_reviewed_and_marketing_lenses_load(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# My own plan\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(self.run_council(extra=["--plan", f.name, "--kind", "marketing"]), 0)
        self.assertFalse(self.has("agents/draft.prompt.md"))
        self.assertIn("My own plan", council.read(os.path.join(self.run_dir, "plan.v1.md")))
        self.assertTrue(self.has("findings/claims-check.json"))


class Setup(unittest.TestCase):
    def test_lineup_prefers_other_vendors_on_other_clis(self):
        inv = {"claude": {"models": ["opus", "sonnet"]}, "codex": {"models": []},
               "pi": {"models": ["zz/claude-opus-5", "zz/grok-4", "zz/mystery"]}}
        got = council.suggest(inv)
        self.assertEqual(got["planner"], {"harness": "claude", "model": "opus"})
        self.assertEqual(got["critics"], {"gpt": {"harness": "codex", "model": None}, "grok": {"harness": "pi", "model": "zz/grok-4"}})
        self.assertEqual(got["verifier"], "gpt")

    def test_one_cli_with_several_models_still_gets_distinct_critics(self):
        got = council.suggest({"claude": {"models": ["opus", "sonnet", "haiku"]}})
        self.assertEqual([r["model"] for r in got["critics"].values()], ["sonnet", "haiku"])
        got = council.suggest({"opencode": {"models": ["a/gpt-9", "b/gemini-9", "c/grok-9"]}})
        self.assertEqual(list(got["critics"]), ["gemini", "grok"])
        got = council.suggest({"codex": {"models": []}})
        self.assertEqual(got["critics"], {"gpt": {"harness": "codex", "model": None}})
        self.assertIsNone(council.suggest({}))

    def test_small_and_free_models_rank_below_large_ones(self):
        names = ["x/big-pickle-free", "x/claude-haiku-4-5", "x/gpt-6-astra", "x/deepseek-v4-pro", "x/gemini-3-flash"]
        ranked = sorted(names, key=council.strength, reverse=True)
        self.assertEqual(set(ranked[:2]), {"x/gpt-6-astra", "x/deepseek-v4-pro"})
        self.assertEqual(ranked[-1], "x/big-pickle-free")

    def test_configure_writes_a_config_that_loads(self):
        with tempfile.TemporaryDirectory() as cwd, redirect_stdout(io.StringIO()):
            code = council.main(["configure", "--local", "--cwd", cwd, "--planner", "claude:opus",
                                 "--critic", "gpt=codex", "--critic", "grok=pi:zz/grok-4:high"])
            cfg = council.load_config(None, cwd)
        self.assertEqual(code, 0)
        self.assertEqual(cfg["critics"]["grok"], {"harness": "pi", "model": "zz/grok-4:high"})
        self.assertEqual((cfg["critics"]["gpt"]["model"], cfg["verifier"]), (None, "gpt"))

    def test_install_links_the_skill_into_a_cli_skills_folder(self):
        with tempfile.TemporaryDirectory() as home, redirect_stdout(io.StringIO()):
            old, os.environ["HOME"] = os.environ.get("HOME"), home
            try:
                council.main(["install", "--only", "claude,codex"])
                council.main(["install", "--only", "claude"])  # second time is a no-op
                link = os.path.join(home, ".codex", "skills", "plan-council")
                self.assertTrue(os.path.exists(os.path.join(link, "SKILL.md")))
                self.assertEqual(os.path.realpath(os.path.join(home, ".claude", "skills", "plan-council")), council.ROOT)
            finally:
                os.environ["HOME"] = old

    def test_detached_run_can_be_followed_with_status(self):
        with tempfile.TemporaryDirectory() as cwd, redirect_stdout(io.StringIO()) as out:
            cfg = os.path.join(cwd, "cfg.json")
            council.write_json(cfg, {"planner": FAKE, "critics": {"one": FAKE}, "limits": {"minutes": 1}})
            self.assertEqual(council.main(["plan", "Add login", "--cwd", cwd, "--config", cfg, "--detach"]), 0)
            self.assertEqual(council.main(["status", "--cwd", cwd, "--wait", "60"]), 0)
            self.assertIn("done, ready", out.getvalue())
            self.assertIn("critique-premortem", out.getvalue())  # console log is replayed


if __name__ == "__main__":
    unittest.main()
