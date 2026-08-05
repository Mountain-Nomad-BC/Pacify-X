"""Compile verified engineering process records into inert skill candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any

from .contracts import validate_instance


TOKEN = re.compile(r"[a-z0-9]+")


def _terms(value: str) -> set[str]:
    return {item for item in TOKEN.findall(value.casefold()) if len(item) > 2}


def _slug(value: str) -> str:
    words = TOKEN.findall(value.casefold())[:6]
    return "-".join(words)[:63].strip("-") or "process-candidate"


def compile_process_candidate(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    validate_instance(record, root / "contracts/engineering-process-record.schema.json")
    if record["verification"]["outcome_met"] is not True:
        return {
            "valid": False,
            "decision": "reject_unverified",
            "errors": ["outcome is not verified"],
            "activation": "blocked",
        }
    if any(item["verified"] is not True for item in record["failures"]):
        return {
            "valid": False,
            "decision": "reject_unverified_recovery",
            "errors": ["a failure recovery is unverified"],
            "activation": "blocked",
        }
    canonical = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    process_hash = hashlib.sha256(canonical).hexdigest()
    catalog = tomllib.loads(
        (root / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    process_terms = _terms(
        " ".join(
            [
                record["goal"],
                record["outcome"],
                record["reusable_pattern"],
                *record["steps"],
            ]
        )
    )
    matches: list[tuple[float, str]] = []
    for skill in catalog.get("skills", ()):
        skill_terms = _terms(
            " ".join([str(skill.get("id", "")), *map(str, skill.get("tags", ()))])
        )
        union = process_terms | skill_terms
        score = len(process_terms & skill_terms) / len(union) if union else 0.0
        matches.append((score, str(skill["id"])))
    score, existing = max(
        matches, default=(0.0, ""), key=lambda item: (item[0], item[1])
    )
    decision = "improve_existing" if score >= 0.20 else "create_candidate"
    candidate_id = (
        existing
        if decision == "improve_existing"
        else _slug(record["reusable_pattern"])
    )
    decisions = [
        {
            "order": index,
            "decision": item["decision"],
            "reason": item["reason"],
            "alternatives": item["alternatives"],
        }
        for index, item in enumerate(record["decisions"])
    ]
    tools = [{"order": index, **item} for index, item in enumerate(record["tools"])]
    execution = [
        {"order": index, "step": step, "depends_on": [] if index == 0 else [index - 1]}
        for index, step in enumerate(record["steps"])
    ]
    return {
        "valid": True,
        "decision": decision,
        "candidate": {
            "id": candidate_id,
            "status": "candidate",
            "auto_activate": False,
            "source_process_sha256": process_hash,
            "goal": record["goal"],
            "procedure": record["steps"],
            "verification": record["verification"],
            "failure_recovery": record["failures"],
            "evidence": record["evidence"],
            "similarity": {
                "existing_skill": existing or None,
                "score": round(score, 6),
            },
        },
        "decision_graph": decisions,
        "tool_graph": tools,
        "execution_graph": execution,
        "activation": "requires_skill_admission_controller",
        "errors": [],
    }


def record_process_candidate(
    root: Path, project: Path, record: dict[str, Any], *, apply: bool = False
) -> dict[str, Any]:
    project = project.resolve()
    state_path = project / ".engineering-bootstrap/project-management/state.json"
    if not state_path.is_file():
        raise ValueError("project is not commissioned")
    result = compile_process_candidate(root, record)
    result = {**result, "apply": apply, "project": project.as_posix()}
    if not result["valid"] or not apply:
        return result
    digest = result["candidate"]["source_process_sha256"]
    relative = (
        Path(".engineering-bootstrap/project-management/process") / f"{digest}.json"
    )
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "1.0", "process": record, "compilation": result}
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise ValueError("process receipt hash collision or drift")
    target.write_text(rendered, encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    records = state.setdefault("evidence", {}).setdefault("process_records", [])
    path_text = relative.as_posix()
    if path_text not in records:
        records.append(path_text)
        records.sort()
    validate_instance(state, root / "contracts/project-management.schema.json")
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {**result, "receipt": path_text}
