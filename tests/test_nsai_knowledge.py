from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from runtime.cognitive_core.index_builder import build_cognitive_index
from runtime.knowledge_refinery import nsai_candidate_records
from runtime.nsai_knowledge import (
    audit_nsai_library,
    build_nsai_index,
    expected_object_relative_path,
    load_nsai_object,
    pretty_json_bytes,
    validate_nsai_object_payload,
    write_nsai_index,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def knowledge_object(*, slug: str = "sample", status: str = "candidate") -> dict[str, object]:
    return {
        "schema_version": "px.nsai-knowledge/1.0",
        "object_id": f"nsai:test:concept:{slug}",
        "object_type": "concept",
        "namespace": "test",
        "title": "Sample knowledge",
        "status": status,
        "semantics": {
            "definition": "A bounded sample concept.",
            "short_description": "Sample concept",
            "retrieval_text": "sample bounded concept retrieval",
            "keywords": ["sample"],
            "intents": ["inspect"],
            "synonyms": ["example"],
            "exclusions": [],
        },
        "ontology": {"classes": ["concept"], "facets": {"domain": "test"}},
        "applicability": {"targets": ["px"], "conditions": [], "exclusions": []},
        "content": {
            "summary": "A sample knowledge object.",
            "claims": [
                {
                    "claim_id": "primary",
                    "statement": "The sample is bounded.",
                    "confidence": 0.8,
                    "evidence_refs": ["source-a"],
                }
            ],
            "mechanisms": [],
            "formula_refs": [],
            "notes": [],
        },
        "relationships": [],
        "provenance": {
            "sources": [
                {
                    "source_id": "source-a",
                    "kind": "engineering_note",
                    "archive": "source.zip",
                    "path": "docs/source.md",
                    "sha256": "a" * 64,
                    "license": "internal-reference",
                }
            ],
            "extraction": {
                "method": "test",
                "generated_by": "tests/test_nsai_knowledge.py",
                "source_pass": "unit",
            },
        },
        "retrieval": {"tags": ["test"], "terms": ["bounded"], "priority": 50},
        "authority_granted": False,
    }


def formula_object(*, slug: str = "gain") -> dict[str, object]:
    base = knowledge_object(slug=slug)
    base["schema_version"] = "px.nsai-formula/1.0"
    base["object_id"] = f"nsai:test:formula:{slug}"
    base["object_type"] = "formula"
    base["ontology"] = {"classes": ["formula"], "facets": {"domain": "test"}}
    base["formula"] = {
        "formula_type": "explicit_equation",
        "verbatim_expression": "y = k*x",
        "normalized_expression": "y=k*x",
        "variables": [
            {"symbol": "x", "role": "input", "definition": "input", "units": "1", "dimensions": "1"},
            {"symbol": "y", "role": "output", "definition": "output", "units": "1", "dimensions": "1"},
            {"symbol": "k", "role": "parameter", "definition": "gain", "units": "1", "dimensions": "1"},
        ],
        "parameters": ["k"],
        "constants": [],
        "inputs": ["x"],
        "outputs": ["y"],
        "assumptions": ["dimensionless example"],
        "constraints": [],
        "time_basis": "not applicable",
        "dynamics": "not_applicable",
        "determinism": "deterministic",
        "linearity": "linear",
    }
    base["content"].pop("formula_refs")
    return base


def write_object(library: Path, payload: dict[str, object]) -> Path:
    relative = expected_object_relative_path(payload)
    target = library / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pretty_json_bytes(payload))
    return target


def test_knowledge_and_formula_contracts_accept_single_objects() -> None:
    validate_nsai_object_payload(knowledge_object(), contract_root=CONTRACTS)
    validate_nsai_object_payload(formula_object(), contract_root=CONTRACTS)


def test_identity_fields_and_path_are_semantically_bound(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    payload = knowledge_object()
    path = write_object(library, payload)
    loaded = load_nsai_object(path, library_root=library, contract_root=CONTRACTS)
    assert loaded.payload["object_id"] == payload["object_id"]
    wrong = library / "objects" / "test" / "wrong.json"
    wrong.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="path disagrees"):
        load_nsai_object(wrong, library_root=library, contract_root=CONTRACTS)


def test_authority_and_generated_vector_fields_are_not_admitted() -> None:
    payload = knowledge_object()
    payload["authority_granted"] = True
    with pytest.raises(ValueError):
        validate_nsai_object_payload(payload, contract_root=CONTRACTS)
    payload = knowledge_object()
    payload["embedding"] = [0.1, 0.2]
    with pytest.raises(ValueError):
        validate_nsai_object_payload(payload, contract_root=CONTRACTS)


def test_provenance_paths_are_relative_and_claim_confidence_is_finite() -> None:
    payload = knowledge_object()
    payload["provenance"]["sources"][0]["path"] = "../escape.md"
    with pytest.raises(ValueError, match="relative locator"):
        validate_nsai_object_payload(payload, contract_root=CONTRACTS)
    payload = knowledge_object()
    payload["content"]["claims"][0]["confidence"] = float("nan")
    with pytest.raises(ValueError):
        validate_nsai_object_payload(payload, contract_root=CONTRACTS)


def test_internal_cross_references_must_resolve(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    payload = knowledge_object()
    payload["relationships"] = [
        {"predicate": "depends_on", "target_id": "nsai:test:concept:missing", "scope": "library"}
    ]
    write_object(library, payload)
    with pytest.raises(ValueError, match="unresolved_library_relationship"):
        build_nsai_index(library, contract_root=CONTRACTS)


def test_formula_refs_must_resolve_to_formula_objects(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    formula = formula_object()
    write_object(library, formula)
    concept = knowledge_object()
    concept["content"]["formula_refs"] = [formula["object_id"]]
    write_object(library, concept)
    index = build_nsai_index(library, contract_root=CONTRACTS)
    assert index["formula_count"] == 1
    assert index["object_count"] == 2


def test_index_is_deterministic_derived_navigation_only(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    write_object(library, knowledge_object(slug="b"))
    write_object(library, knowledge_object(slug="a"))
    first = write_nsai_index(library, contract_root=CONTRACTS)
    first_bytes = (library / "index.json").read_bytes()
    second = write_nsai_index(library, contract_root=CONTRACTS)
    assert first == second
    assert (library / "index.json").read_bytes() == first_bytes
    assert first["authority"] == "derived_navigation_only"
    assert [row["object_id"] for row in first["records"]] == sorted(row["object_id"] for row in first["records"])


def test_stale_index_is_detected_but_objects_remain_source_truth(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    write_object(library, knowledge_object())
    write_nsai_index(library, contract_root=CONTRACTS)
    (library / "index.json").write_text("{}\n", encoding="utf-8")
    audit = audit_nsai_library(library, contract_root=CONTRACTS, require_index_match=True)
    assert audit["valid"] is False and audit["errors"] == ["derived_index_stale"]
    assert build_nsai_index(library, contract_root=CONTRACTS)["object_count"] == 1


def test_jsonl_and_non_json_files_are_rejected(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    target = library / "objects" / "test" / "bad.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-JSON"):
        build_nsai_index(library, contract_root=CONTRACTS)


def test_refinery_projection_preserves_nsai_identity_without_authority(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    payload = knowledge_object(status="validated")
    path = write_object(library, payload)
    rows = nsai_candidate_records(library, contract_root=CONTRACTS)
    assert len(rows) == 1
    assert rows[0]["id"] == payload["object_id"]
    assert rows[0]["nsai_object_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert rows[0]["authority_granted"] is False


def test_cognitive_index_reads_object_files_not_derived_nsai_index(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    payload = knowledge_object()
    write_object(library, payload)
    library.mkdir(parents=True, exist_ok=True)
    (library / "index.json").write_text(json.dumps({"records": [{"object_id": "nsai:fake:concept:fake"}]}), encoding="utf-8")
    index = build_cognitive_index(tmp_path)
    ids = {row["id"] for row in index["records"]}
    assert payload["object_id"] in ids
    assert "nsai:fake:concept:fake" not in ids


def test_index_must_match_canonical_pretty_bytes(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    write_object(library, knowledge_object())
    index = write_nsai_index(library, contract_root=CONTRACTS)
    # Semantically equal but noncanonical compact bytes are considered stale.
    (library / "index.json").write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
    audit = audit_nsai_library(library, contract_root=CONTRACTS, require_index_match=True)
    assert audit["valid"] is False
    assert audit["errors"] == ["derived_index_stale"]


def test_external_relationships_may_remain_unresolved(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    payload = knowledge_object()
    payload["relationships"] = [
        {"predicate": "references", "target_id": "nsai:external:concept:outside", "scope": "external"}
    ]
    write_object(library, payload)
    assert build_nsai_index(library, contract_root=CONTRACTS)["object_count"] == 1


def test_single_object_file_rejects_json_arrays(tmp_path: Path) -> None:
    library = tmp_path / "knowledge" / "nsai"
    target = library / "objects" / "test" / "sample.json"
    target.parent.mkdir(parents=True)
    target.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_nsai_object(target, library_root=library, contract_root=CONTRACTS)
