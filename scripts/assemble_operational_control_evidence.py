"""Assemble exact direct control-stage receipts without broad-evidence promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MATRIX = Path("registry/operational_control_proof_matrix.json")
INVENTORY = Path("registry/operational_surface_inventory.json")
STAGES = (
    "open_load", "display", "user_edit_action", "input_validation",
    "authorization", "backend_dispatch", "runtime_effect", "progress_reporting",
    "result_acknowledgement", "persistence", "reload_reopen", "failure_handling",
    "recovery_rollback",
)
DIRECT_KINDS = {
    "contained_browser_measurement", "direct_installed_host_measurement",
    "direct_disposable_runtime_measurement", "direct_durability_measurement",
    "direct_restart_measurement", "direct_fault_injection_measurement",
    "direct_current_source_host_measurement",
}
REQUIRED_STATES = {"present", "not_applicable"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"receipt must be an object: {path}")
    return value


def _source_path(reference: str) -> str:
    # Canonical references use the first colon to introduce either numeric
    # line coordinates (``file.py:12-18``) or a semantic document anchor
    # (``package.json:contributes.commands``).  Matrix paths are repository-
    # relative, so a drive-letter colon is not valid here.
    path, separator, _anchor = reference.partition(":")
    if not separator or not path:
        return reference
    return path


def current_source_manifest(root: Path, matrix: dict[str, Any]) -> dict[str, Any]:
    paths = sorted({_source_path(str(ref)) for item in matrix["controls"] for ref in item["source_refs"]})
    files = []
    for relative in paths:
        target = (root / relative).resolve(strict=True)
        target.relative_to(root)
        data = target.read_bytes()
        files.append({"path": relative.replace("\\", "/"), "sha256": _digest(data), "bytes": len(data)})
    body = {"schema_version": "px.current-source-control-manifest/2.0", "files": files}
    return {**body, "source_sha256": _digest(_canonical(body))}


def _require_source_binding(receipt: dict[str, Any], current: dict[str, Any]) -> None:
    source = receipt.get("source")
    bound = source.get("control_source_manifest") if isinstance(source, dict) else None
    if bound != current:
        raise ValueError("evidence receipt control-source identity is absent or stale")


def _blank(requirement: dict[str, Any], matrix_reference: str) -> dict[str, dict[str, Any]]:
    result = {}
    for stage in STAGES:
        if requirement["stage_policy"][stage] == "not_applicable_with_evidence":
            result[stage] = {
                "state": "not_applicable",
                "detail": f"Canonical proof matrix marks {stage} not applicable.",
                "evidence": [f"{matrix_reference}#control={requirement['control_id']}&stage={stage}"],
            }
        else:
            result[stage] = {"state": "missing", "detail": f"No direct evidence assembled for required stage {stage}.", "evidence": []}
    return result


def _merge_stage(chain: dict[str, dict[str, Any]], requirement: dict[str, Any], stage: str, item: dict[str, Any], reference: str) -> None:
    state = str(item.get("state") or "")
    if state not in {"present", "not_applicable", "missing"}:
        raise ValueError(f"invalid stage state for {requirement['control_id']}/{stage}")
    policy = requirement["stage_policy"][stage]
    if state == "not_applicable" and policy != "not_applicable_with_evidence":
        raise ValueError(f"required stage cannot be declared not applicable: {requirement['control_id']}/{stage}")
    if state == "present" and policy == "not_applicable_with_evidence":
        raise ValueError(f"not-applicable stage cannot be promoted to present: {requirement['control_id']}/{stage}")
    if state == "present":
        detail = str(item.get("detail") or "").strip()
        evidence = item.get("evidence")
        if not detail or not isinstance(evidence, list) or not evidence or any(not str(value).strip() for value in evidence):
            raise ValueError(f"present stage lacks direct detail/evidence: {requirement['control_id']}/{stage}")
        chain[stage] = {
            "state": "present", "detail": detail,
            "evidence": [f"{reference}#control={requirement['control_id']}&stage={stage}&evidence={index}" for index, _ in enumerate(evidence)],
        }


def _ui_records(path: Path, receipt: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if receipt.get("schema_version") != "px.exhaustive-operational-control-walk/1.0":
        raise ValueError("contained UI receipt schema is invalid")
    records = receipt.get("records")
    if not isinstance(records, list):
        raise ValueError("contained UI receipt records are missing")
    adapted = []
    for record in records:
        chain = record.get("interaction_chain")
        if not isinstance(chain, dict) or set(chain) != set(STAGES):
            raise ValueError("contained UI record lacks the complete stage denominator")
        adapted.append({
            "control_id": record.get("control_id"), "attempted": bool(record.get("attempted")),
            "rendered": bool(record.get("rendered")), "observed": bool(record.get("observed")),
            "stages": chain,
        })
    return "contained_browser_measurement", adapted


def _direct_records(receipt: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if receipt.get("schema_version") != "px.operational-control-stage-evidence/1.0":
        raise ValueError("direct stage receipt schema is invalid")
    kind = str(receipt.get("evidence_kind") or "")
    if kind not in DIRECT_KINDS - {"contained_browser_measurement"}:
        raise ValueError("contextual or unsupported evidence kind cannot satisfy control stages")
    records = receipt.get("records")
    if not isinstance(records, list):
        raise ValueError("direct stage receipt records are missing")
    return kind, records


def assemble(root: Path, ui_path: Path, stage_paths: list[Path]) -> dict[str, Any]:
    root = root.resolve(strict=True)
    matrix_path = root / MATRIX
    inventory_path = root / INVENTORY
    matrix = _load(matrix_path)
    inventory = _load(inventory_path)
    requirements = {str(item["control_id"]): item for item in matrix["controls"]}
    if len(requirements) != matrix["control_count"]:
        raise ValueError("proof matrix control denominator is not unique")
    source = current_source_manifest(root, matrix)
    assembled = {
        control_id: {
            "control_id": control_id, "surface_id": requirement["surface_id"], "kind": requirement["kind"],
            "evidence_mode": requirement["evidence_mode"], "attempted": False, "rendered": False, "observed": False,
            "chain": _blank(requirement, MATRIX.as_posix()), "authorities": [],
        }
        for control_id, requirement in requirements.items()
    }
    ui_receipt = _load(ui_path)
    _require_source_binding(ui_receipt, source)
    inputs = [(ui_path, *_ui_records(ui_path, ui_receipt))]
    for path in stage_paths:
        receipt = _load(path)
        _require_source_binding(receipt, source)
        inputs.append((path, *_direct_records(receipt)))
    for path, kind, records in inputs:
        reference = path.resolve(strict=True).relative_to(root).as_posix()
        seen: set[str] = set()
        for record in records:
            control_id = str(record.get("control_id") or "")
            if control_id in seen:
                raise ValueError(f"duplicate control in one evidence receipt: {control_id}")
            seen.add(control_id)
            if control_id not in requirements:
                raise ValueError(f"evidence references a control outside the denominator: {control_id}")
            stages = record.get("stages")
            if not isinstance(stages, dict) or set(stages) != set(STAGES):
                raise ValueError(f"direct evidence lacks every stage: {control_id}")
            target = assembled[control_id]
            target["attempted"] = target["attempted"] or bool(record.get("attempted"))
            target["rendered"] = target["rendered"] or bool(record.get("rendered"))
            target["observed"] = target["observed"] or bool(record.get("observed"))
            target["authorities"].append({"kind": kind, "reference": reference, "sha256": _digest(path.read_bytes())})
            for stage in STAGES:
                _merge_stage(target["chain"], requirements[control_id], stage, stages[stage], reference)
    records = []
    for control_id in sorted(assembled):
        item = assembled[control_id]
        complete = all(value["state"] in REQUIRED_STATES for value in item["chain"].values())
        stages = [
            {"stage": stage, "status": "observed" if value["state"] == "present" else value["state"], "evidence": value["detail"], "references": value["evidence"]}
            for stage, value in item["chain"].items()
        ]
        records.append({
            "control_id": control_id, "surface_id": item["surface_id"], "kind": item["kind"],
            "evidence_mode": item["evidence_mode"], "rendered": item["rendered"], "observed": item["observed"],
            "attempted": item["attempted"], "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "authority": "multiple exact direct control-stage receipts" if len(item["authorities"]) > 1 else (item["authorities"][0]["kind"] if item["authorities"] else "no direct evidence"),
            "terminal_disposition": "interaction_complete" if complete and (item["attempted"] or item["observed"]) else "observed_only",
            "stages": stages, "authorities": item["authorities"],
        })
    complete_count = sum(record["terminal_disposition"] == "interaction_complete" for record in records)
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "px.assembled-operational-control-evidence/1.0", "observed_at": observed_at,
        "authority": "Exact direct evidence assembly; incomplete stages remain gaps.", "host_source_mismatch": False,
        "status_truth": {"source_identity": {"state": "verified", **source}},
        "control_chains": {
            "schema_version": "px.operational-ui-control-chain/1.0", "chain_stages": list(STAGES),
            "inventory": {"path": INVENTORY.as_posix(), "sha256": source["source_sha256"], "schema_version": inventory["schema_version"], "inventory_id": inventory["inventory_id"], "surface_count": len(inventory["surfaces"]), "control_count": len(records)},
            "aggregates": {
                "control_count": len(records),
                "attempted_control_count": sum(record["attempted"] for record in records),
                "observed_control_count": sum(record["observed"] for record in records),
                "complete_interaction_chains": complete_count,
            },
            "controls": records,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--ui-receipt", type=Path, required=True)
    parser.add_argument("--stage-receipt", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    ui = (root / args.ui_receipt).resolve(strict=True) if not args.ui_receipt.is_absolute() else args.ui_receipt.resolve(strict=True)
    stages = [(root / item).resolve(strict=True) if not item.is_absolute() else item.resolve(strict=True) for item in args.stage_receipt]
    value = assemble(root, ui, stages)
    output = (root / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output.relative_to(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"output": str(output), **value["control_chains"]["aggregates"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
