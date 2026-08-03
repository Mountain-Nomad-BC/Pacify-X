"""Validate operational ownership distilled from external source packs."""
from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any


def validate_source_coverage(root: Path) -> dict[str, Any]:
    path = root / "registry" / "source_requirement_coverage.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    allowed = set(record.get("allowed_states", ()))
    errors: list[str] = []
    ids: set[str] = set()
    catalog = tomllib.loads((root / "registry" / "skill_catalog.toml").read_text(encoding="utf-8"))
    skills = {item["id"]: item.get("status") for item in catalog.get("skills", ())}
    for control in record.get("controls", ()):
        control_id = str(control.get("id", ""))
        if not control_id or control_id in ids:
            errors.append(f"invalid or duplicate coverage id: {control_id}")
        ids.add(control_id)
        state = control.get("state")
        if state not in allowed:
            errors.append(f"{control_id}: invalid state {state}")
        if control.get("release_role") == "required" and state not in {"operational", "operational_bounded"}:
            errors.append(f"{control_id}: required control is not operational")
        for field in ("owners", "contracts", "tests"):
            for relative in control.get(field, ()):
                if not (root / str(relative)).is_file():
                    errors.append(f"{control_id}: missing {field[:-1]} {relative}")
        for skill_id in control.get("skills", ()):
            status = skills.get(skill_id)
            if status is None:
                errors.append(f"{control_id}: unknown skill {skill_id}")
            if state in {"operational", "operational_bounded"} and status not in {"active", "admitted"}:
                errors.append(f"{control_id}: operational control uses non-admitted skill {skill_id}")
    return {"valid": not errors, "control_count": len(ids), "errors": errors}
