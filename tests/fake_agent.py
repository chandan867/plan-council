#!/usr/bin/env python3
"""Stand-in for an agent CLI. Reads the prompt file, answers by stage. FAKE_MODE changes behaviour."""
import json, os, re, sys

prompt = open(sys.argv[1], encoding="utf-8").read()
stage = re.search(r"^STAGE: (\w+)", prompt, re.M).group(1)
mode = os.environ.get("FAKE_MODE", "ok")

if stage == "draft":
    print("Here is my plan.\n<<<PLAN\n# Plan v1\n\n1. Build the thing.\nPLAN>>>")
elif stage == "frame":
    print(json.dumps({"kind": "strategy", "goal": "Grow revenue tenfold", "success": ["10x MRR"], "known": [], "directions": [],
                      "questions": [{"question": "What is MRR today?", "why": "baseline", "default": "10k"}]}))
elif stage == "brief":
    meta = {"kind": "strategy", "rubric": ["Names the bottleneck", "Math reaches target"],
            "questions": [{"question": "What is MRR today?", "why": "Sets the baseline.", "default": "Assume 10k."}]}
    print("<<<BRIEF\n# Brief\n\nGrow MRR tenfold in a year.\nBRIEF>>>\n<<<META\n%s\nMETA>>>" % json.dumps(meta))
elif stage == "judge":
    print(json.dumps({"scores": [{"candidate": "A", "total": 12, "notes": "ok"}], "base": "B",
                      "grafts": [{"from": "A", "what": "the test plan", "why": "base lacks it"}], "reason": "B is right"}))
elif stage == "combine":
    print("<<<PLAN\n# Plan v1 (combined)\n\n1. Build the thing.\nPLAN>>>\n<<<SYNTHESIS\nBase B, grafted tests from A.\nSYNTHESIS>>>")
elif stage == "critique":
    hat = re.search(r"^HAT: (\S+)", prompt, re.M).group(1)
    if mode == "garbage" and hat == "premortem":
        print("I could not produce JSON, sorry.")
    else:
        findings = [
            {"severity": "high", "claim": "The plan ignores the existing auth module.", "evidence": "src/auth.py:10",
             "suggestion": "Reuse it.", "confidence": "high"},
            {"severity": "low", "claim": "Nit seen only through the %s lens." % hat, "evidence": "unverified: guess",
             "suggestion": "Tidy up.", "confidence": "low"},
        ]
        print('Some chatter with a stray {"x": 1} object.\n```json\n%s\n```' % json.dumps({"summary": "ok", "findings": findings}))
elif stage == "revise":
    ids = sorted(set(re.findall(r'"id": "(F\d+)"', prompt)), key=lambda i: int(i[1:]))
    if mode == "silent":
        ids = ids[1:]
    ledger = [{"id": i, "decision": "accept" if n == 0 else "reject", "reason": "because"} for n, i in enumerate(ids)]
    print("<<<PLAN\n# Plan v2\n\n1. Reuse auth, then build the thing.\nPLAN>>>\n<<<LEDGER\n%s\nLEDGER>>>" % json.dumps({"ledger": ledger}))
elif stage == "present":
    print(json.dumps({"headline": "Build login on the existing auth module", "summary": ["Reuse auth"], "numbers": [{"label": "Slices", "value": "3"}],
                      "diagrams": [{"title": "Flow", "caption": "c", "mermaid": 'flowchart LR\n  A["UI"] --> B["API"]'}],
                      "steps": [{"name": "Skeleton", "what": "Thin path", "done_when": "Test passes"}],
                      "decisions": [{"decision": "Reuse auth", "why": "Exists"}], "risks": [{"risk": "r", "handling": "h"}], "open_questions": []}))
elif stage == "verify":
    ids = sorted(set(re.findall(r'"id": "(F\d+)"', prompt)))
    status = "unresolved" if mode == "unresolved" else "resolved"
    print(json.dumps({"checks": [{"id": i, "status": status, "note": "checked"} for i in ids]}))
