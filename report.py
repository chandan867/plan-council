"""Builds report.html for a run: every stage, which model did it, and what it said, from the first framing
to the final plan. Rebuilt after each step, so it can be left open in a browser while the council works."""
import html
import json
import os
import re

STAGES = ("frame", "brief", "draft", "judge", "combine", "critique", "revise", "verify")
STAGE_TITLES = {"frame": "Frame", "brief": "Brief", "draft": "Draft", "judge": "Judge", "combine": "Combine",
                "critique": "Critique", "revise": "Revise", "verify": "Verify"}

CSS = """
:root{--bg:#faf9f6;--card:#fff;--ink:#1f1d1a;--muted:#6b665e;--line:#e4e0d8;--accent:#0f6b5c;--soft:#f1eee8;
--red:#b3261e;--orange:#b25a00;--amber:#8a6d00;--green:#1e6b3a;--grey:#6b665e}
@media (prefers-color-scheme:dark){:root{--bg:#171614;--card:#201f1c;--ink:#ece8e1;--muted:#a39d92;--line:#35322d;
--accent:#5fc4b0;--soft:#2a2824;--red:#ff8a80;--orange:#ffb066;--amber:#e6c75a;--green:#7fd59b;--grey:#a39d92}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:1000px;margin:0 auto;padding:28px 16px 80px}h1{font-size:22px;margin:0 0 6px}h2{font-size:18px;margin:36px 0 10px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 6px}h4,h5,h6{font-size:14px;margin:14px 0 4px}p{margin:8px 0}a{color:var(--accent)}
.muted{color:var(--muted)}.goal{font-size:16px;margin:10px 0 14px;white-space:pre-wrap}
.pipe{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}.pipe a{text-decoration:none;padding:5px 10px;border:1px solid var(--line);border-radius:999px;color:var(--muted);background:var(--card);font-size:13px}
.pipe a.done{color:var(--green);border-color:var(--green)}.pipe a.running{color:var(--accent);border-color:var(--accent);font-weight:600}.pipe a.failed{color:var(--red);border-color:var(--red)}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
.who{font-size:13px;color:var(--muted)}.who b{color:var(--ink)}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:10px 0}summary{cursor:pointer;padding:10px 14px;font-weight:600}
details>.body{padding:0 14px 12px;border-top:1px solid var(--line)}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}th,td{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}code{background:var(--soft);padding:1px 4px;border-radius:4px;font-size:13px}pre{background:var(--soft);padding:10px;border-radius:6px;overflow-x:auto;font-size:13px}
.chip{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.blocker,.unresolved,.failed,.unanswered{color:var(--red)}.high{color:var(--orange)}.medium,.defer{color:var(--amber)}.low,.reject{color:var(--grey)}.accept,.resolved,.ok{color:var(--green)}.running{color:var(--accent)}
.state{font-weight:600}.headline{font-size:19px;font-weight:600;margin:6px 0 10px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.tile .v{font-size:18px;font-weight:650;line-height:1.25;overflow-wrap:anywhere}.tile .l{font-size:12.5px;color:var(--muted)}
figure{margin:16px 0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto}figcaption{font-weight:600;margin-bottom:8px}
figure .cap{color:var(--muted);font-size:13.5px;margin-top:8px}.diagram svg{height:auto;min-width:min(100%,640px)}.diagram{overflow-x:auto}pre.diagram{white-space:pre-wrap}
.steps{list-style:none;padding:0;margin:12px 0;counter-reset:s}.steps li{counter-increment:s;position:relative;padding:0 0 14px 44px;border-left:2px solid var(--line);margin-left:14px}
.steps li:last-child{border-left-color:transparent}.steps li:before{content:counter(s);position:absolute;left:-15px;top:-2px;width:28px;height:28px;border-radius:50%;background:var(--accent);color:var(--bg);font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center}
.steps b{display:block}.steps .dw{color:var(--muted);font-size:13.5px}.finding{border-left:3px solid var(--line);padding:2px 0 2px 10px;margin:10px 0}.finding p{margin:3px 0}
ul,ol{padding-left:22px;margin:6px 0}
"""


# Diagrams are drawn in the browser by Mermaid, loaded from a CDN. Offline, or if a diagram has a syntax
# error, the diagram's source text stays visible instead.
DIAGRAM_SCRIPT = """<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs";
mermaid.initialize({startOnLoad: false, securityLevel: "strict",
  theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "neutral"});
let n = 0;
for (const el of document.querySelectorAll("pre.diagram")) {
  const id = "diagram" + n++;
  try {
    const {svg} = await mermaid.render(id, el.textContent);
    const box = document.createElement("div");
    box.className = "diagram";
    box.innerHTML = svg;
    el.replaceWith(box);
  } catch (err) {
    document.getElementById(id)?.remove();
    document.getElementById("d" + id)?.remove();
  }
}
</script>"""


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def load(path):
    try:
        return json.loads(read(path))
    except ValueError:
        return None


def esc(text):
    return html.escape(str(text), quote=True)


def inline(text):
    text = esc(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)


def markdown(text):
    """Small markdown subset: headings, lists, tables, fenced code, bold, inline code. Everything is escaped."""
    out, para, lines, i, open_list = [], [], text.splitlines(), 0, None

    def flush():
        nonlocal open_list
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            del para[:]
        if open_list:
            out.append("</%s>" % open_list)
            open_list = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            block, lang = [], stripped[3:].strip().lower()
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append('<pre%s>%s</pre>' % (' class="diagram"' if lang == "mermaid" else "", esc("\n".join(block))))
        elif stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))])
                i += 1
            head, body = rows[0], rows[2:]
            out.append('<div class="scroll"><table><tr>%s</tr>%s</table></div>' % (
                "".join("<th>%s</th>" % inline(c) for c in head),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c.replace("\\|", "|")) for c in r) for r in body)))
            continue
        elif re.match(r"^#{1,6}\s", stripped):
            flush()
            level = min(6, len(stripped) - len(stripped.lstrip("#")) + 2)
            out.append("<h%d>%s</h%d>" % (level, inline(stripped.lstrip("#").strip()), level))
        elif re.match(r"^([-*]|\d+[.)])\s+", stripped):
            if para:
                out.append("<p>%s</p>" % inline(" ".join(para)))
                del para[:]
            tag = "ul" if stripped[0] in "-*" else "ol"
            if open_list != tag:
                if open_list:
                    out.append("</%s>" % open_list)
                out.append("<%s>" % tag)
                open_list = tag
            out.append("<li>%s</li>" % inline(re.sub(r"^([-*]|\d+[.)])\s+", "", stripped)))
        elif not stripped:
            flush()
        elif open_list and line.startswith(" "):
            out[-1] = out[-1][:-5] + " " + inline(stripped) + "</li>"
        else:
            if open_list:
                out.append("</%s>" % open_list)
                open_list = None
            para.append(stripped)
        i += 1
    flush()
    return "\n".join(out)


def chip(value):
    return '<span class="chip %s">%s</span>' % (esc(value), esc(value))


def fold(title, body, open_=False):
    return '<details%s><summary>%s</summary><div class="body">%s</div></details>' % (" open" if open_ else "", title, body)


def stage_of(agent):
    name = agent.split(".retry")[0]
    return name.split("-")[0] if name.split("-")[0] in STAGES else name


def build(run_dir):
    def path(*parts):
        return os.path.join(run_dir, *parts)

    events = [e for e in (load_line(l) for l in read(path("events.jsonl")).splitlines()) if e]
    agents = {}  # agent name -> {role, seconds, code, ok}
    for e in events:
        a = agents.setdefault(e.get("agent", ""), {})
        if e.get("event") == "start":
            a.update(role=e.get("role", ""), state="running")
        elif e.get("event") == "end":
            a.update(seconds=e.get("seconds"), code=e.get("code"), state="ok" if e.get("code") == 0 else "failed")
        elif e.get("event") == "result":
            a.update(state="ok" if e.get("ok") else "failed")
    agents.pop("", None)
    exit_code = read(path("exit")).strip()
    finished = exit_code != ""
    if finished:
        for a in agents.values():
            if a.get("state") == "running":
                a["state"] = "failed"

    def who(agent):
        a = agents.get(agent) or {}
        took = " · %ss" % a["seconds"] if a.get("seconds") is not None else ""
        return '<span class="who"><b>%s</b>%s</span>' % (esc(a.get("role") or "unknown model"), took)

    def raw(agent):
        links = ['<a href="agents/%s%s">%s</a>' % (esc(agent), ext, label) for ext, label in
                 ((".prompt.md", "prompt"), (".out", "raw reply")) if os.path.exists(path("agents", agent + ext))]
        return '<span class="who"> · %s</span>' % " · ".join(links) if links else ""

    stage_state = {}
    for name, a in agents.items():
        s = stage_of(name)
        order = {"failed": 0, "ok": 1, "running": 2}
        if s not in stage_state or order[a.get("state", "running")] > order[stage_state[s]]:
            stage_state[s] = a.get("state", "running")
    ledger = load(path("ledger.json")) or {}
    brief_meta = load(path("brief.json")) or {}
    sections = []

    # ---- the plan at a glance (built last, shown first)
    summary = load(path("summary.json"))
    if summary:
        body = '<p class="headline">%s</p>' % inline(summary.get("headline", ""))
        if summary.get("summary"):
            body += "<ul>%s</ul>" % "".join("<li>%s</li>" % inline(b) for b in summary["summary"])
        if summary.get("numbers"):
            body += '<div class="tiles">%s</div>' % "".join(
                '<div class="tile"><div class="v">%s</div><div class="l">%s</div></div>' % (inline(n.get("value", "")), inline(n.get("label", ""))) for n in summary["numbers"])
        for d in summary.get("diagrams") or []:
            body += '<figure><figcaption>%s</figcaption><pre class="diagram">%s</pre>%s</figure>' % (
                inline(d.get("title", "")), esc(d.get("mermaid", "")), '<div class="cap">%s</div>' % inline(d["caption"]) if d.get("caption") else "")
        if summary.get("steps"):
            body += "<h3>Steps, in order</h3><ol class=\"steps\">%s</ol>" % "".join(
                "<li><b>%s</b>%s<span class=\"dw\">Done when: %s</span></li>" % (inline(st.get("name", "")), inline(st.get("what", "")), inline(st.get("done_when", ""))) for st in summary["steps"])
        if summary.get("decisions"):
            body += '<h3>Key decisions</h3><div class="scroll"><table><tr><th>Decision</th><th>Why</th></tr>%s</table></div>' % "".join(
                "<tr><td>%s</td><td>%s</td></tr>" % (inline(d.get("decision", "")), inline(d.get("why", ""))) for d in summary["decisions"])
        if summary.get("risks"):
            body += '<h3>Main risks</h3><div class="scroll"><table><tr><th>Risk</th><th>How the plan handles it</th></tr>%s</table></div>' % "".join(
                "<tr><td>%s</td><td>%s</td></tr>" % (inline(r.get("risk", "")), inline(r.get("handling", ""))) for r in summary["risks"])
        if summary.get("open_questions"):
            body += "<h3>Still open</h3><ul>%s</ul>" % "".join("<li>%s</li>" % inline(q) for q in summary["open_questions"])
        sections.append(("glance", "The plan at a glance", body))

    # ---- frame
    frames = load(path("frames.json")) or {}
    if frames or stage_state.get("frame"):
        body = "<p class=\"muted\">Each model read the project on its own and said how it understands the goal.</p>"
        for label in sorted(frames):
            f = frames[label]
            inner = "<p>%s</p>" % inline(f.get("goal", ""))
            if f.get("known"):
                inner += "<h4>What it found</h4><ul>%s</ul>" % "".join(
                    "<li>%s <span class=\"muted\">(%s)</span></li>" % (inline(k.get("fact", "")), inline(k.get("evidence", ""))) for k in f["known"])
            if f.get("directions"):
                inner += "<h4>Directions it sees</h4><ul>%s</ul>" % "".join(
                    "<li><b>%s.</b> %s <span class=\"muted\">Bet: %s</span></li>" % (inline(d.get("name", "")), inline(d.get("summary", "")), inline(d.get("bet", ""))) for d in f["directions"])
            if f.get("questions"):
                inner += "<h4>What it wanted to ask</h4><ul>%s</ul>" % "".join("<li>%s</li>" % inline(q.get("question", "")) for q in f["questions"])
            agent = "frame-" + label
            body += fold("Framing %s &nbsp; %s" % (esc(label), who(agent)), inner + "<p>%s</p>" % raw(agent).replace(" · ", "", 1))
        for name, a in sorted(agents.items()):
            if stage_of(name) == "frame" and a.get("state") != "ok" and name.split("-")[-1] not in frames:
                body += '<div class="card">%s %s %s</div>' % (esc(name), who(name), chip(a.get("state", "running")))
        sections.append(("frame", "How each model understood the goal", body))

    # ---- brief
    brief = read(path("brief.md"))
    if brief or stage_state.get("brief"):
        body = '<p>%s%s</p>' % (who("brief"), raw("brief"))
        if brief:
            body += fold("The brief the council plans against", markdown(brief), True)
        if brief_meta.get("rubric"):
            body += "<h3>Rubric for judging plans</h3><ul>%s</ul>" % "".join("<li>%s</li>" % inline(c) for c in brief_meta["rubric"])
        if read(path("intake.md")):
            body += "<h3>What you said up front</h3><div class=\"card\">%s</div>" % markdown(read(path("intake.md")))
        answers = read(path("answers.md"))
        if answers:
            body += "<h3>Your answers</h3><div class=\"card\">%s</div>" % markdown(answers)
        sections.append(("brief", "Brief and questions for you", body))

    if read(path("intake.md")) and not (brief or stage_state.get("brief")):
        sections.append(("intake", "What you said up front", '<div class="card">%s</div>' % markdown(read(path("intake.md")))))

    # ---- draft / arena
    candidates = sorted(n[:-3] for n in os.listdir(path("candidates"))) if os.path.isdir(path("candidates")) else []
    plan_v1 = read(path("plan.v1.md"))
    if candidates or plan_v1 or stage_state.get("draft"):
        body = ""
        if candidates:
            body += "<p class=\"muted\">Each model wrote its own plan without seeing the others.</p>"
            for label in candidates:
                agent = "draft-" + label
                body += fold("Candidate %s &nbsp; %s" % (esc(label), who(agent)), markdown(read(path("candidates", label + ".md"))) + "<p>%s</p>" % raw(agent).replace(" · ", "", 1))
        for name, a in sorted(agents.items()):
            if stage_of(name) == "draft" and a.get("state") != "ok":
                body += '<div class="card">%s %s %s</div>' % (esc(name), who(name), chip(a.get("state", "running")))
        judge = load(path("judge.json"))
        if judge:
            body += "<h3>Judge &nbsp; %s%s</h3><p class=\"muted\">The judge saw only the letters, not which model wrote which.</p>" % (who("judge"), raw("judge"))
            body += '<div class="scroll"><table><tr><th>Candidate</th><th>Score</th><th>Notes</th></tr>%s</table></div>' % "".join(
                "<tr><td><b>%s</b>%s</td><td>%s</td><td>%s</td></tr>" % (
                    esc(s.get("candidate", "")), " " + chip("base") if s.get("candidate") == judge.get("base") else "",
                    esc(s.get("total", "")), inline(s.get("notes", ""))) for s in judge.get("scores") or [])
            body += "<p><b>Base: %s.</b> %s</p>" % (esc(judge.get("base", "")), inline(judge.get("reason", "")))
            if judge.get("grafts"):
                body += "<p>Parts to take from the others:</p><ul>%s</ul>" % "".join(
                    "<li><b>From %s:</b> %s <span class=\"muted\">%s</span></li>" % (esc(g.get("from", "")), inline(g.get("what", "")), inline(g.get("why", ""))) for g in judge["grafts"])
        note = read(path("combine.md"))
        if note:
            body += "<h3>How the planner combined them &nbsp; %s%s</h3><div class=\"card\">%s</div>" % (who("combine"), raw("combine"), markdown(note))
        elif not judge and read(path("arena.md")):
            body += fold("Arena record", markdown(read(path("arena.md"))))
        if plan_v1:
            single = "" if candidates else " &nbsp; %s%s" % (who("draft"), raw("draft"))
            body += fold("Plan before the critics saw it" + single, markdown(plan_v1))
        sections.append(("draft", "Drafts", body))

    # ---- critique
    lens_files = sorted(os.listdir(path("findings"))) if os.path.isdir(path("findings")) else []
    if lens_files or stage_state.get("critique"):
        body = "<p class=\"muted\">Each critic attacked the plan through one lens, without seeing the others.</p>"
        seen = set()
        for name in lens_files:
            hat = name[:-5]
            seen.add(hat)
            data = load(path("findings", name)) or {}
            agent = "critique-" + hat
            inner = "<p>%s</p>" % inline(data.get("summary", "")) if data.get("summary") else ""
            for f in data.get("findings") or []:
                inner += '<div class="finding"><p>%s %s</p><p class="muted">Evidence: %s</p><p class="muted">Suggested change: %s</p></div>' % (
                    chip(f.get("severity", "")), inline(f.get("claim", "")), inline(f.get("evidence") or "none given"), inline(f.get("suggestion") or "none given"))
            if not data.get("findings"):
                inner += "<p class=\"muted\">No findings under this lens.</p>"
            count = len(data.get("findings") or [])
            body += fold("%s &nbsp; <span class=\"who\">%d finding%s · critic %s ·</span> %s" % (
                esc(hat), count, "" if count == 1 else "s", esc(data.get("critic", "")), who(agent)), inner + "<p>%s</p>" % raw(agent).replace(" · ", "", 1), True)
        for name, a in sorted(agents.items()):
            hat = name.split(".retry")[0][len("critique-"):]
            if stage_of(name) == "critique" and hat not in seen and ".retry" not in name:
                body += '<div class="card">%s %s %s</div>' % (esc(hat), who(name), chip(a.get("state", "running")))
        sections.append(("critique", "Critique, lens by lens", body))

    # ---- decisions
    findings = ledger.get("findings") or []
    if findings or stage_state.get("revise"):
        body = '<p>Planner: %s%s' % (who("revise"), raw("revise"))
        if "verify" in agents:
            body += ' &nbsp; Verifier: %s%s' % (who("verify"), raw("verify"))
        body += "</p>"
        if findings:
            rows = ""
            for f in findings:
                lens = esc(f.get("hat", "")) + (" +" + esc(", ".join(f["also_raised_by"])) if f.get("also_raised_by") else "")
                check = chip(f["verify"]) + '<br><span class="muted">%s</span>' % inline(f.get("verify_note", "")) if f.get("verify") else '<span class="muted">not checked</span>'
                rows += "<tr><td><b>%s</b><br>%s</td><td>%s<br><span class=\"muted\">%s</span></td><td>%s</td><td>%s<br><span class=\"muted\">%s</span></td><td>%s</td></tr>" % (
                    esc(f.get("id", "")), chip(f.get("severity", "")), lens, esc(f.get("critic", "")), inline(f.get("claim", "")),
                    chip(f.get("decision", "")), inline(f.get("reason", "")), check)
            body += '<div class="scroll"><table><tr><th>ID</th><th>Lens / critic</th><th>Finding</th><th>Planner decided</th><th>Verifier</th></tr>%s</table></div>' % rows
            if ledger.get("gaps"):
                body += "<p class=\"failed\">Lenses that never reported: %s</p>" % esc(", ".join(ledger["gaps"]))
        else:
            body += "<p class=\"muted\">Waiting for the planner's answers.</p>"
        sections.append(("revise", "What the planner did with each finding", body))

    # ---- result
    plan = read(path("plan.md"))
    needs = read(path("NEEDS-YOU.md"))
    if plan or needs:
        body = ""
        if needs:
            body += fold("Needs you", markdown(needs), True)
        if plan:
            body += fold("Final plan", markdown(plan), True)
        sections.append(("result", "Result", body))

    # ---- stages not reached yet are shown as such, so the page always lists the whole path
    if finished and exit_code == "0" and not plan:
        pending = "Not started yet. This run has only been framed. Planning starts with <code>council plan --from latest --answers FILE</code> (leave out <code>--answers</code> to use the defaults)."
    elif finished:
        pending = "Not reached: the run stopped before this step."
    else:
        pending = "Not reached yet."
    have = {anchor for anchor, _, _ in sections}
    for anchor, title in (("draft", "Drafts"), ("critique", "Critique, lens by lens"),
                          ("revise", "What the planner did with each finding"), ("result", "Result")):
        if anchor not in have:
            sections.append((anchor, title, '<p class="muted">%s</p>' % pending))

    # ---- header
    if not finished:
        state = '<span class="state running">running</span>'
    else:
        text = {"0": "done", "3": "done, needs you"}.get(exit_code, "failed (exit %s)" % exit_code)
        if exit_code == "0" and not plan:
            text = "framed: waiting for your answers" if read(path("QUESTIONS.md")) else "framed"
        state = '<span class="state %s">%s</span>' % ("ok" if exit_code == "0" else "failed", esc(text))
    present = [s for s in STAGES if s in stage_state or s in ("draft", "critique", "revise", "verify")]
    pipe = "".join('<a class="%s" href="#%s">%s</a>' % (
        {"ok": "done", "running": "running", "failed": "failed", None: "todo"}[stage_state.get(s)],
        {"judge": "draft", "combine": "draft", "verify": "revise"}.get(s, s), STAGE_TITLES[s]) for s in present)
    calls = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(name), esc(a.get("role", "")), "" if a.get("seconds") is None else "%ss" % a["seconds"], chip(a.get("state", "running")))
        for name, a in agents.items())
    kind = ledger.get("kind") or brief_meta.get("kind") or ""
    head = "<h1>Plan council</h1><div class=\"goal\">%s</div><p>%s%s <span class=\"muted\">· %s</span></p><div class=\"pipe\">%s</div>" % (
        esc(read(path("request.md")).strip()), state, " <span class=\"muted\">· %s</span>" % esc(kind) if kind else "", esc(os.path.basename(run_dir.rstrip("/"))), pipe)
    head += fold("Every model call (%d)" % len(agents), '<div class="scroll"><table><tr><th>Step</th><th>CLI / model</th><th>Time</th><th>Result</th></tr>%s</table></div>' % calls)
    body = "".join('<h2 id="%s">%d. %s</h2>%s' % (anchor, i, title, content) for i, (anchor, title, content) in enumerate(sections, 1))
    refresh = "" if finished else '<meta http-equiv="refresh" content="6">'
    if 'class="diagram"' in body:
        body += DIAGRAM_SCRIPT
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '%s<title>Plan council run</title><style>%s</style></head><body><main>%s%s</main></body></html>' % (refresh, CSS, head, body))


def load_line(line):
    try:
        return json.loads(line)
    except ValueError:
        return None


def write(run_dir):
    """Rebuild report.html. Never raises: a broken report must not stop a run."""
    target = os.path.join(run_dir, "report.html")
    try:
        page = build(run_dir)
        with open(target + ".tmp", "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(target + ".tmp", target)
    except Exception:  # noqa: BLE001
        return None
    return target
