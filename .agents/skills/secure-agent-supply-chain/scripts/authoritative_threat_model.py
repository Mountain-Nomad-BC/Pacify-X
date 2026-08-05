#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system")
    a = ap.parse_args()
    s = json.loads(Path(a.system).read_text())
    threats = []
    for tool in s.get("tools", []):
        if tool.get("network") and tool.get("write"):
            threats.append(
                {
                    "id": "tool-confused-deputy",
                    "asset": tool.get("name"),
                    "risk": "high",
                    "controls": [
                        "independent authorization",
                        "schema validation",
                        "egress allowlist",
                        "approval for destructive writes",
                    ],
                }
            )
    for mem in s.get("memory_stores", []):
        threats.append(
            {
                "id": "memory-poisoning-or-leakage",
                "asset": mem.get("name"),
                "risk": "high",
                "controls": [
                    "scope isolation",
                    "write gate",
                    "provenance",
                    "deletion tests",
                ],
            }
        )
    if s.get("retrieval"):
        threats.append(
            {
                "id": "indirect-prompt-injection",
                "asset": "retrieval corpus",
                "risk": "high",
                "controls": [
                    "data-instruction separation",
                    "tool authority independent of content",
                    "adversarial corpus tests",
                ],
            }
        )
    print(
        json.dumps(
            {
                "assets": s.get("assets", []),
                "trust_boundaries": s.get("trust_boundaries", []),
                "threats": threats,
                "framework_mappings": [
                    "OWASP LLM/Agentic",
                    "MITRE ATLAS",
                    "NIST AI RMF",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
