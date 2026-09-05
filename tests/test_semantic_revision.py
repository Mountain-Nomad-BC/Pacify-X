from __future__ import annotations

import pytest

from runtime.semantic_revision import (
    CANONICALIZER_REVISION,
    compute_semantic_revision,
)


@pytest.mark.parametrize(
    ("artifact_type", "left", "right"),
    (
        (".json", '{"a":1,"b":[2]}', '{\n  "b": [2], "a": 1\n}'),
        ("config.yaml", "a: 1\nb:\n - 2\n", "b: [2]\na: 1\n"),
        ("module.py", "value=1\n", "value = 1  # formatting only\n"),
    ),
)
def test_supported_format_separates_byte_and_semantic_identity(
    artifact_type: str, left: str, right: str
) -> None:
    first = compute_semantic_revision(left, artifact_type=artifact_type)
    second = compute_semantic_revision(right, artifact_type=artifact_type)
    assert first.byte_revision != second.byte_revision
    assert first.semantic_revision == second.semantic_revision
    assert first.semantic_supported
    assert first.canonicalizer_revision == CANONICALIZER_REVISION


def test_behavioral_change_changes_semantic_revision() -> None:
    first = compute_semantic_revision("value = 1\n", artifact_type="x.py")
    second = compute_semantic_revision("value = 2\n", artifact_type="x.py")
    assert first.semantic_revision != second.semantic_revision


def test_unsupported_format_uses_byte_revision_without_guessing() -> None:
    result = compute_semantic_revision(b"opaque\x00bytes", artifact_type="artifact.bin")
    assert not result.semantic_supported
    assert result.semantic_revision is None
    assert result.effective_revision == result.byte_revision
    assert result.canonicalizer is None


def test_invalid_supported_content_fails_closed() -> None:
    with pytest.raises(ValueError):
        compute_semantic_revision("{not json", artifact_type=".json")
