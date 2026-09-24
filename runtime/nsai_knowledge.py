"""Deterministic NSAI single-object knowledge-file support.

This module validates and projects knowledge. It does not retrieve, promote,
execute, or grant authority. Individual JSON object files are the source
artifacts; ``knowledge/nsai/index.json`` is a disposable derived projection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Iterable, Mapping, Sequence

from .archive_io import reject_path_links
from .bounded_walk import WalkLimits, bounded_walk
from .contracts import ContractValidationError, validate_instance
from .json_io import decode_json_object, validate_json_value

KNOWLEDGE_SCHEMA_VERSION = "px.nsai-knowledge/1.0"
FORMULA_SCHEMA_VERSION = "px.nsai-formula/1.0"
INDEX_SCHEMA_VERSION = "px.nsai-index/1.0"
OBJECT_ID = re.compile(
    r"^nsai:([a-z0-9_.-]+):([a-z][a-z0-9_.-]*):([a-z0-9][a-z0-9_.-]*)$"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_OBJECT_BYTES = 1024 * 1024
MAX_OBJECTS = 10000
MAX_LIBRARY_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NsaiObjectFile:
    path: Path
    relative_path: str
    sha256: str
    payload: Mapping[str, object]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _contract_root(contract_root: Path | None = None) -> Path:
    root = (contract_root or (_repo_root() / "contracts")).resolve(strict=True)
    reject_path_links(root)
    return root


def _schema_path(payload: Mapping[str, object], contract_root: Path) -> Path:
    name = (
        "formula-object.schema.json"
        if payload.get("object_type") == "formula"
        else "knowledge-object.schema.json"
    )
    return contract_root / "nsai" / name


def canonical_json_bytes(value: object) -> bytes:
    validate_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    validate_json_value(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def stable_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def parse_object_id(value: object) -> tuple[str, str, str]:
    if type(value) is not str:
        raise ValueError("NSAI object_id must be a string")
    match = OBJECT_ID.fullmatch(value)
    if not match:
        raise ValueError("invalid NSAI object_id")
    return match.group(1), match.group(2), match.group(3)


def expected_object_relative_path(payload: Mapping[str, object]) -> Path:
    namespace, object_type, slug = parse_object_id(payload.get("object_id"))
    if payload.get("namespace") != namespace or payload.get("object_type") != object_type:
        raise ValueError("NSAI object_id namespace/type disagree with object fields")
    return Path("objects") / namespace / f"{slug}.json"


def _safe_source_path(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 4096:
        raise ValueError("NSAI provenance path must be bounded non-empty text")
    text = value.replace("\\", "/")
    if (
        Path(text).is_absolute()
        or PurePosixPath(text).is_absolute()
        or PureWindowsPath(text).is_absolute()
        or any(part in {"", ".", ".."} for part in PurePosixPath(text).parts)
    ):
        raise ValueError("NSAI provenance path must be a normalized relative locator")
    return PurePosixPath(text).as_posix()


def _semantic_checks(payload: Mapping[str, object]) -> None:
    namespace, object_type, _ = parse_object_id(payload.get("object_id"))
    if payload.get("namespace") != namespace or payload.get("object_type") != object_type:
        raise ValueError("NSAI object identity fields disagree")
    expected_version = (
        FORMULA_SCHEMA_VERSION if object_type == "formula" else KNOWLEDGE_SCHEMA_VERSION
    )
    if payload.get("schema_version") != expected_version:
        raise ValueError("NSAI schema_version does not match object_type")
    if payload.get("authority_granted") is not False:
        raise ValueError("NSAI knowledge objects cannot grant authority")

    claims = payload.get("content", {}).get("claims", ())
    claim_ids: set[str] = set()
    for claim in claims:
        claim_id = claim["claim_id"]
        if claim_id in claim_ids:
            raise ValueError("duplicate NSAI claim_id")
        claim_ids.add(claim_id)
        confidence = claim["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("NSAI claim confidence must be numeric")
        if not math.isfinite(float(confidence)):
            raise ValueError("NSAI claim confidence must be finite")

    source_ids: set[str] = set()
    source_locators: set[tuple[str, str]] = set()
    for source in payload["provenance"]["sources"]:
        source_id = source["source_id"]
        path = _safe_source_path(source["path"])
        if source_id in source_ids:
            raise ValueError("duplicate NSAI provenance source_id")
        key = (str(source.get("archive", "")), path.casefold())
        if key in source_locators:
            raise ValueError("duplicate NSAI provenance source locator")
        if not SHA256.fullmatch(source["sha256"]):
            raise ValueError("invalid NSAI provenance sha256")
        source_ids.add(source_id)
        source_locators.add(key)

    relation_keys: set[tuple[str, str, str]] = set()
    for relation in payload.get("relationships", ()):
        parse_object_id(relation["target_id"])
        key = (relation["predicate"], relation["target_id"], relation["scope"])
        if key in relation_keys:
            raise ValueError("duplicate NSAI relationship")
        relation_keys.add(key)

    for formula_id in payload.get("content", {}).get("formula_refs", ()):
        _, referred_type, _ = parse_object_id(formula_id)
        if referred_type != "formula":
            raise ValueError("NSAI formula_refs must target formula object IDs")


def validate_nsai_object_payload(
    payload: Mapping[str, object], *, contract_root: Path | None = None
) -> None:
    if type(payload) is not dict:
        raise ValueError("NSAI knowledge file must contain one JSON object")
    contracts = _contract_root(contract_root)
    schema = _schema_path(payload, contracts)
    try:
        validate_instance(payload, schema, contract_root=contracts)
    except ContractValidationError as error:
        raise ValueError(str(error)) from error
    _semantic_checks(payload)


def _library_root(root: Path) -> Path:
    reject_path_links(root)
    resolved = root.resolve(strict=True)
    reject_path_links(resolved)
    objects = resolved / "objects"
    if objects.exists():
        reject_path_links(objects)
        if not objects.is_dir():
            raise ValueError("NSAI objects path must be a directory")
    return resolved


def discover_nsai_object_paths(root: Path) -> tuple[Path, ...]:
    library = _library_root(root)
    objects = library / "objects"
    if not objects.exists():
        return ()
    walked = bounded_walk(
        objects,
        limits=WalkLimits(
            max_files=MAX_OBJECTS,
            max_depth=8,
            max_bytes=MAX_LIBRARY_BYTES,
            max_entries=MAX_OBJECTS * 4,
            max_directories=MAX_OBJECTS,
        ),
        symlink_policy="reject",
    )
    paths: list[Path] = []
    for item in walked.files:
        if item.path.suffix.casefold() != ".json":
            raise ValueError(f"non-JSON file inside NSAI object tree: {item.relative}")
        if item.size > MAX_OBJECT_BYTES:
            raise ValueError(f"NSAI object exceeds per-file byte limit: {item.relative}")
        paths.append(item.path)
    return tuple(sorted(paths, key=lambda path: path.relative_to(library).as_posix()))


def load_nsai_object(
    path: Path,
    *,
    library_root: Path,
    contract_root: Path | None = None,
) -> NsaiObjectFile:
    library = _library_root(library_root)
    reject_path_links(path)
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(library).as_posix()
    except ValueError as error:
        raise ValueError("NSAI object escapes the declared library root") from error
    if not relative.startswith("objects/") or resolved.suffix.casefold() != ".json":
        raise ValueError("NSAI source object must live under objects/ as JSON")
    raw = resolved.read_bytes()
    if len(raw) > MAX_OBJECT_BYTES:
        raise ValueError("NSAI object exceeds per-file byte limit")
    payload = decode_json_object(
        raw, max_bytes=MAX_OBJECT_BYTES, max_depth=48, max_nodes=200000
    )
    validate_nsai_object_payload(payload, contract_root=contract_root)
    expected = expected_object_relative_path(payload).as_posix()
    if relative != expected:
        raise ValueError(
            f"NSAI object path disagrees with semantic identity: {relative} != {expected}"
        )
    return NsaiObjectFile(
        path=resolved,
        relative_path=relative,
        sha256=hashlib.sha256(raw).hexdigest(),
        payload=payload,
    )


def _cross_reference_errors(objects: Sequence[NsaiObjectFile]) -> list[str]:
    by_id = {item.payload["object_id"]: item for item in objects}
    errors: list[str] = []
    if len(by_id) != len(objects):
        seen: set[str] = set()
        for item in objects:
            object_id = str(item.payload["object_id"])
            if object_id in seen:
                errors.append(f"duplicate_object_id:{object_id}")
            seen.add(object_id)
    for item in objects:
        payload = item.payload
        object_id = str(payload["object_id"])
        for relation in payload.get("relationships", ()):
            if relation["scope"] == "library" and relation["target_id"] not in by_id:
                errors.append(
                    f"unresolved_library_relationship:{object_id}:{relation['target_id']}"
                )
        for formula_id in payload.get("content", {}).get("formula_refs", ()):
            target = by_id.get(formula_id)
            if target is None:
                errors.append(f"unresolved_formula_ref:{object_id}:{formula_id}")
            elif target.payload.get("object_type") != "formula":
                errors.append(f"formula_ref_not_formula:{object_id}:{formula_id}")
    return sorted(set(errors))


def read_nsai_library(
    root: Path, *, contract_root: Path | None = None
) -> tuple[NsaiObjectFile, ...]:
    library = _library_root(root)
    objects = tuple(
        load_nsai_object(path, library_root=library, contract_root=contract_root)
        for path in discover_nsai_object_paths(library)
    )
    errors = _cross_reference_errors(objects)
    if errors:
        raise ValueError("; ".join(errors))
    return objects


def build_nsai_index(
    root: Path, *, contract_root: Path | None = None
) -> dict[str, object]:
    library = _library_root(root)
    objects = read_nsai_library(library, contract_root=contract_root)
    records: list[dict[str, object]] = []
    formula_count = 0
    for item in objects:
        payload = item.payload
        if payload["object_type"] == "formula":
            formula_count += 1
        semantics = payload["semantics"]
        ontology = payload["ontology"]
        retrieval = payload["retrieval"]
        records.append(
            {
                "object_id": payload["object_id"],
                "object_type": payload["object_type"],
                "namespace": payload["namespace"],
                "title": payload["title"],
                "status": payload["status"],
                "path": item.relative_path,
                "sha256": item.sha256,
                "classes": sorted(ontology["classes"]),
                "tags": sorted(retrieval["tags"]),
                "terms": sorted(
                    set(retrieval["terms"])
                    | set(semantics["keywords"])
                    | set(semantics["synonyms"])
                ),
                "relationship_targets": sorted(
                    {relation["target_id"] for relation in payload["relationships"]}
                ),
                "source_ids": sorted(
                    {source["source_id"] for source in payload["provenance"]["sources"]}
                ),
            }
        )
    records.sort(key=lambda row: row["object_id"])
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "authority": "derived_navigation_only",
        "source_of_truth": "individual_object_files",
        "object_count": len(records),
        "formula_count": formula_count,
        "records": records,
    }
    payload["library_sha256"] = stable_sha256(payload)
    return payload


def write_nsai_index(
    root: Path, *, contract_root: Path | None = None
) -> dict[str, object]:
    library = _library_root(root)
    payload = build_nsai_index(library, contract_root=contract_root)
    target = library / "index.json"
    reject_path_links(target)
    raw = pretty_json_bytes(payload)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(target)
    return payload


def audit_nsai_library(
    root: Path,
    *,
    contract_root: Path | None = None,
    require_index_match: bool = True,
) -> dict[str, object]:
    library = _library_root(root)
    errors: list[str] = []
    try:
        generated = build_nsai_index(library, contract_root=contract_root)
    except (OSError, ValueError) as error:
        return {
            "valid": False,
            "object_count": 0,
            "formula_count": 0,
            "errors": [str(error)],
            "index_matches": False,
            "canonical_writes_performed": False,
        }
    index_matches = True
    index_path = library / "index.json"
    if require_index_match:
        if not index_path.is_file():
            errors.append("derived_index_missing")
            index_matches = False
        else:
            try:
                current_bytes = index_path.read_bytes()
                decode_json_object(
                    current_bytes,
                    max_bytes=MAX_OBJECT_BYTES,
                    max_depth=48,
                    max_nodes=200000,
                )
                index_matches = current_bytes == pretty_json_bytes(generated)
            except (OSError, ValueError):
                index_matches = False
            if not index_matches:
                errors.append("derived_index_stale")
    return {
        "valid": not errors,
        "object_count": int(generated["object_count"]),
        "formula_count": int(generated["formula_count"]),
        "library_sha256": generated["library_sha256"],
        "errors": errors,
        "index_matches": index_matches,
        "canonical_writes_performed": False,
    }


def nsai_to_refinery_record(item: NsaiObjectFile) -> dict[str, object]:
    payload = item.payload
    semantics = payload["semantics"]
    content = payload["content"]
    ontology = payload["ontology"]
    formula = payload.get("formula", {})
    mechanisms = [row["name"] for row in content.get("mechanisms", ())]
    inputs = list(formula.get("inputs", ())) if payload["object_type"] == "formula" else []
    outputs = list(formula.get("outputs", ())) if payload["object_type"] == "formula" else []
    return {
        "id": payload["object_id"],
        "title": payload["title"],
        "description": content["summary"],
        "aliases": list(semantics["synonyms"]),
        "capabilities": list(ontology["classes"]),
        "mechanisms": mechanisms,
        "inputs": inputs,
        "outputs": outputs,
        "failure_modes": list(payload["applicability"]["exclusions"]),
        "invariants": list(payload["applicability"]["conditions"]),
        "evidence_quality": max(
            (float(claim["confidence"]) for claim in content.get("claims", ())),
            default=0.5,
        ),
        "validation_coverage": 1.0 if payload["status"] in {"validated", "authoritative"} else 0.5,
        "nsai_object_sha256": item.sha256,
        "nsai_object_path": item.relative_path,
        "nsai_status": payload["status"],
        "authority_granted": False,
    }


def foundry_knowledge_payload(
    *,
    object_slug: str,
    object_type: str,
    statement: str,
    evidence_refs: Iterable[str],
    relationships: Iterable[str],
    confidence: float,
    source_records: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    if not (0.0 <= float(confidence) <= 1.0) or not math.isfinite(float(confidence)):
        raise ValueError("foundry knowledge confidence must be finite in [0,1]")
    safe_type = re.sub(r"[^a-z0-9_.-]+", "-", object_type.casefold()).strip("-") or "concept"
    slug = re.sub(r"[^a-z0-9_.-]+", "-", object_slug.casefold()).strip("-")
    object_id = f"nsai:foundry:{safe_type}:{slug}"
    source_ids = sorted(set(map(str, evidence_refs)))
    sources = []
    for source_id in source_ids:
        source = source_records.get(source_id)
        if source is None:
            raise ValueError(f"foundry knowledge references unknown source: {source_id}")
        entry = {
            "source_id": source_id,
            "kind": str(source["source_kind"]),
            "path": str(source["locator"]),
            "sha256": str(source["sha256"]),
        }
        for source_key, target_key in (
            ("version", "version"),
            ("license", "license"),
            ("citation", "citation"),
        ):
            if source.get(source_key):
                entry[target_key] = str(source[source_key])
        sources.append(entry)
    relationship_rows = []
    for relation in sorted(set(map(str, relationships))):
        relation_slug = re.sub(r"[^a-z0-9_.-]+", "-", relation.casefold()).strip("-")
        if relation_slug:
            relationship_rows.append(
                {
                    "predicate": "references",
                    "target_id": f"nsai:external:concept:{relation_slug}",
                    "scope": "external",
                }
            )
    payload = {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "object_id": object_id,
        "object_type": safe_type,
        "namespace": "foundry",
        "title": statement[:160],
        "status": "candidate",
        "semantics": {
            "definition": statement,
            "short_description": statement[:240],
            "retrieval_text": statement,
            "keywords": [],
            "intents": [],
            "synonyms": [],
            "exclusions": [],
        },
        "ontology": {"classes": [safe_type], "facets": {"origin": "knowledge_foundry"}},
        "applicability": {"targets": [], "conditions": [], "exclusions": []},
        "content": {
            "summary": statement,
            "claims": [
                {
                    "claim_id": "primary",
                    "statement": statement,
                    "confidence": round(float(confidence), 6),
                    "evidence_refs": source_ids,
                }
            ],
            "mechanisms": [],
            "formula_refs": [],
            "notes": [],
        },
        "relationships": relationship_rows,
        "provenance": {
            "sources": sources,
            "extraction": {
                "method": "px.knowledge-foundry.statement-normalization/1.0",
                "generated_by": "runtime/knowledge_foundry.py",
                "source_pass": "candidate",
            },
        },
        "retrieval": {"tags": [safe_type, "foundry"], "terms": [], "priority": 50},
        "authority_granted": False,
    }
    validate_nsai_object_payload(payload)
    return payload
