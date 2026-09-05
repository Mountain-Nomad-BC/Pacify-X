"""Build and validate a compact semantic index without runtime skill hydration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib

from .capability_semantics import (
    build_capability_semantic_profile,
    validate_capability_semantic_profile,
)


DESCRIPTION = re.compile(r"(?m)^description:\s*[\"']?(.*?)[\"']?\s*$")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _description_text(text: str) -> str:
    match = DESCRIPTION.search(text)
    return match.group(1).strip() if match else ""


def build_semantic_index(
    root: Path, *, overlays: dict[str, bytes] | None = None
) -> dict[str, object]:
    root = root.resolve()
    overlay_bytes = dict(overlays or {})

    def read_bytes(path: Path) -> bytes | None:
        relative = path.relative_to(root).as_posix()
        if relative in overlay_bytes:
            return overlay_bytes[relative]
        return path.read_bytes() if path.is_file() else None

    def read_json(path: Path) -> dict:
        data = read_bytes(path)
        return json.loads(data.decode("utf-8")) if data is not None else {}

    catalog_data = read_bytes(root / "registry" / "skill_catalog.toml")
    if catalog_data is None:
        raise FileNotFoundError("skill catalog is unavailable")
    catalog = tomllib.loads(catalog_data.decode("utf-8"))
    workflow_path = root / "registry" / "skill_orchestrations.json"
    workflow_membership: dict[str, set[str]] = {}
    alias_path = root / "registry" / "capability_aliases.json"
    aliases_by_owner: dict[str, set[str]] = {}
    if alias_path.is_file():
        for alias in _load_json(alias_path).get("records", ()):
            aliases_by_owner.setdefault(str(alias.get("owner", "")), set()).add(
                str(alias.get("alias", ""))
            )
    if workflow_path.is_file():
        for workflow in _load_json(workflow_path).get("workflows", ()):
            workflow_id = str(workflow.get("id", ""))
            for step in workflow.get("steps", ()):
                workflow_membership.setdefault(str(step.get("skill", "")), set()).add(
                    workflow_id
                )
    records: list[dict[str, object]] = []
    for item in catalog.get("skills", ()):
        skill_id = str(item["id"])
        body = root / str(item["body"])
        contract_path = root / str(item["contract"])
        contract = read_json(contract_path)
        body_data = read_bytes(body)
        contract_data = read_bytes(contract_path)
        tags = sorted({str(value) for value in item.get("tags", ())})
        resources = [str(value) for value in contract.get("resources", ())]
        profile = build_capability_semantic_profile(
            {
                **item,
                "aliases": sorted(aliases_by_owner.get(skill_id, set())),
                "triggers": contract.get("triggers", ()),
            },
            contract,
            maturity=None,
        )
        semantic_profile = profile.as_dict()
        profile_revision = hashlib.sha256(
            json.dumps(
                semantic_profile, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        records.append(
            {
                "id": skill_id,
                "kind": "skill",
                "status": str(item.get("status", "candidate")),
                "description": _description_text(body_data.decode("utf-8"))
                if body_data is not None
                else "",
                "domains": list(profile.domains),
                "intents": list(profile.positive_intents),
                "negative_intents": list(profile.negative_intents),
                "concepts": sorted(
                    set((*tags, *skill_id.split("-"), *profile.domains))
                ),
                "synonyms": list(profile.synonyms),
                "tools": sorted({Path(value).stem for value in resources if value}),
                "relations": sorted(workflow_membership.get(skill_id, ())),
                "semantic_profile": semantic_profile,
                "profile_revision": profile_revision,
                "contract_revision": hashlib.sha256(contract_data).hexdigest()
                if contract_data is not None
                else "",
                "body_sha256": hashlib.sha256(body_data).hexdigest()
                if body_data is not None
                else "",
            }
        )
    records.sort(key=lambda value: str(value["id"]))
    revision = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "1.0",
        "loading_rule": "metadata_only",
        "revision": revision,
        "record_count": len(records),
        "records": records,
    }


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
    seen: set[str] = set()
    for record in expected["records"]:
        capability_id = str(record.get("id") or "")
        if capability_id in seen:
            errors.append(f"duplicate semantic identity: {capability_id}")
        seen.add(capability_id)
        profile = record.get("semantic_profile")
        report = (
            validate_capability_semantic_profile(profile)
            if isinstance(profile, dict)
            else {"valid": False, "errors": ["profile missing"]}
        )
        if not report["valid"]:
            errors.append(f"{capability_id}: invalid semantic profile: {report['errors']}")
        if record.get("status") == "active" and not record.get("intents"):
            errors.append(f"{capability_id}: active routable skill has empty positive intent")
        calculated = hashlib.sha256(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if record.get("profile_revision") != calculated:
            errors.append(f"{capability_id}: stale semantic profile revision")
    return {
        "valid": not errors,
        "record_count": expected["record_count"],
        "revision": expected["revision"],
        "errors": errors,
    }
