"""Validate capability-mining dispositions and lazy skill orchestration maps."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib


ALLOWED_DISPOSITIONS = {"adopt", "merge", "defer", "reject", "duplicate", "reference_only"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_capability_assimilation(root: Path) -> dict[str, object]:
    admission = _json(root / "registry" / "capability_mining_admission.json")
    workflows = _json(root / "registry" / "skill_orchestrations.json")
    catalog = tomllib.loads((root / "registry" / "skill_catalog.toml").read_text(encoding="utf-8"))
    catalog_skills = {item["id"]: item for item in catalog.get("skills", ())}
    errors: list[str] = []

    scan_ids: set[str] = set()
    accounted_files = 0
    for scan in admission.get("scan_receipts", ()):
        scan_id = str(scan.get("id", ""))
        if not scan_id or scan_id in scan_ids:
            errors.append(f"invalid or duplicate scan receipt: {scan_id}")
        scan_ids.add(scan_id)
        if scan.get("complete") is not True or scan.get("error_count") != 0:
            errors.append(f"{scan_id}: incomplete source scan")
        if not isinstance(scan.get("files_accounted"), int) or scan.get("files_accounted", 0) < 1:
            errors.append(f"{scan_id}: invalid coverage denominator")
        else:
            # Nested passes intentionally overlap the broad snapshot.  Use the
            # largest complete denominator so coverage is never double-counted.
            accounted_files = max(accounted_files, scan["files_accounted"])
        digest = str(scan.get("report_sha256", ""))
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append(f"{scan_id}: invalid report hash")

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
            if catalog_skills.get(skill_id, {}).get("status") not in {"active", "admitted"}:
                errors.append(f"{workflow_id}: non-selectable skill {skill_id}")
            unknown_dependencies = set(step.get("depends_on", ())) - step_ids
            if unknown_dependencies:
                errors.append(f"{workflow_id}: unknown dependencies {sorted(unknown_dependencies)}")
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

    receipt = root / "evidence" / "capability-mining-receipt.json"
    if not receipt.is_file():
        errors.append("capability mining receipt is missing")
    else:
        value = _json(receipt)
        expected = hashlib.sha256((root / "registry" / "capability_mining_admission.json").read_bytes()).hexdigest()
        if value.get("admission_registry_sha256") != expected:
            errors.append("capability mining receipt does not bind the admission registry")
        if value.get("files_accounted") != accounted_files:
            errors.append("capability mining receipt coverage denominator drift")
    return {
        "valid": not errors,
        "scan_count": len(scan_ids),
        "files_accounted": accounted_files,
        "disposition_count": len(disposition_ids),
        "workflow_count": len(workflow_ids),
        "errors": errors,
    }
