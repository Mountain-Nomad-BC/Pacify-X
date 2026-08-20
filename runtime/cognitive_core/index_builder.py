"""Build one deterministic metadata-only map across PACIFY-X cognitive assets.

The map deliberately indexes metadata and load paths, not full bodies.  Retrieval can
therefore search the whole capability surface and hydrate only the winning records.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable, Mapping

from .common import normalize_text, stable_hash

_DESCRIPTION = re.compile(r"(?m)^description:\s*[\"']?(.*?)[\"']?\s*$")
_INDEX_KIND = {
    "capability-index.json": "capability",
    "capabilities-index.json": "capability",
    "scripts-index.json": "script",
    "workflow-index.json": "workflow",
    "orchestration-index.json": "workflow",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return value


def _read_jsonish(path: Path) -> dict[str, Any] | None:
    try:
        return _json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _description(path: Path) -> str:
    try:
        match = _DESCRIPTION.search(path.read_text(encoding="utf-8"))
    except OSError:
        return ""
    return match.group(1).strip() if match else ""


def _record_key(kind: str, identifier: str) -> str:
    return f"{kind}:{identifier}"


def _strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [str(key) for key in value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    return [str(value)]


def _first_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _add(records: dict[str, dict[str, Any]], record: Mapping[str, Any]) -> None:
    identifier = str(record.get("id", "")).strip()
    kind = str(record.get("kind", "")).strip()
    if not identifier or not kind:
        return
    key = _record_key(kind, identifier)
    normalized = {
        "key": key,
        "id": identifier,
        "kind": kind,
        "title": str(record.get("title", identifier.replace("-", " "))),
        "summary": str(record.get("summary", "")),
        "owner": str(record.get("owner", "")),
        "status": str(record.get("status", "active")),
        "domain": str(record.get("domain", "")),
        "aliases": sorted(
            {item.strip() for item in _strings(record.get("aliases")) if item.strip()}
        ),
        "triggers": sorted(
            {item.strip() for item in _strings(record.get("triggers")) if item.strip()}
        ),
        "concepts": sorted(
            {item.strip() for item in _strings(record.get("concepts")) if item.strip()}
        ),
        "inputs": sorted(
            {item.strip() for item in _strings(record.get("inputs")) if item.strip()}
        ),
        "outputs": sorted(
            {item.strip() for item in _strings(record.get("outputs")) if item.strip()}
        ),
        "dependencies": sorted(
            {
                item.strip()
                for item in _strings(record.get("dependencies"))
                if item.strip()
            }
        ),
        "formula_refs": sorted(
            {
                item.strip()
                for item in _strings(record.get("formula_refs"))
                if item.strip()
            }
        ),
        "relations": sorted(
            {item.strip() for item in _strings(record.get("relations")) if item.strip()}
        ),
        "path": str(record.get("path", "")),
        "implementation_path": str(record.get("implementation_path", "")),
        "source_sha256": str(record.get("source_sha256", "")),
        "risk": str(record.get("risk", "R1")),
        "loading_rule": "metadata_only_until_selected",
    }
    existing = records.get(key)
    if existing is None:
        records[key] = normalized
        return
    for field in (
        "aliases",
        "triggers",
        "concepts",
        "inputs",
        "outputs",
        "dependencies",
        "formula_refs",
        "relations",
    ):
        existing[field] = sorted(set(existing[field]) | set(normalized[field]))
    for field in (
        "summary",
        "owner",
        "domain",
        "path",
        "implementation_path",
        "source_sha256",
    ):
        if not existing.get(field) and normalized.get(field):
            existing[field] = normalized[field]


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in (
        "records",
        "workflows",
        "orchestrations",
        "capabilities",
        "scripts",
        "formulas",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _index_nested_assets(
    root: Path,
    records: dict[str, dict[str, Any]],
    edges: set[tuple[str, str, str]],
    catalog_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    normalized_leaf: dict[str, str] = {}
    references = root / ".px" / "skills"
    for index_path in sorted(references.glob("*/references/*index*.json")):
        kind = _INDEX_KIND.get(index_path.name)
        if kind is None:
            continue
        payload = _read_jsonish(index_path) or {}
        owner = index_path.relative_to(root).parts[2]
        owner_status = str(catalog_by_id.get(owner, {}).get("status", "active"))
        for item in _rows(payload):
            identifier = str(item.get("id", "")).strip()
            if not identifier:
                continue
            relative_path = str(item.get("path", ""))
            body_path = root / relative_path
            full = _read_jsonish(body_path) or {}
            title = _first_text(
                full.get("title"), full.get("name"), identifier.replace("-", " ")
            )
            summary = _first_text(
                full.get("summary"),
                full.get("description"),
                item.get("description"),
                full.get("trigger"),
                full.get("when_to_use"),
                item.get("trigger"),
                item.get("when_to_use"),
            )
            trigger_values = [
                full.get("when_to_use"),
                full.get("trigger"),
                item.get("when_to_use"),
                item.get("trigger"),
                full.get("use_when"),
                item.get("use_when"),
            ]
            dependencies = _strings(full.get("dependencies")) + _strings(
                full.get("composed_with")
            )
            implementation = _first_text(
                full.get("implementation_target"),
                full.get("authoritative_implementation"),
                full.get("authoritative_source"),
            )
            _add(
                records,
                {
                    "id": identifier,
                    "kind": kind,
                    "title": title,
                    "summary": summary,
                    "owner": owner,
                    "status": owner_status,
                    "domain": _first_text(full.get("domain"), item.get("domain"), kind),
                    "aliases": [identifier.replace("-", " "), title],
                    "triggers": trigger_values,
                    "concepts": [
                        identifier.replace("-", " "),
                        *_strings(full.get("failure_modes")),
                        *_strings(full.get("invariants")),
                    ],
                    "inputs": full.get("inputs", ()),
                    "outputs": full.get("outputs", ()),
                    "dependencies": dependencies,
                    "formula_refs": full.get("formula_refs", ()),
                    "relations": full.get("procedure", ()),
                    "path": relative_path,
                    "implementation_path": implementation,
                    "source_sha256": item.get(
                        "sha256",
                        item.get("source_sha256", full.get("source_body_sha256", "")),
                    ),
                    "risk": _first_text(full.get("risk"), "R1"),
                },
            )
            leaf_key = _record_key(kind, identifier)
            normalized_leaf[normalize_text(identifier)] = leaf_key
            normalized_leaf[normalize_text(title)] = leaf_key
            edges.add((leaf_key, _record_key("skill", owner), "owned_by"))
            for dependency in dependencies:
                edges.add((leaf_key, f"unresolved:{dependency}", "depends_on"))
            for formula_id in _strings(full.get("formula_refs")):
                edges.add(
                    (leaf_key, _record_key("formula", formula_id), "uses_formula")
                )

            if kind == "workflow":
                steps = full.get("steps", item.get("steps", ()))
                if isinstance(steps, list):
                    for order, step in enumerate(steps):
                        if not isinstance(step, Mapping):
                            continue
                        member = _first_text(
                            step.get("skill_id"),
                            step.get("skill"),
                            step.get("capability"),
                            step.get("script"),
                        )
                        if member:
                            edges.add(
                                (leaf_key, f"unresolved:{member}", f"step:{order}")
                            )
    return normalized_leaf


def build_cognitive_index(root: Path) -> dict[str, Any]:
    root = root.resolve()
    records: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()

    catalog_path = root / "registry" / "skill_catalog.toml"
    catalog = (
        tomllib.loads(catalog_path.read_text(encoding="utf-8"))
        if catalog_path.is_file()
        else {"skills": []}
    )
    catalog_by_id = {str(item["id"]): item for item in catalog.get("skills", ())}
    semantic_path = root / "registry" / "semantic_capability_index.json"
    semantic = _json(semantic_path) if semantic_path.is_file() else {"records": []}
    for item in semantic.get("records", ()):
        identifier = str(item["id"])
        catalog_item = catalog_by_id.get(identifier, {})
        body_path = root / str(catalog_item.get("body", ""))
        _add(
            records,
            {
                "id": identifier,
                "kind": "skill",
                "title": identifier.replace("-", " "),
                "summary": item.get("description", "") or _description(body_path),
                "owner": identifier,
                "status": item.get("status", catalog_item.get("status", "candidate")),
                "domain": " ".join(map(str, item.get("domains", ()))),
                "aliases": item.get("synonyms", ()),
                "triggers": item.get("intents", ()),
                "concepts": item.get("concepts", ()),
                "relations": item.get("relations", ()),
                "path": str(catalog_item.get("body", "")),
                "source_sha256": item.get("body_sha256", ""),
                "risk": "R1",
            },
        )

    agent_registry_path = root / "registry" / "agency_agent_registry.json"
    if agent_registry_path.is_file():
        agent_registry = _json(agent_registry_path)
        agent_digest = hashlib.sha256(agent_registry_path.read_bytes()).hexdigest()
        agent_ids = {
            str(item.get("agent_id"))
            for item in agent_registry.get("agents", ())
            if isinstance(item, Mapping) and item.get("agent_id")
        }
        for item in agent_registry.get("agents", ()):
            if not isinstance(item, Mapping) or not item.get("agent_id"):
                continue
            identifier = str(item["agent_id"])
            lifecycle = str(item.get("lifecycle_state", "reference_only"))
            _add(
                records,
                {
                    "id": identifier,
                    "kind": "agent",
                    "title": item.get("name", identifier),
                    "summary": item.get("description", ""),
                    "owner": "runtime/agent_provider.py",
                    "status": "admitted"
                    if lifecycle in {"active", "advisory"}
                    else "reference_only",
                    "domain": item.get("division", "specialist"),
                    "aliases": item.get("aliases", ()),
                    "triggers": item.get("capabilities", ()),
                    "concepts": [
                        *list(_strings(item.get("capabilities"))),
                        lifecycle,
                        item.get("role_mode", ""),
                    ],
                    "relations": item.get("handoffs", ()),
                    "path": "registry/agency_agent_registry.json",
                    "implementation_path": "runtime/agent_provider.py",
                    "source_sha256": agent_digest,
                    "risk": {"low": "R1", "medium": "R2", "high": "R3"}.get(
                        str(item.get("risk_tier")), "R2"
                    ),
                },
            )
            for target in _strings(item.get("handoffs")):
                if target in agent_ids:
                    edges.add(
                        (
                            _record_key("agent", identifier),
                            _record_key("agent", target),
                            "hands_off_to",
                        )
                    )

    alias_path = root / "registry" / "capability_aliases.json"
    aliases = _json(alias_path).get("records", ()) if alias_path.is_file() else ()
    nested_by_normalized_id = _index_nested_assets(root, records, edges, catalog_by_id)

    brain_capability_path = root / "registry" / "brain_capabilities.json"
    if brain_capability_path.is_file():
        for item in _json(brain_capability_path).get("capabilities", ()):
            if not isinstance(item, Mapping):
                continue
            identifier = str(item.get("id", "")).strip()
            if not identifier:
                continue
            _add(
                records,
                {
                    **item,
                    "kind": "capability",
                    "aliases": [identifier.replace("-", " "), item.get("title", "")],
                    "triggers": item.get("triggers", ()),
                    "relations": [
                        *list(_strings(item.get("extends"))),
                        str(item.get("operation", "")),
                    ],
                    "implementation_path": item.get("path", ""),
                    "source_sha256": hashlib.sha256(
                        brain_capability_path.read_bytes()
                    ).hexdigest(),
                },
            )
            leaf_key = _record_key("capability", identifier)
            nested_by_normalized_id[normalize_text(identifier)] = leaf_key
            nested_by_normalized_id[normalize_text(str(item.get("title", "")))] = (
                leaf_key
            )
            owner = str(item.get("owner", ""))
            if owner:
                edges.add((leaf_key, _record_key("skill", owner), "owned_by"))
            for dependency in _strings(item.get("dependencies")):
                edges.add((leaf_key, f"unresolved:{dependency}", "depends_on"))
            for extended in _strings(item.get("extends")):
                edges.add((leaf_key, f"unresolved:{extended}", "extends"))
            for formula_id in _strings(item.get("formula_refs")):
                edges.add(
                    (leaf_key, _record_key("formula", formula_id), "uses_formula")
                )

    # Target-owned capability registries are first-class map inputs. The source
    # pack omitted project_stream_capabilities.json, which made reviewed
    # workflow steps appear dangling even though their canonical declarations
    # were already present in the target.
    for capability_path in (
        root / "registry" / "project_stream_capabilities.json",
        root / "registry" / "metacognitive_capabilities.json",
    ):
        if not capability_path.is_file():
            continue
        payload = _json(capability_path)
        for item in payload.get("capabilities", ()):
            if not isinstance(item, Mapping) or not item.get("id"):
                continue
            identifier = str(item["id"])
            target_owners = _strings(item.get("target_owners"))
            implementation_level = str(item.get("implementation_level", ""))
            integration_state = str(item.get("integration_state", ""))
            if integration_state == "mapped_tested_owner" or not integration_state:
                status = "admitted"
            else:
                status = "mapped_deferred"
            risk_name = str(item.get("risk", item.get("risk_default", "R1")))
            risk = {"low": "R1", "medium": "R2", "high": "R3", "critical": "R4"}.get(
                risk_name, risk_name
            )
            _add(
                records,
                {
                    "id": identifier,
                    "kind": "capability",
                    "title": item.get("title", identifier.replace("-", " ")),
                    "summary": _first_text(item.get("purpose"), item.get("summary")),
                    "owner": _first_text(
                        *target_owners, item.get("owner"), "capability-registry"
                    ),
                    "status": status,
                    "domain": _first_text(
                        item.get("category"), item.get("domain"), "capability"
                    ),
                    "aliases": [identifier.replace("-", " "), item.get("title", "")],
                    "triggers": item.get("triggers", ()),
                    "concepts": [
                        item.get("invariant", ""),
                        implementation_level,
                        integration_state,
                    ],
                    "inputs": item.get("inputs", ()),
                    "outputs": item.get("outputs", ()),
                    "dependencies": item.get("dependencies", ()),
                    "formula_refs": item.get("formula_refs", ()),
                    "relations": target_owners,
                    "path": capability_path.relative_to(root).as_posix(),
                    "implementation_path": target_owners[0] if target_owners else "",
                    "source_sha256": hashlib.sha256(
                        capability_path.read_bytes()
                    ).hexdigest(),
                    "risk": risk,
                },
            )

    # Exact aliases point to a leaf when one exists; otherwise to the governed owner.
    for item in aliases:
        alias, owner = str(item.get("alias", "")), str(item.get("owner", ""))
        leaf_key = nested_by_normalized_id.get(normalize_text(alias))
        target = leaf_key if leaf_key in records else _record_key("skill", owner)
        if target in records and alias.strip():
            records[target]["aliases"] = sorted(
                set(records[target]["aliases"]) | {alias.strip()}
            )

    for formula_path in (
        root / "registry" / "metacognitive_formulas.json",
        root / "registry" / "declared_suite_formulas.json",
        root / "registry" / "brain_formulas.json",
    ):
        if not formula_path.is_file():
            continue
        payload = _json(formula_path)
        for item in _rows(payload):
            identifier = str(item.get("id", "")).strip()
            if not identifier:
                continue
            _add(
                records,
                {
                    "id": identifier,
                    "kind": "formula",
                    "title": item.get("title", identifier.replace("-", " ")),
                    "summary": _first_text(
                        item.get("use_when"), item.get("purpose"), item.get("summary")
                    ),
                    "owner": "formula-registry",
                    "status": item.get("status", "reference_only"),
                    "domain": _first_text(item.get("domain"), "formula"),
                    "aliases": [
                        identifier.replace("-", " "),
                        item.get("equation", ""),
                        item.get("expression", ""),
                    ],
                    "triggers": [item.get("use_when", "")],
                    "concepts": [
                        *_strings(item.get("caveats")),
                        *_strings(item.get("assumptions")),
                    ],
                    "inputs": item.get("variables", ()),
                    "path": formula_path.relative_to(root).as_posix(),
                    "source_sha256": hashlib.sha256(
                        formula_path.read_bytes()
                    ).hexdigest(),
                },
            )

    # Existing orchestration registries may include workflows not represented by leaf indexes.
    for workflow_path in (
        root / "registry" / "skill_orchestrations.json",
        root / "registry" / "project_stream_orchestrations.json",
    ):
        payload = _read_jsonish(workflow_path)
        if payload is None:
            continue
        for item in _rows(payload):
            identifier = _first_text(item.get("id"), item.get("orchestration_id"))
            if not identifier:
                continue
            member_ids: list[str] = []
            for step in (
                item.get("steps", ()) if isinstance(item.get("steps", ()), list) else ()
            ):
                if isinstance(step, Mapping):
                    member = _first_text(
                        step.get("skill_id"),
                        step.get("skill"),
                        step.get("capability"),
                        step.get("script"),
                    )
                    if member:
                        member_ids.append(member)
            member_ids.extend(_strings(item.get("skills")))
            _add(
                records,
                {
                    "id": identifier,
                    "kind": "workflow",
                    "title": identifier.replace("-", " "),
                    "summary": _first_text(
                        item.get("trigger"),
                        item.get("purpose"),
                        item.get("description"),
                    ),
                    "owner": item.get("canonical_owner", "workflow-registry"),
                    "status": item.get("status", "active"),
                    "domain": "orchestration",
                    "aliases": [identifier.replace("-", " ")],
                    "triggers": [item.get("trigger", "")],
                    "relations": member_ids,
                    "path": workflow_path.relative_to(root).as_posix(),
                    "source_sha256": hashlib.sha256(
                        workflow_path.read_bytes()
                    ).hexdigest(),
                },
            )
            for order, member in enumerate(member_ids):
                if member:
                    edges.add(
                        (
                            _record_key("workflow", identifier),
                            f"unresolved:{member}",
                            f"step:{order}",
                        )
                    )

    knowledge_path = root / "registry" / "knowledge_sources.json"
    if knowledge_path.is_file():
        knowledge_payload = _json(knowledge_path)
        for item in knowledge_payload.get(
            "knowledge_sources", knowledge_payload.get("sources", ())
        ):
            identifier = str(item.get("id", "")).strip()
            if not identifier:
                continue
            _add(
                records,
                {
                    "id": identifier,
                    "kind": "knowledge",
                    "title": identifier.replace("-", " "),
                    "summary": _first_text(item.get("summary"), item.get("kind")),
                    "owner": "knowledge-registry",
                    "status": item.get("status", "active"),
                    "domain": "knowledge",
                    "aliases": [identifier.replace("-", " ")],
                    "relations": item.get("uses", ()),
                    "path": item.get("location", ""),
                },
            )

    # Resolve declared identifiers only through reviewed mappings or one
    # unambiguous exact/normalized identity.
    resolution_path = root / "registry" / "cognitive_dependency_resolutions.json"
    explicit_resolutions: dict[str, str] = {}
    if resolution_path.is_file():
        resolution_payload = _json(resolution_path)
        rows = resolution_payload.get("records", ())
        if resolution_payload.get("count") != len(rows):
            raise ValueError("cognitive dependency resolution count mismatch")
        for item in rows:
            identifier = str(item.get("identifier", ""))
            target_key = str(item.get("target_key", ""))
            if not identifier or not target_key or item.get("status") != "reviewed":
                raise ValueError(
                    "cognitive dependency resolutions must be reviewed and complete"
                )
            if identifier in explicit_resolutions:
                raise ValueError(
                    f"duplicate cognitive dependency resolution: {identifier}"
                )
            explicit_resolutions[identifier] = target_key

    known_ids: dict[str, list[str]] = {}
    normalized_ids: dict[str, list[str]] = {}
    for key, record in records.items():
        known_ids.setdefault(str(record["id"]), []).append(key)
        for identity in (
            record.get("id", ""),
            record.get("title", ""),
            *record.get("aliases", ()),
        ):
            normalized = normalize_text(str(identity))
            if normalized:
                normalized_ids.setdefault(normalized, []).append(key)
    resolved_edges: set[tuple[str, str, str]] = set()
    for source, target, relation in edges:
        if target.startswith("unresolved:"):
            identifier = target.split(":", 1)[1]
            explicit = explicit_resolutions.get(identifier)
            if explicit is not None:
                if explicit not in records:
                    raise ValueError(
                        f"cognitive dependency resolution target is absent: {identifier} -> {explicit}"
                    )
                target = explicit
            else:
                candidates = known_ids.get(identifier, ())
                if not candidates:
                    candidates = tuple(
                        sorted(set(normalized_ids.get(normalize_text(identifier), ())))
                    )
                target = candidates[0] if len(candidates) == 1 else target
        resolved_edges.add((source, target, relation))

    ordered_records = sorted(
        records.values(), key=lambda item: (item["kind"], item["id"])
    )
    ordered_edges = [
        {"source": source, "target": target, "relation": relation}
        for source, target, relation in sorted(resolved_edges)
    ]
    revision = stable_hash({"records": ordered_records, "edges": ordered_edges})
    counts: dict[str, int] = {}
    for record in ordered_records:
        counts[record["kind"]] = counts.get(record["kind"], 0) + 1
    return {
        "schema_version": "1.1",
        "loading_rule": "metadata_only_global_map_then_hydrate_selected_records",
        "revision": revision,
        "record_count": len(ordered_records),
        "edge_count": len(ordered_edges),
        "kind_counts": dict(sorted(counts.items())),
        "records": ordered_records,
        "edges": ordered_edges,
    }


def validate_cognitive_index(
    root: Path, actual: dict[str, Any] | None = None
) -> dict[str, Any]:
    expected = build_cognitive_index(root)
    errors: list[str] = []
    if actual is not None and actual != expected:
        errors.append("cognitive index is stale or non-deterministic")
    keys = [item["key"] for item in expected["records"]]
    if len(keys) != len(set(keys)):
        errors.append("cognitive index contains duplicate keys")
    known = set(keys)
    unresolved = [
        edge for edge in expected["edges"] if edge["target"].startswith("unresolved:")
    ]
    dangling = [
        edge
        for edge in expected["edges"]
        if not edge["target"].startswith("unresolved:") and edge["target"] not in known
    ]
    if dangling:
        errors.append(f"cognitive index has dangling edges: {len(dangling)}")
    return {
        "valid": not errors,
        "record_count": expected["record_count"],
        "edge_count": expected["edge_count"],
        "kind_counts": expected["kind_counts"],
        "unresolved_external_dependencies": len(unresolved),
        "revision": expected["revision"],
        "errors": errors,
    }
