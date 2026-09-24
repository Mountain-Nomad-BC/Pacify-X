from __future__ import annotations

from pathlib import Path

from runtime.semantic_code_export import semantic_index_payload, write_semantic_index
from runtime.semantic_code_index import build_semantic_project_index


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_export_is_marked_derived_and_deterministic(tmp_path: Path):
    index = build_semantic_project_index(FIXTURE)
    payload = semantic_index_payload(index)
    assert payload["authority"] == "derived_non_authoritative"
    left = write_semantic_index(index, tmp_path / "left.json").read_bytes()
    right = write_semantic_index(index, tmp_path / "right.json").read_bytes()
    assert left == right
