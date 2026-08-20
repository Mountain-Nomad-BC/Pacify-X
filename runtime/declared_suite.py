"""Deterministic, read-only runtime for reconstructed declared-suite operations."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


def _load(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _stable_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def list_outcomes(
    root: Path, *, kind: str | None = None, owner: str | None = None
) -> dict:
    registry = _load(root, "registry/declared_outcome_owners.json")
    records = registry["records"]
    if kind:
        records = [record for record in records if record["kind"] == kind]
    if owner:
        records = [record for record in records if record["owner"] == owner]
    return {
        "valid": True,
        "metadata_only": True,
        "count": len(records),
        "records": records,
    }


def describe_outcome(root: Path, kind: str, outcome_id: str) -> dict:
    owners = _load(root, "registry/declared_outcome_owners.json")["records"]
    record = next(
        (
            item
            for item in owners
            if item["kind"] == kind and item["source_id"] == outcome_id
        ),
        None,
    )
    if record is None:
        return {
            "valid": False,
            "errors": [f"unknown declared outcome: {kind}/{outcome_id}"],
        }
    if kind == "orchestration":
        workflows = _load(root, "orchestration/workflows/declared-suite.yaml")[
            "workflows"
        ]
        contract = next(item for item in workflows if item["id"] == outcome_id)
    else:
        name = (
            "capability-contracts.json" if kind == "skill" else "script-contracts.json"
        )
        contracts = _load(root, f".px/skills/{record['owner']}/references/{name}")[
            "contracts"
        ]
        contract = next(item for item in contracts if item["id"] == outcome_id)
    return {
        "valid": True,
        "metadata_only": False,
        "owner": record["owner"],
        "contract": contract,
    }


def plan_outcome(
    root: Path, kind: str, outcome_id: str, payload: Mapping[str, Any]
) -> dict:
    described = describe_outcome(root, kind, outcome_id)
    if not described["valid"]:
        return described
    target = payload.get("target")
    constraints = payload.get("constraints")
    if target in (None, "", []) or not isinstance(constraints, Mapping):
        return {
            "valid": False,
            "errors": ["target and object-valued constraints are required"],
            "outcome": outcome_id,
        }
    contract = described["contract"]
    procedure = contract.get("procedure") or [step["id"] for step in contract["steps"]]
    return {
        "valid": True,
        "dry_run": True,
        "kind": kind,
        "outcome": outcome_id,
        "owner": described["owner"],
        "target": target,
        "constraints": dict(constraints),
        "ordered_steps": procedure,
        "failure_policy": contract["failure_policy"],
        "recovery": contract.get("recovery")
        or contract.get("rollback_or_compensation"),
        "evidence_required": contract.get("evidence")
        or contract.get("evidence_outputs"),
        "request_sha256": _stable_hash(payload),
    }


def _walk_inventory(target: Path, maximum_files: int) -> list[dict]:
    if not target.exists():
        raise ValueError(f"target does not exist: {target}")
    paths = (
        [target]
        if target.is_file()
        else sorted(path for path in target.rglob("*") if path.is_file())
    )
    if len(paths) > maximum_files:
        raise ValueError(f"file budget exceeded: {len(paths)} > {maximum_files}")
    records = []
    base = target.parent if target.is_file() else target
    for path in paths:
        data = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(base).as_posix(),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return records


def _compare(payload: Mapping[str, Any]) -> dict:
    baseline = payload.get("baseline")
    candidate = payload.get("candidate")
    if baseline is None or candidate is None:
        raise ValueError("comparison operations require baseline and candidate")
    if isinstance(baseline, (int, float)) and isinstance(candidate, (int, float)):
        delta = candidate - baseline
        relative = None if baseline == 0 else delta / abs(baseline)
        return {
            "baseline": baseline,
            "candidate": candidate,
            "delta": delta,
            "relative_delta": relative,
        }
    left = json.dumps(baseline, sort_keys=True)
    right = json.dumps(candidate, sort_keys=True)
    return {
        "equal": left == right,
        "baseline_sha256": _stable_hash(baseline),
        "candidate_sha256": _stable_hash(candidate),
    }


def _rank(payload: Mapping[str, Any]) -> dict:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("ranking operations require a nonempty candidates list")
    weights = payload.get("weights", {})
    if not isinstance(weights, Mapping):
        raise ValueError("weights must be an object")
    ranked = []
    for index, item in enumerate(candidates):
        if not isinstance(item, Mapping):
            raise ValueError("every candidate must be an object")
        metrics = item.get("metrics", {})
        score = sum(
            float(metrics.get(name, 0)) * float(weight)
            for name, weight in weights.items()
        )
        ranked.append(
            {
                "id": item.get("id", f"candidate-{index}"),
                "score": score,
                "input_index": index,
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["id"], item["input_index"]))
    return {"ranked": ranked, "winner": ranked[0]["id"]}


def _scan(payload: Mapping[str, Any]) -> dict:
    text = payload.get("text")
    patterns = payload.get("patterns")
    if not isinstance(text, str) or not isinstance(patterns, list):
        raise ValueError("scan operations require text and a patterns list")
    matches = []
    for pattern in patterns:
        if not isinstance(pattern, str) or len(pattern) > 256:
            raise ValueError("patterns must be strings no longer than 256 characters")
        for match in re.finditer(re.escape(pattern), text, flags=re.IGNORECASE):
            matches.append(
                {"pattern": pattern, "start": match.start(), "end": match.end()}
            )
    return {"match_count": len(matches), "matches": matches}


def _validate(payload: Mapping[str, Any]) -> dict:
    record = payload.get("record")
    required = payload.get("required", [])
    allowed = payload.get("allowed")
    if not isinstance(record, Mapping) or not isinstance(required, list):
        raise ValueError("validation operations require record and required fields")
    missing = sorted(str(name) for name in required if name not in record)
    unknown = sorted(
        str(name)
        for name in record
        if isinstance(allowed, list) and name not in allowed
    )
    return {
        "accepted": not missing and not unknown,
        "missing": missing,
        "unknown": unknown,
    }


def _generate_cases(payload: Mapping[str, Any]) -> dict:
    seed = payload.get("seed")
    if seed is None:
        raise ValueError("case-generation operations require seed")
    cases = [seed, None, {}, [], "", 0, {"unexpected": True}]
    unique = []
    seen = set()
    for case in cases:
        fingerprint = _stable_hash(case)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append({"case": case, "sha256": fingerprint})
    return {"case_count": len(unique), "cases": unique}


def run_script_outcome(root: Path, outcome_id: str, payload: Mapping[str, Any]) -> dict:
    described = describe_outcome(root, "script", outcome_id)
    if not described["valid"]:
        return described
    plan = plan_outcome(root, "script", outcome_id, payload)
    if not plan["valid"]:
        return plan
    words = set(outcome_id.split("-"))
    try:
        if words & {
            "map",
            "mapper",
            "index",
            "inventory",
            "bom",
            "manifest",
            "archive",
            "provenance",
        }:
            target = Path(str(payload["target"])).resolve()
            result = {
                "files": _walk_inventory(
                    target, int(payload.get("maximum_files", 10000))
                )
            }
        elif words & {"compare", "differential", "regression"}:
            result = _compare(payload)
        elif words & {
            "route",
            "router",
            "rank",
            "planner",
            "calibrator",
            "scorer",
            "budget",
        }:
            result = _rank(payload)
        elif words & {"scan", "scanner", "secret", "injection", "contamination"}:
            result = _scan(payload)
        elif words & {"validate", "validator", "guard", "enforcer", "policy"}:
            result = _validate(payload)
        elif words & {"fuzz", "mutation", "metamorphic", "scenario", "property"}:
            result = _generate_cases(payload)
        else:
            result = {
                "normalized_record": dict(sorted(payload.items())),
                "record_sha256": _stable_hash(payload),
            }
    except (OSError, TypeError, ValueError) as error:
        return {
            "valid": False,
            "outcome": outcome_id,
            "errors": [str(error)],
            "request_sha256": plan.get("request_sha256"),
        }
    return {
        "valid": True,
        "outcome": outcome_id,
        "owner": described["owner"],
        "read_only": True,
        "result": result,
        "result_sha256": _stable_hash(result),
        "plan": plan,
    }


def validate_declared_suite(root: Path) -> dict:
    owners = _load(root, "registry/declared_outcome_owners.json")
    workflows = _load(root, "orchestration/workflows/declared-suite.yaml")
    errors = []
    seen = set()
    for record in owners["records"]:
        key = (record["kind"], record["source_id"])
        if key in seen:
            errors.append(f"duplicate outcome: {key}")
        seen.add(key)
        described = describe_outcome(root, *key)
        if not described["valid"]:
            errors.extend(described["errors"])
    if owners["record_count"] != 257 or len(seen) != 257:
        errors.append(
            f"owner denominator mismatch: declared={owners['record_count']} unique={len(seen)}"
        )
    if workflows["workflow_count"] != 62:
        errors.append(f"workflow denominator mismatch: {workflows['workflow_count']}")
    return {
        "valid": not errors,
        "outcomes": len(seen),
        "workflows": workflows["workflow_count"],
        "errors": errors,
    }
