#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("change")
    ap.add_argument("dependency_graph")
    a = ap.parse_args()
    c = json.loads(Path(a.change).read_text())
    g = json.loads(Path(a.dependency_graph).read_text())
    seeds = set(c.get("changed_capabilities", []))
    affected = set(seeds)
    changed = True
    while changed:
        changed = False
        for src, dsts in g.get("edges", {}).items():
            if src in affected:
                for d in dsts:
                    if d not in affected:
                        affected.add(d)
                        changed = True
    suites = ["package-integrity"]
    if c.get("code_changed"):
        suites += ["deterministic-correctness", "behavioral-competence"]
    if c.get("permissions_changed"):
        suites += ["adversarial-robustness", "operational-resilience"]
    if c.get("dependencies_changed"):
        suites += ["release-trust"]
    print(
        json.dumps(
            {
                "affected_capabilities": sorted(affected),
                "required_suites": sorted(set(suites)),
                "invalidate_prior_evidence": bool(
                    c.get("code_changed") or c.get("dependencies_changed")
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
