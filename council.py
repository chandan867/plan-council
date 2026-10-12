#!/usr/bin/env python3
"""plan-council: one model drafts a plan, other model families critique it blind
through different lenses, the planner answers every finding, a third party checks
the answers, and whatever is still disputed is handed to a human.

Standard library only. Every agent runs read-only; only this script writes files,
and only under <cwd>/.council/.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

ROOT = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, ROOT)
import report  # noqa: E402
HARNESSES = ("claude", "codex", "pi", "opencode")  # also the planner preference order
SEVERITIES = ("blocker", "high", "medium", "low")
DECISIONS = ("accept", "reject", "defer")
USER_CONFIG = os.environ.get("PLAN_COUNCIL_CONFIG") or os.path.expanduser("~/.config/plan-council/config.json")
MAX_FINDINGS_PER_HAT = 7

DEFAULT_LIMITS = {"minutes": 20, "parallel": 4, "retries": 1}
MAX_SUGGESTED_CRITICS = 3
FAMILIES = (
    ("claude", r"claude|opus|sonnet|haiku"), ("gpt", r"gpt|openai|codex"), ("gemini", r"gemini"), ("grok", r"grok"),
    ("glm", r"glm"), ("qwen", r"qwen"), ("deepseek", r"deepseek"), ("kimi", r"kimi|moonshot"), ("llama", r"llama"),
    ("mistral", r"mistral|codestral|devstral"),
)
STRONG_NAMES = r"opus|fable|sonnet|astra|\bsol\b|pro\b|max\b|ultra|large"
WEAK_NAMES = r"free|mini|nano|lite|flash|haiku|luna|small|tiny|fast|instant|preview|auto-review"
HARNESS_FAMILY = {"claude": "claude", "codex": "gpt"}  # vendor when a CLI runs its default model
SKILL_DIRS = {"claude": "~/.claude/skills", "codex": "~/.codex/skills", "opencode": "~/.config/opencode/skills", "pi": "~/.pi/agent/skills"}
_active_run = []  # the run being executed, so main() can record its exit code
DEFAULT_PROFILES = {
    "coding": {
        "quick": ["codebase-reality", "premortem"],
        "full": ["codebase-reality", "premortem", "simpler-path", "slices-and-tests", "data-and-security"],
    },
    "marketing": {
        "quick": ["customer-skeptic", "claims-check"],
        "full": ["customer-skeptic", "claims-check", "channel-evidence", "brand-voice", "measurement"],
    },
    # A lens written for another kind is borrowed as "kind/lens".
    "architecture": {
        "quick": ["coding/codebase-reality", "failure-modes", "scale-and-cost"],
        "full": ["coding/codebase-reality", "failure-modes", "scale-and-cost", "build-vs-buy", "coding/data-and-security"],
    },
    "strategy": {
        "quick": ["bottleneck", "numbers", "premortem"],
        "full": ["bottleneck", "numbers", "premortem", "focus", "marketing/customer-skeptic", "marketing/measurement"],
    },
}
KIND_HELP = ("coding = build or change software in this project; architecture = design a system or its technical "
             "foundations; strategy = a business goal such as growth, revenue or positioning; marketing = a campaign, "
             "launch or piece of content")
LABELS = "ABCDEFGH"
MAX_PARALLEL_THINKERS = 3  # how many models frame a goal, or draft competing plans

# Tools a Claude Code agent may use. Everything else is denied in -p mode.
CLAUDE_READONLY = ["Read", "Glob", "Grep", "Bash(git log:*)", "Bash(git diff:*)", "Bash(git show:*)", "Bash(ls:*)"]
CLAUDE_DENY = ["Write", "Edit", "NotebookEdit"]
PI_READONLY = "read,grep,find,ls"

_log_lock = threading.Lock()


def die(msg):
    print("council: " + msg, file=sys.stderr)
    sys.exit(1)


def say(msg):
    print(msg, flush=True)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def render(prompt_name, **values):
    """Fill {{name}} placeholders in prompts/<prompt_name>.md in a single pass."""
    text = read(os.path.join(ROOT, "prompts", prompt_name + ".md"))
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), text)


# ---------- config ----------
def detect():
    return [h for h in HARNESSES if shutil.which(h)]


def family(harness, model):
    """Vendor family of a model, guessed from its name. None when the name tells us nothing."""
    name = (model or "").lower()
    for fam, pattern in FAMILIES:
        if re.search(pattern, name):
            return fam
    return None if model else HARNESS_FAMILY.get(harness)


def strength(model):
    """Rough rank of a model from its name, so a suggested lineup does not lead with a small or free one."""
    name = model.lower()
    versions = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", name)]
    return (2 if re.search(STRONG_NAMES, name) else 0) - (3 if re.search(WEAK_NAMES, name) else 0) + min(versions[:1] or [0], default=0) / 100


def _lines(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return []


def list_models(harness):
    """Models a CLI can run, best first where the CLI tells us. Empty means only its default is known."""
    if harness == "claude":
        return ["opus", "sonnet", "haiku"]  # aliases the claude CLI resolves itself
    if harness == "codex":
        try:  # codex has no list command; read only the default model line from its config
            found = re.search(r'^model\s*=\s*"([^"]+)"', read(os.path.expanduser("~/.codex/config.toml")), re.M)
        except OSError:
            found = None
        return [found.group(1)] if found else []
    if harness == "pi":
        rows = [l.split() for l in _lines(["pi", "--list-models"])]
        return sorted(("%s/%s" % (r[0], r[1]) for r in rows if len(r) > 1 and r[0] != "provider"), key=strength, reverse=True)
    if harness == "opencode":
        models = sorted((l.strip() for l in _lines(["opencode", "models"]) if re.match(r"^\S+/\S+$", l.strip())), key=strength, reverse=True)
        try:  # the model the user already set as their default goes first; read only that one key
            chosen = re.search(r'^\s*"model"\s*:\s*"([^"]+)"', read(os.path.expanduser("~/.config/opencode/opencode.json")), re.M)
        except OSError:
            chosen = None
        if chosen and chosen.group(1) in models:
            models.insert(0, models.pop(models.index(chosen.group(1))))
        return models
    return []


def inventory():
    return {h: {"models": list_models(h)} for h in detect()}


def suggest(inv):
    """A lineup from what is installed: critics from vendors other than the planner's, on other CLIs where possible."""
    options = []
    for h in HARNESSES:
        if h in inv:
            options += [(h, m) for m in inv[h]["models"]] or [(h, None)]
    if not options:
        return None
    planner = options[0]
    picked, families, harnesses = [], {family(*planner)}, {planner[0]}

    def take(rule):
        for option in options:
            if len(picked) < MAX_SUGGESTED_CRITICS and option != planner and option not in picked and rule(option):
                picked.append(option)
                families.add(family(*option))
                harnesses.add(option[0])

    take(lambda o: family(*o) and family(*o) not in families and o[0] not in harnesses)  # new vendor on a new CLI
    take(lambda o: family(*o) and family(*o) not in families)                            # new vendor, any CLI
    if len(picked) < 2:
        take(lambda o: len(picked) < 2)                                                   # another model, same vendor
    critics = {}
    for h, m in picked or [planner]:
        base = family(h, m) or h
        name = base
        while name in critics:
            name = "%s%d" % (base, sum(k.startswith(base) for k in critics) + 1)
        critics[name] = {"harness": h, "model": m}
    verifier = next((n for n, r in critics.items() if family(r["harness"], r["model"]) != family(*planner)), next(iter(critics)))
    return {"planner": {"harness": planner[0], "model": planner[1]}, "critics": critics, "verifier": verifier,
            "assign": {}, "limits": dict(DEFAULT_LIMITS)}


def parse_role(spec):
    """"claude:opus" -> {"harness": "claude", "model": "opus"}; "codex" -> model None (the CLI's default)."""
    harness, _, model = spec.partition(":")
    if harness not in HARNESSES:
        die("unknown CLI \"%s\" in \"%s\" (use one of: %s)" % (harness, spec, ", ".join(HARNESSES)))
    return {"harness": harness, "model": model or None}


def config_path(explicit, cwd):
    for p in (explicit, os.path.join(cwd, ".council", "config.json"), USER_CONFIG):
        if p and os.path.exists(p):
            return p
    return None


def load_config(explicit, cwd):
    if explicit and not os.path.exists(explicit):
        die("config not found: " + explicit)
    path = config_path(explicit, cwd)
    if path:
        try:
            cfg = json.loads(read(path))
        except ValueError as e:
            die("%s is not valid JSON: %s" % (path, e))
    else:
        cfg = suggest(inventory())
        if not cfg:
            die("no agent CLI found on PATH (looked for: %s). Install one, or write a config with a \"cmd\" harness."
                % ", ".join(HARNESSES))
    cfg["_source"] = path or "auto-detected"
    cfg["limits"] = dict(DEFAULT_LIMITS, **cfg.get("limits", {}))
    cfg["profiles"] = dict(DEFAULT_PROFILES, **cfg.get("profiles", {}))
    cfg.setdefault("assign", {})
    if not cfg.get("planner") or not cfg.get("critics"):
        die("config needs a \"planner\" and at least one entry in \"critics\" (%s)" % cfg["_source"])
    # The verifier judges the planner's answers, so prefer a critic that is not the planner's CLI and model.
    cfg.setdefault("verifier", next((n for n, r in cfg["critics"].items() if role_label(r) != role_label(cfg["planner"])),
                                    next(iter(cfg["critics"]))))
    if cfg["verifier"] not in cfg["critics"]:
        die("verifier \"%s\" is not one of the critics: %s" % (cfg["verifier"], ", ".join(cfg["critics"])))
    for name, role in [("planner", cfg["planner"])] + list(cfg["critics"].items()):
        h = role.get("harness")
        if h == "cmd":
            if not role.get("cmd"):
                die("role \"%s\" uses harness \"cmd\" but has no \"cmd\" list" % name)
        elif h not in HARNESSES:
            die("role \"%s\" has unknown harness \"%s\" (use one of: %s, cmd)" % (name, h, ", ".join(HARNESSES)))
    return cfg


def role_label(role):
    return "%s/%s" % (role["harness"], role.get("model") or "default")


# ---------- harness adapters ----------
def build_cmd(role, prompt_file, cwd, last_file, schema=None):
    """Command line that runs one read-only agent on a prompt file."""
    h = role["harness"]
    model = role.get("model")
    extra = list(role.get("args", []))
    pointer = "Read the file %s and do exactly what it says." % prompt_file
    if h == "cmd":
        return [x.replace("{prompt_file}", prompt_file).replace("{cwd}", cwd) for x in role["cmd"]]
    if h == "claude":
        # The prompt must come right after -p: --allowedTools is variadic and would swallow it.
        cmd = ["claude", "-p", pointer, "--output-format", "text", "--no-session-persistence"]
        if model:
            cmd += ["--model", model]
        return cmd + extra + ["--allowedTools"] + CLAUDE_READONLY + ["--disallowedTools"] + CLAUDE_DENY
    if h == "codex":
        cmd = ["codex", "exec", "--ephemeral", "-s", "read-only", "-C", cwd, "--skip-git-repo-check", "-o", last_file]
        if model:
            cmd += ["-m", model]
        if schema:
            cmd += ["--output-schema", schema]
        return cmd + extra + [pointer]
    if h == "pi":
        cmd = ["pi", "-p", "--no-session", "--tools", PI_READONLY]
        if model:
            cmd += ["--model", model]
        return cmd + extra + [pointer]
    if h == "opencode":
        cmd = ["opencode", "run", "--agent", "plan"]
        if model:
            cmd += ["-m", model]
        return cmd + extra + [pointer]
    raise ValueError("unknown harness " + str(h))


class Run:
    def __init__(self, cwd, cfg, slug, run_dir=None):
        self.cwd = cwd
        self.cfg = cfg
        self.dir = os.path.abspath(run_dir) if run_dir else os.path.join(cwd, ".council", "runs", time.strftime("%Y%m%d-%H%M%S-") + slug + "-" + os.urandom(2).hex())

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def log(self, **event):
        event["t"] = time.strftime("%H:%M:%S")
        with _log_lock:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.path("events.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
            report.write(self.dir)  # keep report.html current so it can be watched while the council works


def call(run, role, name, prompt, schema=None):
    """Run one agent. Returns (exit code, final text)."""
    prompt_file = run.path("agents", name + ".prompt.md")
    out, err, last = (run.path("agents", name + ext) for ext in (".out", ".err", ".last"))
    write(prompt_file, prompt)
    cmd = build_cmd(role, prompt_file, run.cwd, last, schema)
    run.log(event="start", agent=name, role=role_label(role))
    started = time.time()
    try:
        with open(out, "w") as o, open(err, "w") as e:
            code = subprocess.run(cmd, cwd=run.cwd, stdin=subprocess.DEVNULL, stdout=o, stderr=e,
                                  timeout=run.cfg["limits"]["minutes"] * 60).returncode
    except subprocess.TimeoutExpired:
        code = 124
    except OSError:
        code = 127
    seconds = int(time.time() - started)
    run.log(event="end", agent=name, code=code, seconds=seconds)
    text = read(last) if os.path.exists(last) and os.path.getsize(last) else read(out)
    return code, text, seconds


def ask(run, role, name, prompt, parse, schema=None):
    """Run an agent until its reply parses, up to limits.retries extra attempts."""
    for attempt in range(run.cfg["limits"]["retries"] + 1):
        agent = name if attempt == 0 else "%s.retry%d" % (name, attempt)
        code, text, seconds = call(run, role, agent, prompt, schema)
        value = parse(text)
        run.log(event="result", agent=agent, ok=value is not None)
        if value is not None:
            say("  %-28s %-34s %4ds  ok" % (name, role_label(role), seconds))
            return value
        reason = {124: "timed out", 127: "command not found"}.get(code, "reply not usable (exit %d)" % code)
        say("  %-28s %-34s %4ds  %s" % (name, role_label(role), seconds, reason))
        if code == 127:
            break
        prompt += "\n\nYour previous reply could not be parsed. Follow the Output section exactly.\n"
    return None


# ---------- parsing agent replies ----------
def extract_json(text, key):
    """Last JSON object in the text that has `key`. Tolerates prose and code fences around it."""
    decoder = json.JSONDecoder()
    best, end = None, 0
    for m in re.finditer(r"\{", text):
        if m.start() < end:
            continue
        try:
            obj, length = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        end = m.start() + length
        if isinstance(obj, dict) and key in obj:
            best = obj
    return best


def extract_block(text, tag):
    """Content between <<<TAG and TAG>>> marker lines (last occurrence)."""
    found = re.findall(r"<<<%s[ \t]*\n(.*?)\n[ \t]*%s>>>" % (tag, tag), text, re.S)
    return found[-1].strip() if found else None


def parse_text(text):
    return text.strip() or None


def parse_plan(text):
    return extract_block(text, "PLAN") or None


def parse_findings(text):
    obj = extract_json(text, "findings")
    if obj is None or not isinstance(obj["findings"], list):
        return None
    # Reject the whole reply rather than silently losing findings. ask() retries it,
    # and reports a missing lens if the critic cannot return a valid bounded list.
    if len(obj["findings"]) > MAX_FINDINGS_PER_HAT:
        return None
    findings = []
    for f in obj["findings"]:
        if not isinstance(f, dict) or not isinstance(f.get("claim"), str) or not f["claim"].strip():
            return None
        severity = str(f.get("severity") or "").lower()
        findings.append({
            # An unreadable severity is treated as high so the finding still gets verified.
            "severity": severity if severity in SEVERITIES else "high",
            "claim": str(f["claim"]).strip(),
            "evidence": str(f.get("evidence") or "").strip(),
            "suggestion": str(f.get("suggestion") or "").strip(),
            "confidence": str(f.get("confidence") or "medium").lower(),
        })
    return {"summary": str(obj.get("summary") or ""), "findings": findings}


def parse_revision(text):
    plan = extract_block(text, "PLAN")
    if not plan:
        return None
    ledger = {}
    obj = extract_json(extract_block(text, "LEDGER") or text, "ledger")
    for row in (obj or {}).get("ledger") or []:
        if isinstance(row, dict) and str(row.get("decision") or "").lower() in DECISIONS:
            ledger[str(row.get("id"))] = {"decision": row["decision"].lower(), "reason": str(row.get("reason") or "")}
    return plan, ledger


def parse_frame(text):
    obj = extract_json(text, "questions")
    return obj if obj is not None and str(obj.get("goal") or "").strip() else None


def parse_brief(text):
    brief = extract_block(text, "BRIEF")
    if not brief:
        return None
    meta = extract_json(extract_block(text, "META") or text, "rubric") or {}
    questions = [q for q in meta.get("questions") or [] if isinstance(q, dict) and str(q.get("question") or "").strip()]
    return brief, {"kind": str(meta.get("kind") or "").lower(), "rubric": [str(c) for c in meta.get("rubric") or []][:6],
                   "questions": [{k: str(q.get(k) or "") for k in ("question", "why", "default")} for q in questions][:5]}


def parse_judge(text):
    obj = extract_json(text, "base")
    return obj if obj is not None and str(obj.get("base") or "").strip() else None


def parse_synthesis(text):
    plan = extract_block(text, "PLAN")
    return (plan, extract_block(text, "SYNTHESIS") or "") if plan else None


def parse_checks(text):
    obj = extract_json(text, "checks")
    if obj is None or not isinstance(obj["checks"], list):
        return None
    checks = {}
    for row in obj["checks"]:
        if isinstance(row, dict) and row.get("status") in ("resolved", "unresolved"):
            checks[str(row.get("id"))] = {"status": row["status"], "note": str(row.get("note") or "")}
    return checks


# ---------- hats and findings ----------
def hat_id(spec):
    return spec.split("/")[-1]


def hat_path(cwd, kind, hat):
    """File for a lens. `hat` may be "kind/lens" to borrow a lens written for another kind."""
    if "/" in hat:
        kind, hat = hat.split("/", 1)
    for base in (os.path.join(cwd, ".council", "hats"), os.path.join(ROOT, "hats")):
        p = os.path.join(base, kind, hat + ".md")
        if os.path.exists(p):
            return p
    return None


def assign_hats(cfg, hats):
    """hat -> critic name. Explicit `assign` wins, the rest go round-robin over the critics."""
    names = list(cfg["critics"])
    out = {}
    for i, hat in enumerate(hats):
        critic = cfg["assign"].get(hat) or names[i % len(names)]
        if critic not in cfg["critics"]:
            die("hat \"%s\" is assigned to unknown critic \"%s\"" % (hat, critic))
        out[hat] = critic
    return out


def _norm(claim):
    # Keep Unicode and operators: a changed token can describe a different issue.
    normalized = claim.strip()
    return normalized[:-1] if normalized.endswith(".") and not normalized.endswith("..") else normalized


def merge_findings(per_hat):
    """Fold matching claims together without losing evidence or source provenance."""
    merged = []
    for hat, result in per_hat.items():
        for f in result["findings"]:
            source = dict(f, hat=hat, critic=result["critic"])
            twin = next((m for m in merged if _norm(m["claim"]) == _norm(f["claim"])), None)
            if twin:
                if hat != twin["hat"] and hat not in twin["also_raised_by"]:
                    twin["also_raised_by"].append(hat)
                if SEVERITIES.index(f["severity"]) < SEVERITIES.index(twin["severity"]):
                    twin["severity"] = f["severity"]
                twin["sources"].append(source)
                for field in ("evidence", "suggestion"):
                    values = dict.fromkeys(s.get(field, "") for s in twin["sources"] if s.get(field))
                    twin[field] = "\n\n".join(values)
                continue
            merged.append(dict(f, hat=hat, critic=result["critic"], also_raised_by=[], sources=[source]))
    merged.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    return [dict(f, id="F%d" % (i + 1)) for i, f in enumerate(merged)]


def is_major(finding):
    return finding["severity"] in ("blocker", "high")


def needs_you(findings, verifier_ran):
    """Findings a human has to decide: (finding, why)."""
    items = []
    for f in findings:
        if f["decision"] == "unanswered":
            items.append((f, "The planner did not answer this finding."))
        elif f.get("verify") == "unresolved":
            items.append((f, f.get("verify_note") or "The verifier disagrees with how this was handled."))
        elif not is_major(f):
            continue
        elif not verifier_ran:
            items.append((f, "Nobody independently checked the planner's answer (the verifier did not run)."))
    return items


# ---------- reports ----------
def cell(text):
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|")


def ledger_markdown(findings, gaps):
    lines = ["# Council ledger", "", "| ID | Severity | Lens (critic) | Finding | Decision | Reason | Check |", "|---|---|---|---|---|---|---|"]
    for f in findings:
        lens = "%s (%s)" % (f["hat"], f["critic"])
        if f["also_raised_by"]:
            lens += ", also " + ", ".join(f["also_raised_by"])
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            f["id"], f["severity"], cell(lens), cell(f["claim"]), f["decision"], cell(f["reason"]), f.get("verify", "-")))
    if not findings:
        lines.append("| - | - | - | No findings | - | - | - |")
    if gaps:
        lines += ["", "Lenses that did not report (agent failed or timed out): " + ", ".join(gaps)]
    lines += ["", "## Evidence and suggested changes", ""]
    for f in findings:
        lines += ["**%s** %s" % (f["id"], f["claim"]), "", "- Evidence: " + (f["evidence"] or "none given"),
                  "- Suggested change: " + (f["suggestion"] or "none given"), ""]
    return "\n".join(lines) + "\n"


def needs_you_markdown(items, gaps, notes):
    lines = ["# Needs you", "", "The council could not settle these. Decide each one, then edit plan.md.", ""]
    for note in notes:
        lines += ["- " + note]
    if gaps:
        lines += ["- These lenses never reported, so the plan was not checked from that angle: " + ", ".join(gaps)]
    if notes or gaps:
        lines.append("")
    for f, why in items:
        lines += ["## %s (%s, %s lens)" % (f["id"], f["severity"], f["hat"]), "",
                  "- Finding: " + f["claim"], "- Evidence: " + (f["evidence"] or "none given"),
                  "- Suggested change: " + (f["suggestion"] or "none given"),
                  "- Planner: %s. %s" % (f["decision"], f["reason"]), "- Why it is here: " + why, ""]
    return "\n".join(lines) + "\n"


# ---------- repo guard ----------
def repo_state(cwd):
    """Fingerprint of the working tree outside .council/, or None when cwd is not in a git repo."""
    try:
        status = subprocess.run(["git", "-C", cwd, "status", "--porcelain"], capture_output=True, text=True, timeout=60)
        diff = subprocess.run(["git", "-C", cwd, "diff", "--", ".", ":(exclude).council"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode != 0:
        return None
    lines = sorted(l for l in status.stdout.splitlines() if ".council/" not in l)
    return lines, hashlib.sha1(diff.stdout).hexdigest()


# ---------- commands ----------
def read_request(args):
    request = read(args.file) if args.file else " ".join(args.request)
    if not request.strip():
        die("give a request in quotes, or --file request.md")
    return request.strip()


INTAKE_HEADING = "\n\n## What the user said when asked up front\n\n"


def read_context(args, run_dir=None):
    """The user's answers to the host's first clarifying questions: from --context, else saved by an earlier step."""
    if args.context:
        return read(args.context).strip()
    saved = os.path.join(run_dir, "intake.md") if run_dir else ""
    return read(saved).strip() if saved and os.path.exists(saved) else ""


def parse_summary(text):
    obj = extract_json(text, "headline")
    return obj if obj is not None and str(obj.get("headline") or "").strip() else None


def present(run, planner, plan, request):
    """One last call: turn the final plan into a short visual summary (figures, diagrams, steps) for the report."""
    say("present")
    summary = ask(run, planner, "present", render("present", cwd=run.cwd, request=request, plan=plan), parse_summary,
                  os.path.join(ROOT, "schemas", "summary.schema.json"))
    if summary:
        write_json(run.path("summary.json"), summary)
    return summary


def slug_of(request):
    return re.sub(r"[^a-z0-9]+", "-", request.lower()).strip("-")[:40].strip("-") or "plan"


def thinkers(cfg):
    """The planner plus critics on a different CLI or model, for stages where several models work the same brief."""
    roles = []
    for role in [cfg["planner"]] + list(cfg["critics"].values()):
        if role_label(role) not in [role_label(r) for r in roles]:
            roles.append(role)
    return roles[:MAX_PARALLEL_THINKERS]


def find_run(cwd, spec):
    runs_dir = os.path.join(cwd, ".council", "runs")
    if spec == "latest":
        names = sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []
        if not names:
            die("no run found under " + runs_dir)
        return os.path.join(runs_dir, names[-1])
    if not os.path.isdir(spec):
        die("run folder not found: " + spec)
    return os.path.abspath(spec)


def detach(run, args):
    """Re-run this command in the background so a caller with a short command timeout can poll `council status`."""
    os.makedirs(run.dir, exist_ok=True)
    if os.path.exists(run.path("exit")):
        os.remove(run.path("exit"))
    child = [sys.executable, os.path.join(ROOT, "council.py")] + [a for a in args.argv if a != "--detach"] + ["--run-dir", run.dir]
    with open(run.path("console.log"), "a") as log:
        proc = subprocess.Popen(child, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    write(run.path("pid"), str(proc.pid))
    say("started   " + run.dir)
    say("watch     %s  (open in a browser; it updates as each model finishes)" % (report.write(run.dir) or run.path("report.html")))
    say("follow    council status --wait 100 --cwd " + run.cwd)
    return 0


def start(run):
    """Mark a run as executing in this process and make sure run folders stay out of git."""
    _active_run.append(run)
    if os.path.exists(run.path("exit")):
        os.remove(run.path("exit"))
    gitignore = os.path.join(run.cwd, ".council", ".gitignore")
    if not os.path.exists(gitignore):
        write(gitignore, "runs/\n")


def questions_markdown(questions):
    lines = []
    for i, q in enumerate(questions, 1):
        lines += ["%d. **%s**" % (i, q["question"]), "   - Why it matters: " + q["why"],
                  "   - If you do not answer, the council assumes: " + q["default"]]
    return "\n".join(lines) if lines else "None. The project files answered everything that would change the plan."


def run_arena(run, drafts, rubric, planner, judge, common):
    """Judge competing drafts against a rubric, then have the planner build one plan from the best of them."""
    say("arena")
    for label, _, text in drafts:
        write(run.path("candidates", label + ".md"), text + "\n")
    candidates = "\n\n".join("### Candidate %s\n\n%s" % (label, text) for label, _, text in drafts)
    rubric_text = "\n".join("- " + c for c in rubric or []) or \
        "(none was given: write three to six gradeable criteria from the request before you read the candidates)"
    verdict = ask(run, judge, "judge", render("judge", candidates=candidates, rubric=rubric_text, **common), parse_judge,
                  os.path.join(ROOT, "schemas", "judge.schema.json"))
    combined = ask(run, planner, "combine", render(
        "combine", candidates=candidates, rubric=rubric_text,
        verdict=json.dumps(verdict, indent=2, ensure_ascii=False) if verdict else "(the judge did not report)", **common), parse_synthesis)
    by_label = {label: text for label, _, text in drafts}
    if verdict:
        write_json(run.path("judge.json"), verdict)
    if combined:
        plan, note = combined
    else:
        base = verdict["base"].strip() if verdict and verdict["base"].strip() in by_label else drafts[0][0]
        plan, note = by_label[base], "Combining failed, so candidate %s is used unchanged." % base
    lines = ["# Arena record", "", "Candidates (the judge saw only the letters):", ""]
    lines += ["- %s: %s" % (label, role_label(role)) for label, role, _ in drafts]
    lines += ["", "## Judge (%s)" % role_label(judge), "", "```json", json.dumps(verdict, indent=2, ensure_ascii=False), "```",
              "", "## How the planner combined them", "", note or "No note given.", ""]
    write(run.path("combine.md"), (note or "No note given.") + "\n")
    write(run.path("arena.md"), "\n".join(lines))
    return plan


def cmd_frame(args):
    """Turn a goal stated in a line into a brief: what is known, what success means, and what to ask the user."""
    cwd = os.path.abspath(args.cwd)
    if not os.path.isdir(cwd):
        die("not a directory: " + cwd)
    cfg = load_config(args.config, cwd)
    request = read_request(args)
    context = read_context(args)
    run = Run(cwd, cfg, slug_of(request), args.run_dir)
    roles = thinkers(cfg)
    say("council: framing the goal with %d model(s), config %s" % (len(roles), cfg["_source"]))
    if args.detach:
        return detach(run, args)
    start(run)
    write(run.path("request.md"), request + "\n")
    if context:
        write(run.path("intake.md"), context + "\n")
    common = {"cwd": cwd, "request": request + (INTAKE_HEADING + context if context else ""), "kinds": KIND_HELP}

    say("frame")
    with cf.ThreadPoolExecutor(max_workers=max(1, int(cfg["limits"]["parallel"]))) as pool:
        jobs = [pool.submit(ask, run, role, "frame-" + LABELS[i], render("frame", **common), parse_frame,
                            os.path.join(ROOT, "schemas", "frame.schema.json")) for i, role in enumerate(roles)]
        frames = [j.result() for j in jobs]
    frames = {LABELS[i]: f for i, f in enumerate(frames) if f is not None}
    if not frames:
        die("no model produced a framing. See %s" % run.path("agents"))
    write_json(run.path("frames.json"), frames)

    say("brief")
    result = ask(run, cfg["planner"], "brief", render("brief", frames=json.dumps(frames, indent=2, ensure_ascii=False), **common), parse_brief)
    if result is None:
        die("the planner produced no brief. See %s" % run.path("agents"))
    brief, meta = result
    if meta["kind"] not in cfg["profiles"]:
        meta["kind"] = "coding"
    questions = questions_markdown(meta["questions"])
    write(run.path("brief.md"), "%s\n\n## Questions for the user\n\n%s\n" % (brief, questions))
    write_json(run.path("brief.json"), meta)
    if meta["questions"]:
        write(run.path("QUESTIONS.md"), "# Questions before planning\n\n%s\n" % questions)
    say("")
    say("kind      " + meta["kind"])
    say("brief     " + run.path("brief.md"))
    if meta["questions"]:
        say("questions %s  (%d)" % (run.path("QUESTIONS.md"), len(meta["questions"])))
    say("next      council plan --from %s%s" % (run.dir, " --answers FILE" if meta["questions"] else ""))
    return 0


def cmd_plan(args):
    cwd = os.path.abspath(args.cwd)
    if not os.path.isdir(cwd):
        die("not a directory: " + cwd)
    cfg = load_config(args.config, cwd)
    source, meta = None, {}
    if args.source:  # continue from `council frame`
        source = find_run(cwd, args.source)
        if not os.path.exists(os.path.join(source, "brief.md")):
            die("%s has no brief.md. Run `council frame` first, or drop --from." % source)
        meta = json.loads(read(os.path.join(source, "brief.json")))
        goal = read(os.path.join(source, "request.md")).strip()
        answers = read(args.answers).strip() if args.answers else ""
        context = read_context(args, source)
        request = "%s%s\n\n## Brief agreed before planning\n\n%s\n\n## The user's answers to the questions\n\n%s" % (
            goal, INTAKE_HEADING + context if context else "", read(os.path.join(source, "brief.md")).strip(),
            answers or "No answers were given. Use the default stated under each question and list it as an assumption.")
    else:
        goal = read_request(args)
        context = read_context(args)
        request = goal + (INTAKE_HEADING + context if context else "")
    args.kind = args.kind or meta.get("kind") or "coding"
    if args.kind not in cfg["profiles"]:
        die("unknown kind \"%s\" (available: %s)" % (args.kind, ", ".join(cfg["profiles"])))
    if args.hats:
        specs = [h.strip() for h in args.hats.split(",") if h.strip()]
    else:
        specs = cfg["profiles"][args.kind].get(args.depth) or die("profile %s has no \"%s\" depth" % (args.kind, args.depth))
    lens_files = {hat_id(spec): hat_path(cwd, args.kind, spec) for spec in specs}
    for spec in specs:
        if not lens_files[hat_id(spec)]:
            die("no lens file for \"%s\" (expected hats/%s/%s.md)" % (spec, args.kind, spec))
    hats = list(lens_files)
    if not os.path.exists(os.path.join(ROOT, "prompts", "template-%s.md" % args.kind)) and not args.plan:
        die("no plan template for kind \"%s\" (expected prompts/template-%s.md)" % (args.kind, args.kind))
    assignment = assign_hats(cfg, hats)
    planner, verifier = cfg["planner"], cfg["critics"][cfg["verifier"]]
    # Arena: several models draft the same plan, a judge compares them, the planner grafts the best parts together.
    arena = (args.depth == "full" or bool(source)) if args.arena is None else args.arena
    drafters = thinkers(cfg) if arena and not args.plan else [planner]
    arena = len(drafters) > 1
    run = Run(cwd, cfg, slug_of(goal), args.run_dir or source)

    say("council: %s plan, %s depth, config %s" % (args.kind, args.depth, cfg["_source"]))
    if role_label(verifier) == role_label(planner):
        say("note: the verifier is the same CLI and model as the planner, so its check is not independent.")
    if args.dry_run:
        if args.plan:
            say("  draft     skipped, using " + args.plan)
        for i, role in enumerate([] if args.plan else drafters):
            say("  draft     %-20s %s" % ("candidate " + LABELS[i] if arena else "", role_label(role)))
        if arena:
            say("  judge     " + role_label(verifier))
            say("  combine   " + role_label(planner))
        for hat, critic in assignment.items():
            say("  critique  %-20s %s" % (hat, role_label(cfg["critics"][critic])))
        say("  revise    " + role_label(planner))
        say("  verify    " + role_label(verifier))
        return 0
    if args.detach:
        return detach(run, args)
    start(run)

    if not source:
        write(run.path("request.md"), goal + "\n")
    if context:
        write(run.path("intake.md"), context + "\n")
    if source and args.answers:
        write(run.path("answers.md"), read(args.answers).strip() + "\n")
    before = repo_state(cwd)
    common = {"cwd": cwd, "request": request}
    pool = cf.ThreadPoolExecutor(max_workers=max(1, int(cfg["limits"]["parallel"])))

    # 1 draft: one plan, or an arena of competing plans combined into one
    say("draft")
    if args.plan:
        draft = read(args.plan).strip()
    else:
        prompt = render("draft", template=render("template-" + args.kind), **common)
        jobs = [pool.submit(ask, run, role, "draft-" + LABELS[i] if arena else "draft", prompt, parse_plan)
                for i, role in enumerate(drafters)]
        drafts = [(LABELS[i], drafters[i], job.result()) for i, job in enumerate(jobs)]
        drafts = [d for d in drafts if d[2] is not None]
        if not drafts:
            die("no model produced a plan. See %s" % run.path("agents"))
        draft = drafts[0][2]
        if len(drafts) > 1:
            draft = run_arena(run, drafts, meta.get("rubric"), planner, verifier, common)
    write(run.path("plan.v1.md"), draft + "\n")

    # 2 blind critique, one lens per critic, in parallel
    say("critique")
    jobs = {}
    for hat, critic in assignment.items():
        prompt = render("critique", hat=hat, hat_body=read(lens_files[hat]), plan=draft, **common)
        jobs[hat] = pool.submit(ask, run, cfg["critics"][critic], "critique-" + hat, prompt, parse_findings,
                                os.path.join(ROOT, "schemas", "findings.schema.json"))
    per_hat, gaps = {}, []
    for hat, job in jobs.items():
        result = job.result()
        if result is None:
            gaps.append(hat)
            continue
        per_hat[hat] = dict(result, critic=assignment[hat])
        write_json(run.path("findings", hat + ".json"), per_hat[hat])

    # 3 merge
    findings = merge_findings(per_hat)
    for f in findings:
        f.update(decision="unanswered", reason="")
    say("  %d finding(s): %s" % (len(findings), ", ".join(
        "%d %s" % (sum(f["severity"] == s for f in findings), s) for s in SEVERITIES) if findings else "nothing to change"))

    # 4 the planner answers every finding and revises
    final, notes, verifier_ran = draft, [], False
    if findings:
        say("revise")
        public = [{k: f[k] for k in ("id", "severity", "hat", "claim", "evidence", "suggestion", "confidence")} for f in findings]
        revision = ask(run, planner, "revise", render(
            "revise", plan=draft, findings=json.dumps(public, indent=2, ensure_ascii=False), **common), parse_revision)
        if revision is None:
            notes.append("The revision step failed, so plan.md is still the first draft and no finding was answered.")
        else:
            final, ledger = revision
            for f in findings:
                f.update(ledger.get(f["id"], {}))

    # 5 another model checks how the blocker and high findings were handled
    major = [f for f in findings if is_major(f)]
    if major and not notes:
        say("verify")
        rows = [{k: f[k] for k in ("id", "severity", "claim", "evidence", "suggestion", "decision", "reason")} for f in major]
        checks = ask(run, verifier, "verify", render(
            "verify", plan=final, findings=json.dumps(rows, indent=2, ensure_ascii=False), **common), parse_checks,
            os.path.join(ROOT, "schemas", "verify.schema.json"))
        if checks is not None:
            verifier_ran = True
            for f in major:
                check = checks.get(f["id"], {"status": "unresolved", "note": "The verifier did not report on this finding."})
                f.update(verify=check["status"], verify_note=check["note"])
    pool.shutdown()

    # 6 write results, then a visual summary of the final plan
    items = needs_you(findings, verifier_ran)
    write(run.path("plan.md"), final + "\n")
    if not args.no_summary:
        present(run, planner, final, request)
    write(run.path("ledger.md"), ledger_markdown(findings, gaps))
    write_json(run.path("ledger.json"), {"request": goal, "kind": args.kind, "depth": args.depth,
                                         "planner": role_label(planner), "findings": findings, "gaps": gaps,
                                         "needs_you": [f["id"] for f, _ in items]})
    open_points = bool(items or gaps or notes)
    if open_points:
        write(run.path("NEEDS-YOU.md"), needs_you_markdown(items, gaps, notes))
    elif os.path.exists(run.path("NEEDS-YOU.md")):
        os.unlink(run.path("NEEDS-YOU.md"))
    after = repo_state(cwd)
    if before is not None and after != before:
        say("WARNING: files outside .council/ changed during this run. Agents are meant to be read-only; check `git status`.")

    counts = {d: sum(f["decision"] == d for f in findings) for d in DECISIONS + ("unanswered",)}
    say("")
    say("report    " + run.path("report.html"))
    say("plan      " + run.path("plan.md"))
    say("ledger    %s  (%s)" % (run.path("ledger.md"), ", ".join("%d %s" % (n, d) for d, n in counts.items() if n) or "no findings"))
    if open_points:
        say("needs you " + run.path("NEEDS-YOU.md"))
        return 3
    say("ready: no open blocker or high finding.")
    return 0


def cmd_init(args):
    found = detect()
    if not found:
        die("no agent CLI found on PATH (looked for: %s)" % ", ".join(HARNESSES))
    target = os.path.join(os.path.abspath(args.cwd), ".council", "config.json") if args.local else USER_CONFIG
    if os.path.exists(target) and not args.force:
        die("%s already exists (use --force to overwrite)" % target)
    cfg = suggest(inventory())
    write_json(target, cfg)
    say("wrote " + target)
    say("planner   " + role_label(cfg["planner"]))
    for name, role in cfg["critics"].items():
        say("critic    %-10s %s%s" % (name, role_label(role), "  (verifier)" if name == cfg["verifier"] else ""))
    say("A null model means that CLI's own default. Change the lineup with `council configure` or edit the file.")
    return 0


def cmd_detect(args):
    """Machine-readable picture of this machine, for a host agent that is setting the skill up."""
    cwd = os.path.abspath(args.cwd)
    inv = inventory()
    path = config_path(args.config, cwd)
    current = None
    if path:
        cfg = load_config(args.config, cwd)
        current = {"path": path, "planner": cfg["planner"], "critics": cfg["critics"], "verifier": cfg["verifier"]}
    suggested = suggest(inv)
    notes = []
    if suggested:
        labels = {role_label(r) for r in suggested["critics"].values()} | {role_label(suggested["planner"])}
        vendors = {family(r["harness"], r["model"]) for r in list(suggested["critics"].values()) + [suggested["planner"]]}
        if len(labels) == 1:
            notes.append("Only one model is known, so planner and critics would be the same model. Ask the user which other "
                         "models their CLI can run and pass them to `configure`, or to install a second CLI.")
        elif len(vendors) == 1:
            notes.append("All suggested models are from one vendor. It works, but models from different vendors catch more.")
    if "codex" in inv:
        notes.append("codex cannot list its models; only its default is shown. Other model names can be typed in.")
    say(json.dumps({"clis": inv, "not_installed": [h for h in HARNESSES if h not in inv], "config": current,
                    "suggested": suggested, "notes": notes}, indent=2))
    return 0 if inv else 1


def cmd_configure(args):
    if not args.planner or not args.critic:
        die("give --planner CLI[:MODEL] and at least one --critic NAME=CLI[:MODEL]")
    critics = {}
    for spec in args.critic:
        name, eq, role = spec.partition("=")
        if not eq or not name:
            die("--critic must look like NAME=CLI[:MODEL], got \"%s\"" % spec)
        critics[name] = parse_role(role)
    planner = parse_role(args.planner)
    verifier = args.verifier or next((n for n, r in critics.items() if role_label(r) != role_label(planner)), next(iter(critics)))
    if verifier not in critics:
        die("--verifier must be one of the critic names: " + ", ".join(critics))
    target = os.path.join(os.path.abspath(args.cwd), ".council", "config.json") if args.local else USER_CONFIG
    old = json.loads(read(target)) if os.path.exists(target) else {}
    cfg = {"planner": planner, "critics": critics, "verifier": verifier,
           "assign": {h: c for h, c in old.get("assign", {}).items() if c in critics},
           "limits": dict(DEFAULT_LIMITS, **old.get("limits", {}))}
    if "profiles" in old:
        cfg["profiles"] = old["profiles"]
    write_json(target, cfg)
    say("wrote " + target)
    missing = sorted({r["harness"] for r in [planner] + list(critics.values()) if not shutil.which(r["harness"])})
    if missing:
        say("WARNING: not installed on this machine: " + ", ".join(missing))
    return 0


def cmd_install(args):
    """Link this folder into each CLI's skills folder so the CLI can use it as the plan-council skill."""
    targets = [h.strip() for h in args.only.split(",")] if args.only else detect()
    for h in targets:
        if h not in SKILL_DIRS:
            die("unknown CLI \"%s\" (use: %s)" % (h, ", ".join(SKILL_DIRS)))
        link = os.path.join(os.path.expanduser(SKILL_DIRS[h]), "plan-council")
        if os.path.realpath(link) == ROOT:
            say("%-9s already installed  %s" % (h, link))
        elif os.path.lexists(link):
            say("%-9s SKIPPED, something else is already at %s" % (h, link))
        else:
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.symlink(ROOT, link)
            say("%-9s installed  %s" % (h, link))
    if not targets:
        say("no agent CLI found on PATH (looked for: %s)" % ", ".join(HARNESSES))
        return 1
    return 0


def cmd_summarize(args):
    """Rebuild the visual summary of a finished run, for example after plan.md was edited by hand."""
    cwd = os.path.abspath(args.cwd)
    cfg = load_config(args.config, cwd)
    run_dir = find_run(cwd, args.run or "latest")
    if not os.path.exists(os.path.join(run_dir, "plan.md")):
        die("%s has no plan.md yet" % run_dir)
    run = Run(cwd, cfg, "", run_dir)
    ok = present(run, cfg["planner"], read(run.path("plan.md")).strip(), read(run.path("request.md")).strip())
    say("report    " + (report.write(run_dir) or "could not be built"))
    return 0 if ok else 1


def cmd_view(args):
    """Build the run's report.html (every stage, model by model) and open it in the browser."""
    cwd = os.path.abspath(args.cwd)
    run_dir = find_run(cwd, args.run or "latest")
    target = report.write(run_dir)
    if not target:
        die("could not build the report for " + run_dir)
    say("report    " + target)
    if not args.no_open:
        webbrowser.open("file://" + target)
    return 0


def cmd_status(args):
    """State of a run (default: the latest in this project). Exit: the run's own code when done, 2 while running."""
    runs_dir = os.path.join(os.path.abspath(args.cwd), ".council", "runs")
    names = sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []
    run_dir = os.path.abspath(args.run) if args.run else (os.path.join(runs_dir, names[-1]) if names else None)
    if not run_dir or not os.path.isdir(run_dir):
        die("no run found" + (" at " + args.run if args.run else " under " + runs_dir))
    done, pid = os.path.join(run_dir, "exit"), os.path.join(run_dir, "pid")

    def alive():
        try:
            os.kill(int(read(pid)), 0)
            return True
        except (OSError, ValueError):
            return False

    deadline = time.time() + args.wait
    while not os.path.exists(done) and time.time() < deadline and (not os.path.exists(pid) or alive()):
        time.sleep(2)
    if os.path.exists(os.path.join(run_dir, "console.log")):
        say(read(os.path.join(run_dir, "console.log")).rstrip())
    say("run       " + run_dir)
    say("report    " + (report.write(run_dir) or "could not be built"))
    if not os.path.exists(done):
        if os.path.exists(pid) and not alive():
            say("state     died without finishing; see console.log and agents/ in the run folder")
            return 1
        say("state     running")
        return 2
    code = int(read(done).strip() or 1)
    names = [n for n in ("NEEDS-YOU.md", "QUESTIONS.md", "brief.md", "plan.md", "summary.json", "ledger.md", "arena.md") if os.path.exists(os.path.join(run_dir, n))]
    say("files     " + ", ".join(names))
    say("state     " + {0: "done, ready", 3: "done, needs you: read NEEDS-YOU.md first"}.get(code, "failed (exit %d)" % code))
    return code


def cmd_doctor(args):
    cwd = os.path.abspath(args.cwd)
    found = detect()
    for h in HARNESSES:
        if h not in found:
            say("%-9s not found" % h)
            continue
        try:
            version = subprocess.run([h, "--version"], capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
        except (OSError, subprocess.TimeoutExpired, IndexError):
            version = "installed (version unknown)"
        say("%-9s %s" % (h, version))
    if not found and not config_path(args.config, cwd):
        say("\nNo agent CLI found. Install at least one of: " + ", ".join(HARNESSES))
        return 1
    cfg = load_config(args.config, cwd)
    say("\nconfig    " + cfg["_source"])
    say("planner   " + role_label(cfg["planner"]))
    for name, role in cfg["critics"].items():
        say("critic    %-10s %s%s" % (name, role_label(role), "  (verifier)" if name == cfg["verifier"] else ""))
    missing = sorted({r["harness"] for r in [cfg["planner"]] + list(cfg["critics"].values())
                      if r["harness"] != "cmd" and r["harness"] not in found})
    if missing:
        say("\nPROBLEM: config uses CLIs that are not installed: " + ", ".join(missing))
        return 1
    if all(role_label(r) == role_label(cfg["planner"]) for r in cfg["critics"].values()):
        say("\nNote: every critic is the same CLI and model as the planner. It works, but different model\n"
            "families catch more. Add a second CLI or pin a different model per critic.")
    return 0


def cmd_hats(args):
    cwd = os.path.abspath(args.cwd)
    cfg = load_config(args.config, cwd)
    for kind, depths in cfg["profiles"].items():
        say(kind)
        for hat in depths.get("full") or []:
            path = hat_path(cwd, kind, hat)
            title = read(path).splitlines()[0].lstrip("# ").strip() if path else "MISSING FILE"
            say("  %-26s %-6s %s" % (hat, "quick" if hat in (depths.get("quick") or []) else "full", title))
    return 0


def cmd_stats(args):
    runs_dir = os.path.join(os.path.abspath(args.cwd), ".council", "runs")
    rows = {}
    runs = 0
    for name in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
        path = os.path.join(runs_dir, name, "ledger.json")
        if not os.path.exists(path):
            continue
        runs += 1
        for f in json.loads(read(path))["findings"]:
            for key in ("lens   " + f["hat"], "critic " + f["critic"]):
                total, accepted = rows.get(key, (0, 0))
                rows[key] = (total + 1, accepted + (f["decision"] == "accept"))
    if not rows:
        say("no finished runs with findings under " + runs_dir)
        return 0
    say("%d run(s). Accepted = the planner changed the plan because of the finding.\n" % runs)
    for key in sorted(rows):
        total, accepted = rows[key]
        say("%-32s %3d findings  %3d accepted  %3d%%" % (key, total, accepted, round(100.0 * accepted / total)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="council", description="Draft a plan with one model, have other models attack it, hand you what is left.")
    sub = ap.add_subparsers(dest="command")

    def common(p):
        p.add_argument("--cwd", default=".", help="project directory the plan is about (default: current)")
        p.add_argument("--config", help="config file (default: .council/config.json, then ~/.config/plan-council/config.json)")

    p = sub.add_parser("plan", help="run the council on a request")
    p.add_argument("request", nargs="*", help="what you want planned")
    p.add_argument("--file", help="read the request from a file")
    p.add_argument("--plan", help="skip the draft and critique this existing plan file")
    p.add_argument("--from", dest="source", metavar="RUN", help="continue from a `council frame` run (a folder, or \"latest\")")
    p.add_argument("--answers", help="file with the user's answers to that run's QUESTIONS.md")
    p.add_argument("--kind", help="coding, architecture, strategy or marketing (default: from the brief, else coding)")
    p.add_argument("--arena", dest="arena", action="store_true", default=None, help="several models draft and a judge compares (default at full depth and after frame)")
    p.add_argument("--no-arena", dest="arena", action="store_false")
    p.add_argument("--context", help="file with what the user said when first asked (scope, constraints, decisions already made)")
    p.add_argument("--no-summary", action="store_true", help="skip the visual summary at the end")
    p.add_argument("--depth", default="quick", choices=("quick", "full"))
    p.add_argument("--hats", help="comma-separated lenses, overriding the profile")
    p.add_argument("--dry-run", action="store_true", help="show who would do what, run nothing")
    p.add_argument("--detach", action="store_true", help="run in the background; follow with `council status --wait N`")
    p.add_argument("--run-dir", help=argparse.SUPPRESS)
    common(p)
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("frame", help="turn a goal stated in a line into a brief and the few questions worth asking")
    p.add_argument("request", nargs="*", help="the goal, as vague as it is")
    p.add_argument("--file", help="read the goal from a file")
    p.add_argument("--context", help="file with what the user said when first asked (scope, constraints, decisions already made)")
    p.add_argument("--detach", action="store_true", help="run in the background; follow with `council status --wait N`")
    p.add_argument("--run-dir", help=argparse.SUPPRESS)
    common(p)
    p.set_defaults(fn=cmd_frame)

    p = sub.add_parser("init", help="write a config from the agent CLIs found on this machine")
    p.add_argument("--local", action="store_true", help="write .council/config.json in the project instead of your home config")
    p.add_argument("--force", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("configure", help="write the lineup: who plans, who critiques, who verifies")
    p.add_argument("--planner", help="CLI[:MODEL], for example claude:opus")
    p.add_argument("--critic", action="append", help="NAME=CLI[:MODEL], repeatable, for example gpt=codex")
    p.add_argument("--verifier", help="critic name that checks the planner's answers (default: first critic unlike the planner)")
    p.add_argument("--local", action="store_true", help="write .council/config.json in the project instead of your home config")
    common(p)
    p.set_defaults(fn=cmd_configure)

    p = sub.add_parser("install", help="link this folder into the skills folder of each installed CLI")
    p.add_argument("--only", help="comma-separated CLIs instead of every installed one")
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("view", help="open the run's report: every stage, model by model (updates while a run is going)")
    p.add_argument("--run", help="run folder (default: latest in this project)")
    p.add_argument("--no-open", action="store_true", help="build report.html but do not open a browser")
    common(p)
    p.set_defaults(fn=cmd_view)

    p = sub.add_parser("summarize", help="rebuild the visual summary of a run from its plan.md")
    p.add_argument("--run", help="run folder (default: latest in this project)")
    common(p)
    p.set_defaults(fn=cmd_summarize)

    p = sub.add_parser("status", help="state of the latest run, or of --run DIR")
    p.add_argument("--run", help="run folder (default: latest in this project)")
    p.add_argument("--wait", type=int, default=0, help="wait up to this many seconds for the run to finish")
    common(p)
    p.set_defaults(fn=cmd_status)

    for name, fn, text in (("detect", cmd_detect, "print installed CLIs, their models, the config and a suggested lineup as JSON"),
                           ("doctor", cmd_doctor, "check installed CLIs and the active config"),
                           ("hats", cmd_hats, "list the lenses per kind"),
                           ("stats", cmd_stats, "accepted-finding rate per lens and critic")):
        p = sub.add_parser(name, help=text)
        common(p)
        p.set_defaults(fn=fn)

    args = ap.parse_args(argv)
    if not args.command:
        ap.print_help()
        return 1
    args.argv = list(sys.argv[1:] if argv is None else argv)
    del _active_run[:]
    try:
        code = args.fn(args)
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else 1
    except Exception:
        traceback.print_exc()
        code = 1
    for run in _active_run:
        if os.path.isdir(run.dir):
            write(run.path("exit"), "%d\n" % code)
            report.write(run.dir)
    return code


if __name__ == "__main__":
    sys.exit(main())
