from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime.knowledge_foundry import SourceArtifact, compile_foundry_bundle, materialize_candidate_bundle
from runtime.nsai_knowledge import validate_nsai_object_payload

ROOT = Path(__file__).resolve().parents[1]


def source(source_id: str, text: str) -> SourceArtifact:
    return SourceArtifact(
        source_id=source_id,
        source_kind="engineering_note",
        locator=f"docs/{source_id}.md",
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        license="internal-reference",
    )


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_foundry_materializes_one_valid_json_object_per_knowledge_item(tmp_path: Path) -> None:
    bundle = compile_foundry_bundle((source("one", "# Routing\nValidate routing evidence before promotion."),))
    receipt = materialize_candidate_bundle(bundle, tmp_path)
    root = tmp_path / bundle.bundle_id
    assert receipt["knowledge_storage"] == "one_json_object_per_file"
    assert not (root / "knowledge.json").exists()
    paths = sorted((root / "knowledge" / "objects").rglob("*.json"))
    assert len(paths) == len(bundle.knowledge)
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_nsai_object_payload(payload, contract_root=ROOT / "contracts")
        assert payload["authority_granted"] is False
    derived = json.loads((root / "knowledge" / "index.json").read_text(encoding="utf-8"))
    assert derived["authority"] == "derived_navigation_only"
    assert len(derived["records"]) == len(paths)


def test_second_materialization_to_different_root_is_byte_stable(tmp_path: Path) -> None:
    bundle = compile_foundry_bundle((source("one", "Generate and validate bounded evidence."),))
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir(); right.mkdir()
    materialize_candidate_bundle(bundle, left)
    materialize_candidate_bundle(bundle, right)
    assert tree_bytes(left / bundle.bundle_id) == tree_bytes(right / bundle.bundle_id)


def test_source_artifact_from_absolute_path_materializes_portable_provenance(tmp_path: Path) -> None:
    source_path = tmp_path / "source.md"
    source_path.write_text("Validate bounded source evidence.\n", encoding="utf-8")
    artifact = SourceArtifact.from_path(source_path)
    assert artifact.locator == "source.md"
    bundle = compile_foundry_bundle((artifact,))
    destination = tmp_path / "out"
    destination.mkdir()
    materialize_candidate_bundle(bundle, destination)
    objects = list((destination / bundle.bundle_id / "knowledge" / "objects").rglob("*.json"))
    assert objects
    payload = json.loads(objects[0].read_text(encoding="utf-8"))
    assert payload["provenance"]["sources"][0]["path"] == "source.md"
