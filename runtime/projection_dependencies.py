"""Revision-bound authority and rebuild planning for derived projections."""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping
from uuid import uuid4


SCHEMA_VERSION = "px.projection-dependencies/1.0"
SHA256 = re.compile(r"^[a-f0-9]{64}$")
GATES = frozenset({"rebuild_before_use", "block_until_rebuilt"})
COSTS = frozenset({"cheap_synchronous", "expensive"})


def revision_for_path(root: Path, relative: str) -> str:
    target = (root.resolve() / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"projection path escapes repository: {relative}") from error
    if target.is_file():
        return hashlib.sha256(target.read_bytes()).hexdigest()
    if not target.is_dir():
        raise ValueError(f"projection dependency does not exist: {relative}")
    digest = hashlib.sha256(b"px.projection-tree/1.0\0")
    for path in sorted(item for item in target.rglob("*") if item.is_file()):
        if {"__pycache__", ".pytest_cache", ".ruff_cache"} & set(path.parts):
            continue
        name = path.relative_to(target).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _validate(root: Path, payload: Mapping[str, object]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported projection dependency schema")
    rows = payload.get("projections")
    if not isinstance(rows, list) or not rows:
        raise ValueError("projection registry must contain projections")
    ids: set[str] = set()
    outputs: set[str] = set()
    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("projection record must be an object")
        projection_id = str(row.get("projection_id", ""))
        output = str(row.get("output", ""))
        builder = str(row.get("builder", ""))
        if not projection_id or projection_id in ids:
            raise ValueError("projection IDs must be non-empty and unique")
        if not output or output in outputs:
            raise ValueError("projection outputs must be non-empty and unique")
        ids.add(projection_id)
        outputs.add(output)
        indegree[output] = 0
        if not (root / builder).is_file():
            raise ValueError(f"unknown projection builder: {builder}")
        if row.get("cost") not in COSTS or row.get("rebuild_gate") not in GATES:
            raise ValueError(f"{projection_id}: invalid cost or rebuild gate")
        if (
            row.get("cost") == "expensive"
            and row.get("rebuild_gate") != "block_until_rebuilt"
        ):
            raise ValueError(f"{projection_id}: expensive projection must fail closed")
        if not SHA256.fullmatch(str(row.get("output_revision", ""))):
            raise ValueError(f"{projection_id}: output revision is required")
        dependencies = row.get("dependencies")
        if not isinstance(dependencies, list) or not dependencies:
            raise ValueError(f"{projection_id}: dependencies are required")
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                raise ValueError(f"{projection_id}: dependency must be an object")
            path = str(dependency.get("path", ""))
            if not path or not SHA256.fullmatch(str(dependency.get("revision", ""))):
                raise ValueError(f"{projection_id}: dependency revision is required")
            if not (root / path).exists():
                raise ValueError(f"{projection_id}: dependency does not exist: {path}")
    by_output = {str(row["output"]): row for row in rows}
    for row in rows:
        output = str(row["output"])
        for dependency in row["dependencies"]:
            source = str(dependency["path"])
            if source in by_output:
                adjacency[source].add(output)
                indegree[output] += 1
    queue = deque(sorted(path for path, count in indegree.items() if count == 0))
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for consumer in sorted(adjacency[current]):
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                queue.append(consumer)
    if visited != len(indegree):
        raise ValueError("projection dependency cycle")


def load_projection_dependencies(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    payload = json.loads(
        (resolved / "registry/projection_dependencies.json").read_text(encoding="utf-8")
    )
    _validate(resolved, payload)
    return payload


def _assert_known_projection_current(
    root: Path, projection_id: str, output: str
) -> None:
    """Refuse to record fresh revisions for known stale projection bytes."""
    known = {
        "semantic-capability-index",
        "cognitive-map-index",
        "agency-agent-graph",
        "registry-envelope-inventory",
    }
    if projection_id not in known:
        return
    path = root / output
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{projection_id}: projection output is unreadable") from error
    if projection_id == "semantic-capability-index":
        from .semantic_index import build_semantic_index

        expected = build_semantic_index(root)
    elif projection_id == "cognitive-map-index":
        from .cognitive_core.index_builder import build_cognitive_index

        expected = build_cognitive_index(root)
    elif projection_id == "agency-agent-graph":
        from .agent_provider import build_agent_graph

        expected = build_agent_graph(root)
    elif projection_id == "registry-envelope-inventory":
        from scripts.build_registry_envelope_inventory import build_inventory

        expected = build_inventory()
    if actual != expected:
        raise ValueError(
            f"{projection_id}: registered builder output is stale; rebuild before revision reconciliation"
        )


def reconcile_projection_dependencies(root: Path) -> dict[str, object]:
    """Publish exact current output/dependency revisions after registered builders run."""
    resolved = root.resolve(strict=True)
    path = resolved / "registry/projection_dependencies.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("projections"), list):
        raise ValueError("projection dependency registry is invalid")
    projections = []
    for row in payload["projections"]:
        if not isinstance(row, Mapping):
            raise ValueError("projection dependency row is invalid")
        output = str(row.get("output") or "")
        projection_id = str(row.get("projection_id") or "")
        dependencies = row.get("dependencies")
        if not isinstance(dependencies, list):
            raise ValueError("projection dependency list is invalid")
        _assert_known_projection_current(resolved, projection_id, output)
        projections.append(
            {
                **dict(row),
                "output_revision": revision_for_path(resolved, output),
                "dependencies": [
                    {**dict(item), "revision": revision_for_path(resolved, str(item.get("path") or ""))}
                    for item in dependencies
                    if isinstance(item, Mapping)
                ],
            }
        )
    current = {**dict(payload), "projections": projections}
    _validate(resolved, current)
    encoded = json.dumps(current, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_bytes(encoded)
    os.replace(prepared, path)
    return current


def build_projection_staleness(
    registry: Mapping[str, object],
) -> dict[str, object]:
    """Project one reconciled registry into a bounded all-current status."""
    rows = registry.get("projections")
    if not isinstance(rows, list):
        raise ValueError("projection dependency registry is invalid")
    projections = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("projection dependency row is invalid")
        projections.append(
            {
                "output": str(row.get("output") or ""),
                "output_revision": str(row.get("output_revision") or ""),
                "projection_id": str(row.get("projection_id") or ""),
                "stale": False,
            }
        )
    return {
        "consumer_policy": "block_until_governed_rebuild",
        "projections": projections,
        "schema_version": "px.projection-staleness/1.0",
    }


def invalidate_projections(
    root: Path, registry: Mapping[str, object] | None = None
) -> dict[str, object]:
    resolved = root.resolve()
    payload = dict(registry) if registry is not None else load_projection_dependencies(resolved)
    _validate(resolved, payload)
    rows = {str(row["output"]): row for row in payload["projections"]}
    stale: dict[str, dict[str, object]] = {}
    for output, row in sorted(rows.items()):
        changed = []
        for dependency in row["dependencies"]:
            path = str(dependency["path"])
            current = revision_for_path(resolved, path)
            if current != dependency["revision"]:
                changed.append(path)
        if not (resolved / output).is_file() or revision_for_path(resolved, output) != row["output_revision"]:
            changed.append(output)
        if changed:
            stale[output] = {
                "projection_id": row["projection_id"],
                "output": output,
                "reasons": tuple(sorted(set(changed))),
                "cost": row["cost"],
                "rebuild_gate": row["rebuild_gate"],
            }
    changed = True
    while changed:
        changed = False
        for output, row in sorted(rows.items()):
            if output in stale:
                continue
            upstream = sorted(
                str(item["path"])
                for item in row["dependencies"]
                if str(item["path"]) in stale
            )
            if upstream:
                stale[output] = {
                    "projection_id": row["projection_id"],
                    "output": output,
                    "reasons": tuple(upstream),
                    "cost": row["cost"],
                    "rebuild_gate": row["rebuild_gate"],
                }
                changed = True
    return {
        "schema_version": "px.projection-invalidation/1.0",
        "valid": True,
        "stale": tuple(stale[key] for key in sorted(stale)),
        "fresh_outputs": tuple(sorted(set(rows) - set(stale))),
    }


def plan_projection_rebuild(invalidation: Mapping[str, object]) -> dict[str, object]:
    stale = tuple(invalidation.get("stale", ()))
    synchronous = tuple(
        str(row["projection_id"])
        for row in stale
        if row.get("cost") == "cheap_synchronous"
        and row.get("rebuild_gate") == "rebuild_before_use"
    )
    blocked = tuple(
        str(row["projection_id"])
        for row in stale
        if row.get("rebuild_gate") == "block_until_rebuilt"
    )
    return {
        "schema_version": "px.projection-rebuild-plan/1.0",
        "synchronous": synchronous,
        "blocked_until_rebuilt": blocked,
        "usable": not blocked,
        "all_stale_accounted": len(stale) == len(synchronous) + len(blocked),
    }


def validate_graph_authority_manifest(
    root: Path, manifest: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Require one purpose-specific authority contract for every major graph."""
    resolved = root.resolve()
    try:
        payload = (
            dict(manifest)
            if manifest is not None
            else json.loads(
                (resolved / "registry/graph_authority_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": (str(error),)}
    errors: list[str] = []
    if payload.get("schema_version") != "px.graph-authority-manifest/1.0":
        errors.append("graph authority schema mismatch")
    rows = payload.get("graphs")
    if not isinstance(rows, list):
        rows = []
        errors.append("graphs must be a list")
    ids: set[str] = set()
    paths: set[str] = set()
    purposes: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("graph record must be an object")
            continue
        graph_id = str(row.get("graph_id", ""))
        path = str(row.get("path", ""))
        purpose = str(row.get("purpose", ""))
        authority = row.get("authority")
        if not graph_id or graph_id in ids or not path or path in paths:
            errors.append("graph IDs and paths must be non-empty and unique")
        ids.add(graph_id)
        paths.add(path)
        if not purpose or purpose in purposes:
            errors.append(f"{graph_id}: graph purpose must be distinct")
        purposes.add(purpose)
        if not isinstance(authority, str) or not authority.strip():
            errors.append(f"{graph_id}: exactly one authority owner is required")
        builder = str(row.get("builder", ""))
        if not (resolved / builder).is_file():
            errors.append(f"{graph_id}: builder is missing")
        if not row.get("consumers") or not row.get("invalidation_rule") or not row.get("rebuild_gate"):
            errors.append(f"{graph_id}: consumer/invalidation/gate contract is incomplete")
        revisions = row.get("source_revisions")
        if not isinstance(revisions, list) or not revisions or any(
            not isinstance(item, Mapping)
            or not str(item.get("path", ""))
            or not SHA256.fullmatch(str(item.get("revision", "")))
            for item in revisions
        ):
            errors.append(f"{graph_id}: source revisions are incomplete")
        expected = str(row.get("graph_revision", ""))
        target = resolved / path
        if not target.is_file() or not SHA256.fullmatch(expected):
            errors.append(f"{graph_id}: graph artifact/revision is missing")
        elif revision_for_path(resolved, path) != expected:
            errors.append(f"{graph_id}: consumer graph is stale")
    inventory = {
        path.relative_to(resolved).as_posix()
        for base in (resolved / "registry", resolved / "registry/graphs")
        for path in base.glob("*graph*.json")
        if path.name not in {"graph_authority_manifest.json", "graph_manifest.json"}
    }
    if paths != inventory:
        errors.append(
            f"graph inventory mismatch: missing={sorted(inventory - paths)}, extra={sorted(paths - inventory)}"
        )
    return {
        "schema_version": "px.graph-authority-validation/1.0",
        "valid": not errors,
        "graph_count": len(rows),
        "errors": tuple(errors),
    }


def reconcile_graph_authority_manifest(root: Path) -> dict[str, object]:
    """Refresh only declared graph and source revisions after graph builders run."""
    resolved = root.resolve(strict=True)
    path = resolved / "registry/graph_authority_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("graphs"), list):
        raise ValueError("graph authority manifest is invalid")
    graphs = []
    for row in payload["graphs"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("source_revisions"), list):
            raise ValueError("graph authority row is invalid")
        graphs.append(
            {
                **dict(row),
                "graph_revision": revision_for_path(resolved, str(row.get("path") or "")),
                "source_revisions": [
                    {**dict(item), "revision": revision_for_path(resolved, str(item.get("path") or ""))}
                    for item in row["source_revisions"]
                    if isinstance(item, Mapping)
                ],
            }
        )
    current = {**dict(payload), "graphs": graphs}
    report = validate_graph_authority_manifest(resolved, current)
    if not report["valid"]:
        raise ValueError("reconciled graph authority is invalid: " + "; ".join(report["errors"]))
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(prepared, path)
    return current
