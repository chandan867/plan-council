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

    def test_invalid_claims_reject_the_entire_reply(self):
        for bad in ("x", None, {}, {"claim": ""}, {"claim": " \n "}, {"claim": 42},
                    {"claim": True}, {"claim": ["issue"]}, {"claim": {"issue": "x"}}):
            for findings in ([bad], [{"claim": "valid issue"}, bad]):
                with self.subTest(findings=findings):
                    self.assertIsNone(council.parse_findings(json.dumps({"findings": findings})))

    def test_empty_findings_are_valid_and_unknown_severity_defaults(self):
        self.assertEqual(council.parse_findings('{"findings": []}')["findings"], [])
        got = council.parse_findings(json.dumps({"findings": [{"claim": "real", "severity": "urgent"}]}))
        self.assertEqual([f["severity"] for f in got["findings"]], ["high"])

    def test_findings_limit_rejects_excess_instead_of_truncating(self):
        findings = [{"claim": "Issue %d" % i} for i in range(council.MAX_FINDINGS_PER_HAT)]
        self.assertEqual(len(council.parse_findings(json.dumps({"findings": findings}))["findings"]), len(findings))
        self.assertIsNone(council.parse_findings(json.dumps({"findings": findings + [{"claim": "Extra issue"}]})))

    def test_non_list_findings_are_invalid(self):
        for findings in ({}, "issue", None, 1):
            with self.subTest(findings=findings):
                self.assertIsNone(council.parse_findings(json.dumps({"findings": findings})))

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

    def test_merge_keeps_similar_token_unicode_and_operator_claims_separate(self):
        pairs = [
            ("The plan ignores access token expiration.", "The plan ignores refresh token expiration."),
            ("Retries use count < limit.", "Retries use count > limit."),
            ("Validate tenant α before writing.", "Validate tenant β before writing."),
            ("权限检查缺失", "租户检查缺失"),
            ("/App/Token", "/app/token"),
            ('quoted "a b" value', 'quoted "a  b" value'),
        ]
        for claims in pairs:
            with self.subTest(claims=claims):
                merged = council.merge_findings({"hat": {"critic": "one", "findings": [
                    {"severity": "high", "claim": claim} for claim in claims]}})
                self.assertEqual([f["claim"] for f in merged], list(claims))

    def test_duplicate_retains_evidence_suggestions_severity_and_provenance(self):
        first = {"severity": "low", "claim": "Missing tenant check.", "evidence": "api.py:10", "suggestion": "Check the API."}
        second = {"severity": "high", "claim": "Missing tenant check", "evidence": "worker.py:20", "suggestion": "Check the worker."}
        merged = council.merge_findings({"h1": {"critic": "one", "findings": [first]},
                                         "h2": {"critic": "two", "findings": [second, second]}})
        self.assertEqual(len(merged), 1)
        f = merged[0]
        self.assertEqual(f["severity"], "high")
        self.assertEqual(f["also_raised_by"], ["h2"])
        self.assertEqual(f["evidence"], "api.py:10\n\nworker.py:20")
        self.assertEqual(f["suggestion"], "Check the API.\n\nCheck the worker.")
        self.assertEqual(f["sources"], [dict(first, hat="h1", critic="one"), dict(second, hat="h2", critic="two"),
                                        dict(second, hat="h2", critic="two")])

    def test_unanswered_at_every_severity_needs_the_user(self):
        for severity in council.SEVERITIES:
            for verifier_ran in (False, True):
                with self.subTest(severity=severity, verifier_ran=verifier_ran):
                    f = {"severity": severity, "decision": "unanswered", "verify": "resolved"}
                    self.assertEqual(council.needs_you([f], verifier_ran), [(f, "The planner did not answer this finding.")])

    def test_only_answered_major_findings_need_independent_verification(self):
        for severity in council.SEVERITIES:
            with self.subTest(severity=severity):
                f = {"severity": severity, "decision": "accept"}
                self.assertEqual(bool(council.needs_you([f], False)), severity in ("blocker", "high"))
                self.assertEqual(council.needs_you([f], True), [])


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

    def test_malformed_or_excess_findings_retry_then_report_a_gap(self):
        for mode in ("malformed", "too-many"):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_council(mode), 3)
                self.assertEqual(self.ledger["gaps"], ["premortem"])
                self.assertTrue(self.has("agents/critique-premortem.retry1.out"))
                self.assertFalse(self.has("findings/premortem.json"))
                self.assertIn("premortem", council.read(os.path.join(self.run_dir, "NEEDS-YOU.md")))

    def test_unanswered_medium_finding_goes_to_the_human(self):
        self.assertEqual(self.run_council("silent-medium"), 3)
        pending = [f for f in self.ledger["findings"] if f["id"] in self.ledger["needs_you"]]
        self.assertEqual([(f["severity"], f["decision"]) for f in pending], [("medium", "unanswered")])
        self.assertNotIn("verify", pending[0])
        self.assertIn("The planner did not answer", council.read(os.path.join(self.run_dir, "NEEDS-YOU.md")))

    def test_similar_token_issues_both_reach_the_planner(self):
        self.assertEqual(self.run_council("tokens"), 0)
        self.assertEqual([f["claim"] for f in self.ledger["findings"]], [
            "The plan ignores access token expiration.", "The plan ignores refresh token expiration."])
        prompt = council.read(os.path.join(self.run_dir, "agents/revise.prompt.md"))
        self.assertIn("access token expiration", prompt)
        self.assertIn("refresh token expiration", prompt)

    def test_duplicate_evidence_reaches_the_planner_and_final_ledger(self):
        self.assertEqual(self.run_council("duplicate-evidence"), 0)
        f = self.ledger["findings"][0]
        self.assertEqual(f["evidence"], "codebase-reality.py:10\n\npremortem.py:10")
        self.assertEqual(f["suggestion"], "Fix codebase-reality.\n\nFix premortem.")
        self.assertEqual([(s["hat"], s["critic"]) for s in f["sources"]], [("codebase-reality", "one"), ("premortem", "two")])
        for filename in ("agents/revise.prompt.md", "agents/verify.prompt.md", "ledger.md"):
            content = council.read(os.path.join(self.run_dir, filename))
            self.assertIn("codebase-reality.py:10", content)
            self.assertIn("premortem.py:10", content)

    def test_successful_plan_rerun_removes_stale_needs_you_from_frame_directory(self):
        self.assertEqual(self.run_council(), 0)
        cwd, cfg = self.tmp.name, os.path.join(self.tmp.name, "cfg.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(council.main(["frame", "Add login", "--cwd", cwd, "--config", cfg]), 0)
            run_dir = next(os.path.join(cwd, ".council", "runs", name) for name in os.listdir(os.path.join(cwd, ".council", "runs"))
                           if os.path.exists(os.path.join(cwd, ".council", "runs", name, "brief.md")))
            os.environ["FAKE_MODE"] = "unresolved"
            args = ["plan", "--from", run_dir, "--cwd", cwd, "--config", cfg, "--no-arena", "--hats", "coding/codebase-reality"]
            self.assertEqual(council.main(args), 3)
            self.assertTrue(os.path.exists(os.path.join(run_dir, "NEEDS-YOU.md")))
            os.environ["FAKE_MODE"] = "ok"
            self.assertEqual(council.main(args), 0)
        self.assertFalse(os.path.exists(os.path.join(run_dir, "NEEDS-YOU.md")))
        ledger = json.loads(council.read(os.path.join(run_dir, "ledger.json")))
        self.assertEqual(ledger["needs_you"], [])

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
