"""Adapt an exact owned VS Code control probe into strict direct stage evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.assemble_operational_control_evidence import MATRIX, STAGES, current_source_manifest
except ModuleNotFoundError:
    from assemble_operational_control_evidence import MATRIX, STAGES, current_source_manifest


KINDS = {"direct_current_source_host_measurement", "direct_installed_host_measurement"}
STATES = {"present", "missing", "not_applicable"}
PROFILE_SPECS = (
    ("reversible_configuration_profile", "px.installed-operational-control-probe/1.0", False),
    ("studio_setup_profile", "px.installed-operational-control-probe/1.0", False),
    ("studio_candidate_save_profile", "px.installed-operational-control-probe/1.0", False),
    ("studio_lifecycle_profile", "px.installed-studio-lifecycle-profile/1.0", True),
    ("studio_revision_edit_profile", "px.installed-studio-revision-edit-profile/1.0", True),
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"receipt must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile_records(
    receipt: dict[str, Any], name: str, schema_version: str, nested: bool
) -> list[dict[str, Any]]:
    profile = receipt.get(name)
    if profile is None:
        return []
    if not isinstance(profile, dict) or profile.get("schema_version") != schema_version:
        raise ValueError(f"{name} schema is invalid")
    probe = profile.get("control_probe") if nested else profile
    if (
        not isinstance(probe, dict)
        or probe.get("schema_version") != "px.installed-operational-control-probe/1.0"
    ):
        raise ValueError(f"{name} control probe schema is invalid")
    records = probe.get("records")
    if not isinstance(records, list) or len(records) != probe.get("eligible_control_count"):
        raise ValueError(f"{name} denominator is incomplete")
    return records


def _merge_stage(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_state = str(left["state"])
    right_state = str(right["state"])
    if left_state == "not_applicable" or right_state == "not_applicable":
        if left_state != right_state:
            raise ValueError("duplicate profile stages conflict on applicability")
        return left
    if left_state == "present" and right_state == "present":
        details = [str(left["detail"]).strip(), str(right["detail"]).strip()]
        evidence = list(dict.fromkeys([*left["evidence"], *right["evidence"]]))
        return {
            "state": "present",
            "detail": " | ".join(dict.fromkeys(details)),
            "evidence": evidence,
        }
    if right_state == "present":
        return right
    return left


def build(root: Path, receipt_path: Path, evidence_kind: str) -> dict[str, Any]:
    root = root.resolve(strict=True)
    receipt_path = receipt_path.resolve(strict=True)
    if evidence_kind not in KINDS:
        raise ValueError("unsupported owned-host evidence kind")
    receipt = _load(receipt_path)
    if receipt.get("schema_version") != "px.operational-ui-walk/1.2":
        raise ValueError("owned-host walk receipt schema is invalid")
    if receipt.get("host_source_mismatch") or receipt.get("source_identity", {}).get("state") != "verified":
        raise ValueError("owned-host source identity is not verified")
    if receipt.get("host_errors"):
        raise ValueError("owned-host receipt contains host errors")
    probe = receipt.get("installed_control_probe")
    if not isinstance(probe, dict) or probe.get("schema_version") != "px.installed-operational-control-probe/1.0" or probe.get("bridge_instrumented") is not True:
        raise ValueError("expanded installed-control probe is missing or uninstrumented")
    records = probe.get("records")
    if not isinstance(records, list) or len(records) != probe.get("eligible_control_count"):
        raise ValueError("expanded probe denominator is incomplete")
    records = list(records)
    for name, schema_version, nested in PROFILE_SPECS:
        records.extend(_profile_records(receipt, name, schema_version, nested))
    matrix = _load(root / MATRIX)
    source_manifest = current_source_manifest(root, matrix)
    if receipt.get("source_identity", {}).get("control_source_manifest") != source_manifest:
        raise ValueError("owned-host control-source identity is absent or stale")
    requirements = {str(item["control_id"]): item for item in matrix["controls"]}
    adapted: dict[str, dict[str, Any]] = {}
    for record in records:
        control_id = str(record.get("control_id") or "")
        requirement = requirements.get(control_id)
        if requirement is None:
            raise ValueError(f"expanded probe references an unknown control: {control_id}")
        chain = record.get("interaction_chain")
        if not isinstance(chain, dict) or set(chain) != set(STAGES):
            raise ValueError(f"expanded probe lacks every stage: {control_id}")
        stages = {}
        for stage in STAGES:
            item = chain[stage]
            state = str(item.get("state") or "") if isinstance(item, dict) else ""
            if state not in STATES:
                raise ValueError(f"expanded probe has invalid state: {control_id}/{stage}")
            expected_na = requirement["stage_policy"][stage] == "not_applicable_with_evidence"
            if (state == "not_applicable") != expected_na:
                raise ValueError(f"expanded probe conflicts with proof matrix: {control_id}/{stage}")
            detail = str(item.get("detail") or "").strip()
            evidence = item.get("evidence")
            if state == "present" and (not detail or not isinstance(evidence, list) or not evidence):
                raise ValueError(f"expanded probe present stage lacks direct evidence: {control_id}/{stage}")
            stages[stage] = item
        candidate = {
            "control_id": control_id,
            "attempted": bool(record.get("attempted")),
            "rendered": bool(record.get("rendered")),
            "observed": bool(record.get("observed")),
            "stages": stages,
        }
        existing = adapted.get(control_id)
        if existing is None:
            adapted[control_id] = candidate
            continue
        existing["attempted"] = existing["attempted"] or candidate["attempted"]
        existing["rendered"] = existing["rendered"] or candidate["rendered"]
        existing["observed"] = existing["observed"] or candidate["observed"]
        existing["stages"] = {
            stage: _merge_stage(existing["stages"][stage], candidate["stages"][stage])
            for stage in STAGES
        }
    return {
        "schema_version": "px.operational-control-stage-evidence/1.0",
        "evidence_kind": evidence_kind,
        "authority": "Exact expanded control probe in an owned isolated VS Code host; missing stages remain missing.",
        "source": {"receipt": receipt_path.relative_to(root).as_posix(), "receipt_sha256": _sha256(receipt_path), "control_source_manifest": source_manifest},
        "records": list(adapted.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--evidence-kind", choices=sorted(KINDS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    receipt = (root / args.receipt).resolve(strict=True) if not args.receipt.is_absolute() else args.receipt.resolve(strict=True)
    result = build(root, receipt, args.evidence_kind)
    output = (root / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output.relative_to(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"output": str(output), "record_count": len(result["records"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
