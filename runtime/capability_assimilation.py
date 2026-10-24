"""Validate capability-mining dispositions and lazy skill orchestration maps."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib


ALLOWED_DISPOSITIONS = {
    "adopt",
    "merge",
    "defer",
    "reject",
    "duplicate",
    "reference_only",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_capability_assimilation(root: Path) -> dict[str, object]:
    from .json_io import read_bounded_bytes

    current_paths = [
        root / "registry/capability_mining_admission.json",
        root / "registry/skill_orchestrations.json",
        root / "registry/skill_catalog.toml",
    ]
    raw_inputs = {path.relative_to(root).as_posix(): read_bounded_bytes(path, max_bytes=8 * 1024 * 1024)
                  for path in current_paths}
    admission = json.loads(raw_inputs["registry/capability_mining_admission.json"])
    workflows = json.loads(raw_inputs["registry/skill_orchestrations.json"])
    catalog = tomllib.loads(raw_inputs["registry/skill_catalog.toml"].decode("utf-8"))
    catalog_skills = {item["id"]: item for item in catalog.get("skills", ())}
    errors: list[str] = []

    # Historical scan declarations are reference metadata, not current proof.
    # Measure and validate the current admission/workflow/catalog inputs below.
    historical_scans = admission.get("scan_receipts", ())
    input_sha256 = {name: hashlib.sha256(data).hexdigest() for name, data in raw_inputs.items()}
    if not admission.get("dispositions"):
        errors.append("current capability admission has no dispositions")
    if not workflows.get("workflows"):
        errors.append("current capability admission has no workflows")

    disposition_ids: set[str] = set()
    for record in admission.get("dispositions", ()):
        record_id = str(record.get("id", ""))
        if not record_id or record_id in disposition_ids:
            errors.append(f"invalid or duplicate disposition: {record_id}")
        disposition_ids.add(record_id)
        if record.get("disposition") not in ALLOWED_DISPOSITIONS:
            errors.append(f"{record_id}: invalid disposition")
        targets = record.get("targets", ())
        if not isinstance(targets, list) or not targets:
            errors.append(f"{record_id}: disposition has no target")
        for skill_id in targets:
            if skill_id not in catalog_skills:
                errors.append(f"{record_id}: unknown skill target {skill_id}")

    workflow_ids: set[str] = set()
    for workflow in workflows.get("workflows", ()):
        workflow_id = str(workflow.get("id", ""))
        if not workflow_id or workflow_id in workflow_ids:
            errors.append(f"invalid or duplicate skill orchestration: {workflow_id}")
        workflow_ids.add(workflow_id)
        steps = workflow.get("steps", ())
        step_ids = {str(step.get("id", "")) for step in steps}
        if "" in step_ids or len(step_ids) != len(steps):
            errors.append(f"{workflow_id}: invalid step identities")
        for step in steps:
            skill_id = str(step.get("skill", ""))
            if catalog_skills.get(skill_id, {}).get("status") not in {
                "active",
                "admitted",
            }:
                errors.append(f"{workflow_id}: non-selectable skill {skill_id}")
            unknown_dependencies = set(step.get("depends_on", ())) - step_ids
            if unknown_dependencies:
                errors.append(
                    f"{workflow_id}: unknown dependencies {sorted(unknown_dependencies)}"
                )
        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {str(step["id"]): step for step in steps if step.get("id")}

        def visit(step_id: str) -> None:
            if step_id in visiting:
                errors.append(f"{workflow_id}: cycle includes {step_id}")
                return
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in sorted(by_id[step_id].get("depends_on", ())):
                if dependency in by_id:
                    visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in sorted(by_id):
            visit(step_id)

    # Evidence is produced by this fresh validation and its governed execution
    # receipt, rather than requiring a receipt from a previous mining campaign.
    return {
        "valid": not errors,
        "scan_count": 1,
        "validation_basis": "current_implementation",
        "input_sha256": input_sha256,
        "historical_scan_count": len(historical_scans),
        "historical_scans_verified": False,
        "files_accounted": len(current_paths),
        "disposition_count": len(disposition_ids),
        "workflow_count": len(workflow_ids),
        "errors": errors,
    }
