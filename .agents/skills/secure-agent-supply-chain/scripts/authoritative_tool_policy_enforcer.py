#!/usr/bin/env python3
from __future__ import annotations
import argparse
import fnmatch
import json
from pathlib import Path


def match(v, ps):
    return any(fnmatch.fnmatch(v, p) for p in ps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("policy")
    ap.add_argument("request")
    a = ap.parse_args()
    p = json.loads(Path(a.policy).read_text())
    r = json.loads(Path(a.request).read_text())
    reasons = []
    op = r.get("operation")
    target = r.get("target", "")
    scope = {
        "read": "read_scope",
        "write": "write_scope",
        "network": "network_scope",
    }.get(op)
    if not scope or not match(target, p.get(scope, [])):
        reasons.append("operation outside declared scope")
    if p.get("requires_approval") and not r.get("approval_id"):
        reasons.append("approval required")
    if p.get("destructive") and not r.get("rollback_ready"):
        reasons.append("destructive operation lacks rollback")
    print(
        json.dumps(
            {"allow": not reasons, "reasons": reasons, "tool": p.get("name")}, indent=2
        )
    )
    raise SystemExit(0 if not reasons else 3)


if __name__ == "__main__":
    main()
