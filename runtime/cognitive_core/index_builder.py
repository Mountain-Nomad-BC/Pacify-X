"""Build one deterministic metadata-only map across PACIFY-X cognitive assets.

Compilation inspects bounded source images and emits typed metadata and load paths.
Runtime retrieval searches that projection and hydrates only selected records.
Declared metadata and measured source digests do not grant execution authority.
"""

from __future__ import annotations

import codecs
from contextvars import ContextVar
import time
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

from .common import normalize_text, stable_hash
from ..archive_io import reject_path_links
from ..bounded_walk import bounded_walk, WalkLimits
from ..input_files import (
    contained_file,
    relative_source_path,
    read_file_image,
    read_file_prefix,
    cooperative_deadline,
    check_deadline,
)
from ..json_io import decode_json_object, bounded_json_text
from ..skill_inputs import parse_catalog_metadata
from ..numeric_inputs import bounded_mapping, bounded_sequence, bounded_json_value

_DESCRIPTION = re.compile(r"(?m)^description:\s*[\"']?(.*?)[\"']?\s*$")
_INDEX_KIND = {
    "capability-index.json": "capability",
    "capabilities-index.json": "capability",
    "scripts-index.json": "script",
    "workflow-index.json": "workflow",
    "orchestration-index.json": "workflow",
}


_MIB = 1024 * 1024
_FIXED = (
    "skill_catalog.toml",
    "semantic_capability_index.json",
    "agency_agent_registry.json",
    "capability_aliases.json",
    "brain_capabilities.json",
    "project_stream_capabilities.json",
    "metacognitive_capabilities.json",
    "metacognitive_formulas.json",
    "declared_suite_formulas.json",
    "brain_formulas.json",
    "skill_orchestrations.json",
    "project_stream_orchestrations.json",
    "knowledge_sources.json",
    "cognitive_dependency_resolutions.json",
)
_INPUTS = ContextVar("cognitive_compilation_inputs", default=None)


class _CompilationInputs:
    """One finite compilation inventory, never shared between builds."""

    def __init__(self, root):
        reject_path_links(root)
        self.root = root.resolve(strict=True)
        self.deadline = cooperative_deadline()
        self.inventory = {}
        self.locators = {}
        self.images = {}
        self.digests = {}
        self.objects = {}
        self.current_sources = []
        self.current_prefixes = []
        self.descriptions = {}
        self.prefixes = {}
        self.record_sizes = {}
        self.record_bytes = 0
        self.total_bytes = 0
        self.indices = []
        for name in _FIXED:
            self.reserve(self.root / "registry" / name, optional=True)
        references = self.root / ".px/skills"
        reject_path_links(references)
        if references.exists():

            def excluded(relative):
                parts = relative.split("/")
                if any(
                    p.casefold() in {"quarantine", "_quarantine", ".quarantine"}
                    for p in parts
                ):
                    return True
                return (
                    len(parts) == 2
                    and parts[1] != "references"
                    or len(parts) >= 3
                    and (len(parts) != 3 or parts[2] not in _INDEX_KIND)
                )

            walked = bounded_walk(
                references,
                limits=WalkLimits(
                    max_files=4096,
                    max_depth=3,
                    max_bytes=64 * _MIB,
                    max_entries=20000,
                    max_directories=4096,
                    max_duration_seconds=max(0.001, self.deadline - time.monotonic()),
                ),
                exclude=excluded,
            )
            self.indices = sorted(
                e.path for e in walked.files if e.path.name in _INDEX_KIND
            )
            for path in self.indices:
                self.reserve(path)
        # Descriptor images establish the second-stage inventory. No referenced
        # body is acquired until all declared body sizes fit the shared budget.
        for path in self.indices:
            for item in _rows(self.json(path)):
                relative = _text(item.get("path", ""), "body path", 4096)
                if relative:
                    self.reserve(self.root / relative_source_path(relative))

    def relative(self, path):
        check_deadline(self.deadline)
        reject_path_links(path)
        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError as error:
            raise ValueError("compiler input escapes original root") from error
        return relative_source_path(relative)

    def reserve(self, path, *, optional=False, prefix=False):
        relative = self.relative(path)
        prior = self.locators.get(relative.casefold())
        if prior is not None and prior != relative:
            raise ValueError("case-aliased compiler source locator")
        if relative in self.inventory:
            return self.inventory[relative]
        try:
            checked, info = contained_file(self.root, relative)
        except FileNotFoundError:
            if optional:
                return None
            raise
        charge = min(info.st_size, 65537) if prefix else info.st_size
        if not prefix and charge > _MIB:
            raise ValueError("compiler source exceeds per-image byte budget")
        if len(self.inventory) >= 4096 or self.total_bytes + charge > 64 * _MIB:
            raise ValueError("compiler source inventory exceeds aggregate budget")
        self.total_bytes += charge
        self.locators[relative.casefold()] = relative
        self.inventory[relative] = (checked, info, prefix)
        return self.inventory[relative]

    def image(self, path):
        relative = self.relative(path)
        if relative not in self.images:
            checked, info, prefix = self.reserve(path)
            if prefix:
                raise ValueError(
                    "prefix image cannot stand in for a whole source image"
                )
            self.images[relative] = bytes(
                read_file_image(checked, info, limit=_MIB, deadline=self.deadline)
            )
        check_deadline(self.deadline)
        return self.images[relative]

    def digest(self, path):
        relative = self.relative(path)
        if relative not in self.digests:
            self.digests[relative] = hashlib.sha256(self.image(path)).hexdigest()
        return self.digests[relative]

    def json(self, path):
        relative = self.relative(path)
        if relative not in self.objects:
            self.objects[relative] = decode_json_object(
                self.image(path), max_bytes=_MIB, max_depth=32, max_nodes=100000
            )
        payload = self.objects[relative]
        for key in (
            "records",
            "agents",
            "capabilities",
            "workflows",
            "orchestrations",
            "scripts",
            "formulas",
            "knowledge_sources",
            "sources",
        ):
            if key not in payload:
                continue
            rows = bounded_sequence(payload[key], key, maximum=20000)
            seen = set()
            for row in rows:
                bounded_mapping(row, key + " row", maximum=256)
                for identity_field in ("id", "agent_id", "orchestration_id"):
                    if identity_field in row:
                        identity = _text(row[identity_field], identity_field, 512)
                        if not identity or (identity_field, identity) in seen:
                            raise ValueError(
                                "missing or duplicate source record identity"
                            )
                        seen.add((identity_field, identity))
        self.current_sources = [relative]
        self.current_prefixes = []
        return payload

    def provenance(self):
        return [
            dict(path=p, sha256=self.digest(self.root / p))
            for p in sorted(set(self.current_sources))
        ]

    def description(self, path):
        relative = self.relative(path)
        if relative in self.descriptions:
            self.current_prefixes = [self.prefixes[relative]]
            return self.descriptions[relative]
        reserved = self.reserve(path, optional=True, prefix=True)
        if reserved is None:
            return ""
        checked, info, prefix = reserved
        if prefix:
            raw, truncated = read_file_prefix(
                checked, info, limit=65536, deadline=self.deadline
            )
        else:
            raw = self.image(path)[:65536]
            truncated = info.st_size > len(raw)
        self.prefixes[relative] = dict(
            path=relative,
            sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),
            truncated=truncated,
        )
        self.current_prefixes = [self.prefixes[relative]]
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        text = decoder.decode(raw, final=not truncated)
        lines = text.splitlines()
        description = ""
        if lines and lines[0] == "---":
            for index, line in enumerate(lines[1:], 1):
                if line == "---":
                    match = _DESCRIPTION.search("\n".join(lines[1:index]))
                    description = (
                        _text(match.group(1).strip(), "description", 16384)
                        if match
                        else ""
                    )
                    break
        self.descriptions[relative] = description
        return description

    def retain_record(self, record):
        check_deadline(self.deadline)
        # The wrapper conservatively includes the final record indentation.
        size = len(
            bounded_json_text({"records": [record]}, max_bytes=8 * _MIB).encode("utf-8")
        )
        total = self.record_bytes - self.record_sizes.get(record["key"], 0) + size
        if total > 8 * _MIB:
            raise ValueError("cognitive retained record byte budget exhausted")
        self.record_sizes[record["key"]] = size
        self.record_bytes = total


def _inputs():
    result = _INPUTS.get()
    if result is None:
        raise ValueError("cognitive source acquisition requires a bounded compilation")
    check_deadline(result.deadline)
    return result


def _text(value, name, limit=16384):
    if type(value) is not str or len(value) > limit:
        raise ValueError(name + " requires bounded text")
    try:
        if len(value.encode("utf-8")) > limit:
            raise ValueError(name + " exceeds UTF-8 budget")
    except UnicodeError as error:
        raise ValueError(name + " requires valid UTF-8") from error
    return value.strip()


def _json(path):
    return _inputs().json(path)


def _read_jsonish(path):
    if _inputs().reserve(path, optional=True) is None:
        return None
    return _json(path)


def _description(path):
    return _inputs().description(path)


def _strings(value):
    if value is None:
        return []
    if type(value) is str:
        return [_text(value, "metadata item")]
    if type(value) is dict:
        # Named variable/input maps project their explicit keys, never objects.
        value = list(bounded_mapping(value, "metadata map", maximum=256))
    bounded_sequence(value, "metadata items", maximum=256)
    return [_text(item, "metadata item") for item in value if item is not None]


def _first_text(*values):
    for value in values:
        if value is not None:
            text = _text(value, "metadata text")
            if text:
                return text
    return ""


def _required_identity(item, *fields):
    for field in fields:
        if field in item:
            value = _text(item[field], field, 512)
            if value:
                return value
    raise ValueError("source record requires a nonempty identity")


_STEP_MEMBERS = ("skill_id", "skill", "capability", "script")


def _step_member(step):
    return _first_text(*(step.get(field) for field in _STEP_MEMBERS))


def _workflow_steps(value):
    steps = bounded_sequence(value, "workflow steps", maximum=256)
    identities = set()
    for step in steps:
        bounded_mapping(step, "workflow step", maximum=256)
        identity = _required_identity(step, "id") if "id" in step else ""
        if identity:
            if identity in identities:
                raise ValueError("duplicate local workflow step identity")
            identities.add(identity)
        members = set()
        for field in _STEP_MEMBERS:
            if field in step:
                members.add(_required_identity(step, field))
        if len(members) > 1:
            raise ValueError("workflow member aliases name different targets")
        if not identity and not _step_member(step):
            raise ValueError("workflow step requires a local ID or global member")
        for field in ("requires", "depends_on"):
            if field not in step:
                continue
            labels = bounded_sequence(step[field], field, maximum=256)
            for label in labels:
                if not _text(label, "workflow dependency", 512):
                    raise ValueError("workflow dependency requires an identity")
    return steps


def _rows(
    payload,
    keys=(
        "records",
        "workflows",
        "orchestrations",
        "capabilities",
        "scripts",
        "formulas",
    ),
):
    if sum(key in payload for key in keys) > 1:
        raise ValueError("competing cognitive collection aliases")
    for key in keys:
        if key in payload:
            values = bounded_sequence(payload[key], key, maximum=20000)
            if any(type(item) is not dict for item in values):
                raise ValueError(key + " requires object records")
            return values
    return []


class _Edges(set):
    def __init__(self):
        super().__init__()
        self.serialized_bytes = 0

    def add(self, edge):
        if type(edge) is not tuple or len(edge) != 3:
            raise ValueError("invalid cognitive edge")
        for value in edge:
            _text(value, "edge identity", 1024)
        if edge in self:
            return
        if len(self) >= 100000:
            raise ValueError("cognitive edge budget exhausted")
        inputs = _INPUTS.get()
        if inputs:
            check_deadline(inputs.deadline)
        source, target, relation = edge
        size = len(
            bounded_json_text(
                {"edges": [dict(source=source, target=target, relation=relation)]},
                max_bytes=8 * _MIB,
            ).encode("utf-8")
        )
        if self.serialized_bytes + size > 8 * _MIB:
            raise ValueError("cognitive retained edge byte budget exhausted")
        self.serialized_bytes += size
        super().add(edge)


def _record_key(kind, identifier):
    return f"{kind}:{identifier}"


_LIST_FIELDS = (
    "aliases",
    "triggers",
    "concepts",
    "inputs",
    "outputs",
    "dependencies",
    "formula_refs",
    "relations",
)
_SCALAR_FIELDS = (
    "title",
    "summary",
    "owner",
    "status",
    "domain",
    "path",
    "implementation_path",
    "source_sha256",
    "declared_lineage_sha256",
    "risk",
)
_CONTRACT_FIELDS = {
    "owner",
    "status",
    "path",
    "implementation_path",
    "source_sha256",
    "declared_lineage_sha256",
    "risk",
}


def _add(records, record):
    bounded_mapping(record, "cognitive record", maximum=256)
    identifier = _text(record.get("id", ""), "record identity", 512)
    kind = _text(record.get("kind", ""), "record kind", 512)
    if not identifier or kind not in {
        "skill",
        "capability",
        "script",
        "workflow",
        "formula",
        "knowledge",
        "agent",
    }:
        raise ValueError("cognitive record requires a typed identity and kind")
    key = _record_key(kind, identifier)
    defaults = dict(
        title=identifier.replace("-", " "),
        summary="",
        owner="",
        status="candidate",
        domain="",
        path="",
        implementation_path="",
        source_sha256="",
        declared_lineage_sha256="",
        risk="unknown",
    )
    scalars = {
        field: _text(
            record.get(field, default),
            field,
            4096
            if field in {"path", "implementation_path"}
            else 512
            if field in {"owner", "status", "source_sha256", "risk"}
            else 16384,
        )
        for field, default in defaults.items()
    }
    if not scalars["owner"] and scalars["status"] in {
        "active",
        "admitted",
        "executable",
    }:
        scalars["status"] = "candidate"
    if not scalars["status"]:
        scalars["status"] = "candidate"
    digest = scalars["source_sha256"]
    if digest and not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("declared source digest must be SHA-256")
    lineage = scalars["declared_lineage_sha256"]
    if lineage and not re.fullmatch("[0-9a-f]{64}", lineage):
        raise ValueError("declared lineage must have SHA-256 shape")
    normalized = dict(
        key=key,
        id=identifier,
        kind=kind,
        **scalars,
        loading_rule="metadata_only_until_selected",
        authority="not_evaluated",
    )
    for field in _LIST_FIELDS:
        normalized[field] = sorted(set(x for x in _strings(record.get(field)) if x))
    inputs = _INPUTS.get()
    normalized["source_provenance"] = inputs.provenance() if inputs else []
    normalized["prefix_provenance"] = (
        [dict(prefix) for prefix in inputs.current_prefixes] if inputs else []
    )
    normalized["scalar_declarations"] = {
        field: [value] for field, value in scalars.items()
    }
    if "status_declarations" in record:
        declarations = sorted(set(_strings(record["status_declarations"])))
        if not declarations:
            raise ValueError("status declarations cannot be empty")
        normalized["scalar_declarations"]["status"] = declarations
    normalized["conflicts"] = (
        ["status"] if len(normalized["scalar_declarations"]["status"]) > 1 else []
    )
    if normalized["conflicts"]:
        normalized["status"] = "conflicted"
    normalized["source_sha256_kind"] = record.get("source_sha256_kind", "declared")
    if normalized["source_sha256_kind"] not in {"declared", "measured", "mixed"}:
        raise ValueError("invalid source digest interpretation")
    normalized["lineage_verification"] = (
        "matching_named_source_declaration" if lineage else "not_evaluated"
    )
    bounded_json_value(normalized)
    existing = records.get(key)
    if existing is None:
        if len(records) >= 20000:
            raise ValueError("cognitive record budget exhausted")
        if inputs:
            inputs.retain_record(normalized)
        records[key] = normalized
        return
    for field in _LIST_FIELDS:
        values = set(existing[field]) | set(normalized[field])
        if len(values) > 256:
            raise ValueError("merged cognitive metadata exceeds item budget")
        existing[field] = sorted(values)
    declarations = existing["scalar_declarations"]
    for field in _SCALAR_FIELDS:
        values = sorted(
            set(declarations[field]) | set(normalized["scalar_declarations"][field])
        )
        if len(values) > 256:
            raise ValueError("cognitive scalar contributor budget exhausted")
        declarations[field] = values
        nonempty = [value for value in values if value]
        existing[field] = nonempty[0] if nonempty else ""
    conflicts = sorted(
        field for field in _CONTRACT_FIELDS if len(declarations[field]) > 1
    )
    existing["conflicts"] = conflicts
    if conflicts:
        existing["status"] = "conflicted"
        for field in conflicts:
            if field != "status":
                existing[field] = ""
    existing["lineage_verification"] = (
        "conflicting_source_declarations"
        if "declared_lineage_sha256" in conflicts
        else "matching_named_source_declaration"
        if existing["declared_lineage_sha256"]
        else "not_evaluated"
    )
    if existing["source_sha256_kind"] != normalized["source_sha256_kind"]:
        existing["source_sha256_kind"] = "mixed"
    sources = {
        (p["path"], p["sha256"])
        for p in existing["source_provenance"] + normalized["source_provenance"]
    }
    if len(sources) > 256:
        raise ValueError("cognitive source contributor budget exhausted")
    existing["source_provenance"] = [
        dict(path=path, sha256=sha) for path, sha in sorted(sources)
    ]
    prefixes = {
        (p["path"], p["sha256"], p["bytes"], p["truncated"])
        for p in existing["prefix_provenance"] + normalized["prefix_provenance"]
    }
    if len(prefixes) > 256:
        raise ValueError("cognitive prefix contributor budget exhausted")
    existing["prefix_provenance"] = [
        dict(path=path, sha256=sha, bytes=size, truncated=truncated)
        for path, sha, size, truncated in sorted(prefixes)
    ]
    if inputs:
        inputs.retain_record(existing)


def _nested_source_metadata(body_path, kind, identifier, owner, descriptor):
    """Keep declared per-record lineage separate from measured image identity."""
    inputs = _inputs()
    raw = inputs.image(body_path)
    full = (
        _json(body_path)
        if body_path.suffix.casefold() == ".json"
        or (
            kind == "workflow"
            and body_path.suffix.casefold() in {".yaml", ".yml"}
            and raw.lstrip().startswith(b"{")
        )
        else {}
    )
    lineage = ""
    if kind == "workflow" and "workflows" in full:
        rows = _rows(full)
        if (
            full.get("schema_version") != "1.0"
            or type(full.get("workflow_count")) is not int
            or full["workflow_count"] != len(rows)
        ):
            raise ValueError("named workflow source envelope is invalid")
        names = {}
        for row in rows:
            name = _text(row.get("name", row.get("id", "")), "workflow name", 512)
            if not name or name in names:
                raise ValueError("named workflow identities must be unique")
            names[name] = row
        if identifier not in names:
            raise ValueError("named workflow source record is missing")
        full = names[identifier]
        if full.get("canonical_owner", owner) != owner:
            raise ValueError(
                "named workflow source owner differs from descriptor owner"
            )
        if "source_sha256" in descriptor:
            lineage = _text(
                descriptor["source_sha256"], "declared workflow lineage", 64
            )
            if not re.fullmatch("[0-9a-f]{64}", lineage) or lineage != full.get(
                "source_sha256"
            ):
                raise ValueError(
                    "named workflow lineage differs from its source declaration"
                )
    for field in ("sha256", "source_sha256"):
        if field == "source_sha256" and lineage:
            continue
        declared = descriptor.get(field, "")
        if declared and declared != inputs.digest(body_path):
            raise ValueError(
                "nested source digest differs from its compiled image: "
                + body_path.relative_to(inputs.root).as_posix()
            )
    return full, lineage


def _index_nested_assets(
    root: Path,
    records: dict[str, dict[str, Any]],
    edges: set[tuple[str, str, str]],
    catalog_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, set[str]]:
    normalized_leaf: dict[str, set[str]] = {}
    for index_path in _inputs().indices:
        kind = _INDEX_KIND.get(index_path.name)
        if kind is None:
            continue
        payload = _read_jsonish(index_path) or {}
        owner = index_path.relative_to(root).parts[2]
        owner_status = _text(
            catalog_by_id.get(owner, {}).get("status", "candidate"), "metadata text"
        )
        for item in _rows(payload):
            identifier = _required_identity(item, "id")
            relative_path = _text(item.get("path", ""), "metadata text")
            body_path = root / relative_path
            record_status = owner_status if relative_path else "candidate"
            if relative_path:
                full, declared_lineage = _nested_source_metadata(
                    body_path, kind, identifier, owner, item
                )
            else:
                if item.get("sha256") or item.get("source_sha256"):
                    raise ValueError(
                        "declared source digest has no source locator: " + identifier
                    )
                full, declared_lineage = {}, ""

            _inputs().current_sources = [index_path.relative_to(root).as_posix()]
            _inputs().current_prefixes = []
            if relative_path:
                _inputs().current_sources.append(relative_path)
            if owner in catalog_by_id:
                _inputs().current_sources.append("registry/skill_catalog.toml")
            title = _first_text(
                item.get("title"),
                full.get("title"),
                full.get("name"),
                identifier.replace("-", " "),
            )
            summary = _first_text(
                item.get("summary"),
                item.get("description"),
                full.get("summary"),
                full.get("description"),
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
                    "status": record_status,
                    "status_declarations": [
                        record_status,
                        *([item["status"]] if "status" in item else []),
                        *([full["status"]] if "status" in full else []),
                    ],
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
                    "relations": full.get("relations", item.get("relations", ())),
                    "path": relative_path,
                    "implementation_path": implementation,
                    "declared_lineage_sha256": declared_lineage,
                    "source_sha256_kind": "measured",
                    "source_sha256": _inputs().digest(body_path)
                    if relative_path
                    else "",
                    "risk": _first_text(full.get("risk"), "R1"),
                },
            )
            leaf_key = _record_key(kind, identifier)
            normalized_leaf.setdefault(normalize_text(identifier), set()).add(leaf_key)
            normalized_leaf.setdefault(normalize_text(title), set()).add(leaf_key)
            edges.add((leaf_key, _record_key("skill", owner), "owned_by"))
            for dependency in dependencies:
                edges.add((leaf_key, f"unresolved:{dependency}", "depends_on"))
            for formula_id in _strings(full.get("formula_refs")):
                edges.add(
                    (leaf_key, _record_key("formula", formula_id), "uses_formula")
                )

            if kind == "workflow":
                steps = _workflow_steps(full.get("steps", item.get("steps", ())))
                for order, step in enumerate(steps):
                    member = _step_member(step)
                    if member:
                        edges.add((leaf_key, f"unresolved:{member}", f"step:{order}"))
    return normalized_leaf


def build_cognitive_index(root: Path) -> dict[str, Any]:
    inputs = _CompilationInputs(root)
    token = _INPUTS.set(inputs)
    try:
        result = _build_cognitive_index(inputs.root)
        bounded_json_text(result, max_bytes=8 * _MIB - 1)
        check_deadline(inputs.deadline)
        return result
    finally:
        _INPUTS.reset(token)


def _build_cognitive_index(root: Path) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = _Edges()

    catalog_path = root / "registry" / "skill_catalog.toml"
    catalog = (
        parse_catalog_metadata(
            _inputs().image(catalog_path), deadline=_inputs().deadline
        )
        if catalog_path.is_file()
        else {"skills": []}
    )
    catalog_by_id = {item["id"]: item for item in catalog["skills"]}
    semantic_path = root / "registry" / "semantic_capability_index.json"
    semantic = _json(semantic_path) if semantic_path.is_file() else {"records": []}
    for item in semantic.get("records", ()):
        identifier = _required_identity(item, "id")
        catalog_item = catalog_by_id.get(identifier, {})
        body_path = root / _text(catalog_item.get("body", ""), "metadata text")
        _inputs().current_sources = ["registry/semantic_capability_index.json"]
        _inputs().current_prefixes = []
        if catalog_item:
            _inputs().current_sources.append("registry/skill_catalog.toml")
        _add(
            records,
            {
                "id": identifier,
                "kind": "skill",
                "title": identifier.replace("-", " "),
                "summary": item.get("description", "")
                or (_description(body_path) if catalog_item else ""),
                "status_declarations": [
                    catalog_item.get("status", "candidate"),
                    item.get("status", catalog_item.get("status", "candidate")),
                ]
                if catalog_item
                else ["candidate"],
                "owner": identifier,
                "status": item.get("status", catalog_item.get("status", "candidate"))
                if catalog_item
                else "candidate",
                "domain": " ".join(_strings(item.get("domains", ()))),
                "aliases": item.get("synonyms", ()),
                "triggers": item.get("intents", ()),
                "concepts": item.get("concepts", ()),
                "relations": item.get("relations", ()),
                "path": _text(catalog_item.get("body", ""), "metadata text"),
                "source_sha256": item.get("body_sha256", ""),
                "risk": "R1",
            },
        )

    agent_registry_path = root / "registry" / "agency_agent_registry.json"
    if agent_registry_path.is_file():
        agent_registry = _json(agent_registry_path)
        agent_digest = _inputs().digest(agent_registry_path)
        agent_ids = {
            _required_identity(item, "agent_id")
            for item in agent_registry.get("agents", ())
        }
        for item in agent_registry.get("agents", ()):
            identifier = _required_identity(item, "agent_id")
            lifecycle = _text(
                item.get("lifecycle_state", "reference_only"), "metadata text"
            )
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
                    "source_sha256_kind": "measured",
                    "source_sha256": agent_digest,
                    "risk": {"low": "R1", "medium": "R2", "high": "R3"}.get(
                        _text(item.get("risk_tier", ""), "metadata text"), "R2"
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
            identifier = _required_identity(item, "id")
            _add(
                records,
                {
                    **{
                        field: item[field]
                        for field in (
                            "id",
                            "title",
                            "summary",
                            "owner",
                            "status",
                            "domain",
                            "concepts",
                            "inputs",
                            "outputs",
                            "dependencies",
                            "formula_refs",
                            "path",
                            "risk",
                        )
                        if field in item
                    },
                    "kind": "capability",
                    "aliases": [identifier.replace("-", " "), item.get("title", "")],
                    "triggers": item.get("triggers", ()),
                    "relations": [
                        *list(_strings(item.get("extends"))),
                        _text(item.get("operation", ""), "metadata text"),
                    ],
                    "implementation_path": item.get("path", ""),
                    "source_sha256_kind": "measured",
                    "source_sha256": _inputs().digest(brain_capability_path),
                },
            )
            leaf_key = _record_key("capability", identifier)
            nested_by_normalized_id.setdefault(normalize_text(identifier), set()).add(
                leaf_key
            )
            nested_by_normalized_id.setdefault(
                normalize_text(_text(item.get("title", ""), "metadata text")), set()
            ).add(leaf_key)
            owner = _text(item.get("owner", ""), "metadata text")
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
            identifier = _required_identity(item, "id")
            target_owners = _strings(item.get("target_owners"))
            implementation_level = _text(
                item.get("implementation_level", ""), "metadata text"
            )
            integration_state = _text(
                item.get("integration_state", ""), "metadata text"
            )
            if integration_state == "mapped_tested_owner" and target_owners:
                status = "admitted"
            else:
                status = "mapped_deferred" if integration_state else "candidate"
            declared_status = _text(item.get("status", ""), "capability status", 512)
            if not declared_status:
                status = "candidate"
            if declared_status and declared_status not in {"active", "admitted"}:
                status = declared_status
            risk_name = _text(
                item.get("risk", item.get("risk_default", "R1")), "metadata text"
            )
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
                    "source_sha256_kind": "measured",
                    "source_sha256": _inputs().digest(capability_path),
                    "risk": risk,
                },
            )

    # Exact aliases point to a leaf when one exists; otherwise to the governed owner.
    seen_aliases = set()
    for item in aliases:
        alias, owner = (
            _text(item.get("alias", ""), "metadata text"),
            _text(item.get("owner", ""), "metadata text"),
        )
        normalized_alias = normalize_text(alias)
        if not normalized_alias or normalized_alias in seen_aliases:
            raise ValueError("missing or duplicate alias declaration")
        seen_aliases.add(normalized_alias)
        candidates = nested_by_normalized_id.get(normalized_alias, set())
        owner_key = _record_key("skill", owner)
        if len(candidates) > 1:
            if owner_key not in records or len(candidates) > 256:
                raise ValueError(
                    "ambiguous normalized leaf alias without a bounded declared owner: "
                    + alias
                )
            target = owner_key
            conflicts = records[target].setdefault("alias_conflicts", [])
            if len(conflicts) >= 256:
                raise ValueError("alias conflict metadata budget exhausted")
            conflicts.append({"alias": alias, "candidates": sorted(candidates)})
            conflicts.sort(key=lambda item: item["alias"])
        else:
            leaf_key = next(iter(candidates)) if candidates else None
            target = leaf_key if leaf_key in records else owner_key
        if target in records and alias.strip():
            provenance = records[target]["source_provenance"]
            alias_source = {
                "path": alias_path.relative_to(root).as_posix(),
                "sha256": _inputs().digest(alias_path),
            }
            if alias_source not in provenance:
                if len(provenance) >= 256:
                    raise ValueError("alias source provenance budget exhausted")
                provenance.append(alias_source)
                provenance.sort(key=lambda item: (item["path"], item["sha256"]))
            if (
                len(records[target]["aliases"]) >= 256
                and alias.strip() not in records[target]["aliases"]
            ):
                raise ValueError("merged alias item budget exhausted")
            records[target]["aliases"] = sorted(
                set(records[target]["aliases"]) | {alias.strip()}
            )
            _inputs().retain_record(records[target])

    for formula_path in (
        root / "registry" / "metacognitive_formulas.json",
        root / "registry" / "declared_suite_formulas.json",
        root / "registry" / "brain_formulas.json",
    ):
        if not formula_path.is_file():
            continue
        payload = _json(formula_path)
        for item in _rows(payload):
            identifier = _required_identity(item, "id")
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
                    "source_sha256_kind": "measured",
                    "source_sha256": _inputs().digest(formula_path),
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
            identifier = _required_identity(item, "id", "orchestration_id")
            member_ids: list[str] = []
            member_edges = []
            steps = _workflow_steps(item.get("steps", ()))
            for order, step in enumerate(steps):
                member = _step_member(step)
                if member:
                    member_ids.append(member)
                    member_edges.append((order, member))
            for order, member in enumerate(_strings(item.get("skills")), len(steps)):
                member_ids.append(member)
                member_edges.append((order, member))
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
                    "status": item.get("status", "candidate"),
                    "domain": "orchestration",
                    "aliases": [identifier.replace("-", " ")],
                    "triggers": [item.get("trigger", "")],
                    "relations": member_ids,
                    "path": workflow_path.relative_to(root).as_posix(),
                    "source_sha256_kind": "measured",
                    "source_sha256": _inputs().digest(workflow_path),
                },
            )
            for order, member in member_edges:
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
        for item in _rows(knowledge_payload, ("knowledge_sources", "sources")):
            identifier = _required_identity(item, "id")
            _add(
                records,
                {
                    "id": identifier,
                    "kind": "knowledge",
                    "title": identifier.replace("-", " "),
                    "summary": _first_text(item.get("summary"), item.get("kind")),
                    "owner": "knowledge-registry",
                    "status": item.get("status", "candidate"),
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
        if type(resolution_payload.get("count")) is not int or resolution_payload[
            "count"
        ] != len(rows):
            raise ValueError("cognitive dependency resolution count mismatch")
        for item in rows:
            identifier = _text(item.get("identifier", ""), "metadata text")
            target_key = _text(item.get("target_key", ""), "metadata text")
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
    alias_work = 0
    for key, record in records.items():
        alias_work += 2 + len(record["aliases"])
        if alias_work > 100000:
            raise ValueError("normalized alias work budget exhausted")
        known_ids.setdefault(_text(record["id"], "metadata text"), []).append(key)
        for identity in (
            record.get("id", ""),
            record.get("title", ""),
            *record.get("aliases", ()),
        ):
            normalized = normalize_text(_text(identity, "metadata text"))
            if normalized:
                normalized_ids.setdefault(normalized, []).append(key)
    resolved_edges: set[tuple[str, str, str]] = _Edges()
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

    counts: dict[str, int] = {}
    for record in records.values():
        counts[record["kind"]] = counts.get(record["kind"], 0) + 1
    result = {
        "schema_version": "1.1",
        "loading_rule": "metadata_only_global_map_then_hydrate_selected_records",
        "revision": "0" * 64,
        "record_count": len(records),
        "edge_count": len(resolved_edges),
        "kind_counts": dict(sorted(counts.items())),
        "records": list(records.values()),
        "edges": [
            dict(source=source, target=target, relation=relation)
            for source, target, relation in resolved_edges
        ],
    }
    # Bound the complete final framing before sorting or hashing expanded data.
    # Sorting and replacing the fixed-width revision preserve its encoded size.
    bounded_json_text(result, max_bytes=8 * _MIB - 1)
    ordered_records = sorted(
        records.values(), key=lambda item: (item["kind"], item["id"])
    )
    ordered_edges = [
        {"source": source, "target": target, "relation": relation}
        for source, target, relation in sorted(resolved_edges)
    ]
    material = {"records": ordered_records, "edges": ordered_edges}
    revision = stable_hash(material)
    result.update(revision=revision, records=ordered_records, edges=ordered_edges)
    return result


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
        if edge["source"] not in known
        or (
            not edge["target"].startswith("unresolved:") and edge["target"] not in known
        )
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
