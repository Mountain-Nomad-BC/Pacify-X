"""Build and validate a compact semantic index without runtime skill hydration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib


DESCRIPTION = re.compile(r"(?m)^description:\s*[\"']?(.*?)[\"']?\s*$")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _description(path: Path) -> str:
    match = DESCRIPTION.search(path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else ""


def build_semantic_index(root: Path) -> dict[str, object]:
    root = root.resolve()
    catalog = tomllib.loads((root / "registry" / "skill_catalog.toml").read_text(encoding="utf-8"))
    workflow_path = root / "registry" / "skill_orchestrations.json"
    workflow_membership: dict[str, set[str]] = {}
    alias_path = root / "registry" / "capability_aliases.json"
    aliases_by_owner: dict[str, set[str]] = {}
    if alias_path.is_file():
        for alias in _load_json(alias_path).get("records", ()):
            aliases_by_owner.setdefault(str(alias.get("owner", "")), set()).add(str(alias.get("alias", "")))
    if workflow_path.is_file():
        for workflow in _load_json(workflow_path).get("workflows", ()):
            workflow_id = str(workflow.get("id", ""))
            for step in workflow.get("steps", ()):
                workflow_membership.setdefault(str(step.get("skill", "")), set()).add(workflow_id)
    records: list[dict[str, object]] = []
    for item in catalog.get("skills", ()):
        skill_id = str(item["id"])
        body = root / str(item["body"])
        contract_path = root / str(item["contract"])
        contract = _load_json(contract_path) if contract_path.is_file() else {}
        tags = sorted({str(value) for value in item.get("tags", ())})
        provides = [str(value) for value in contract.get("provides", ())]
        resources = [str(value) for value in contract.get("resources", ())]
        records.append({
            "id": skill_id,
            "kind": "skill",
            "status": str(item.get("status", "candidate")),
            "description": _description(body) if body.is_file() else "",
            "domains": tags,
            "intents": sorted(set(provides)),
            "concepts": sorted(set((*tags, *skill_id.split("-")))),
            "synonyms": sorted({skill_id.replace("-", " "), *aliases_by_owner.get(skill_id, set())}),
            "tools": sorted({Path(value).stem for value in resources if value}),
            "relations": sorted(workflow_membership.get(skill_id, ())),
            "body_sha256": hashlib.sha256(body.read_bytes()).hexdigest() if body.is_file() else "",
        })
    records.sort(key=lambda value: str(value["id"]))
    revision = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"schema_version": "1.0", "loading_rule": "metadata_only", "revision": revision, "record_count": len(records), "records": records}


def load_semantic_index(root: Path) -> dict[str, object]:
    return _load_json(root.resolve() / "registry" / "semantic_capability_index.json")


def validate_semantic_index(root: Path) -> dict[str, object]:
    expected = build_semantic_index(root)
    try:
        actual = load_semantic_index(root)
    except (OSError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [f"semantic index unavailable: {error}"]}
    errors: list[str] = []
    alias_path = root.resolve() / "registry" / "capability_aliases.json"
    if alias_path.is_file():
        aliases = _load_json(alias_path).get("records", ())
        owners = {str(record["id"]) for record in expected["records"]}
        seen_aliases: dict[str, str] = {}
        for record in aliases:
            alias = str(record.get("alias", "")).strip()
            owner = str(record.get("owner", ""))
            if not alias:
                errors.append("capability alias must be nonempty")
            if owner not in owners:
                errors.append(f"capability alias {alias}: unknown owner {owner}")
            if alias in seen_aliases and seen_aliases[alias] != owner:
                errors.append(f"capability alias {alias}: conflicting owners")
            seen_aliases[alias] = owner
    if actual != expected:
        errors.append("semantic capability index is stale or non-deterministic")
    return {"valid": not errors, "record_count": expected["record_count"], "revision": expected["revision"], "errors": errors}
