"""Attach custodian evidence to each B7 decision: which component reads the resource
but is not one of its producers.

Sources only — no new component is invented and nothing is approved here.
"""
from __future__ import annotations

import json
from pathlib import Path

EVIDENCE = Path(__file__).parent
REGISTER = EVIDENCE / "px-os-1067-b7-owner-decision-register.json"
MATRIX = EVIDENCE / "px-os-1067-runtime-state-ownership-matrix.json"

matrix = {item["resource_id"]: item for item in json.loads(MATRIX.read_text(encoding="utf-8"))["resources"]}
register = json.loads(REGISTER.read_text(encoding="utf-8"))

counts = {"registered": 0, "ambiguous": 0, "none": 0}
for decision in register["decisions"]:
    resource = matrix[decision["resource_id"]]
    writers = {str(path).replace("\\", "/") for path in resource.get("writers") or []}
    readers = sorted(
        {str(path).replace("\\", "/") for path in resource.get("readers") or []} - writers
    )
    if len(readers) == 1:
        custody = {"status": "registered", "custodian": readers[0], "candidates": readers}
    elif readers:
        custody = {"status": "ambiguous", "custodian": None, "candidates": readers}
    else:
        custody = {"status": "none", "custodian": None, "candidates": []}
    decision["custodian_evidence"] = custody
    counts[custody["status"]] += 1

REGISTER.write_text(json.dumps(register, indent=1, sort_keys=True), encoding="utf-8")
print(counts)
