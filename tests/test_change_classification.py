from __future__ import annotations

import pytest

from runtime.change_classification import ChangeClass, classify_changes


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("docs/guide.md", "DOC_ONLY"),
        ("registry/catalog.json", "METADATA_ONLY"),
        (".px/skills/example/SKILL.md", "SEMANTIC"),
        ("tests/test_example.py", "BEHAVIORAL"),
        ("contracts/example.schema.json", "SCHEMA"),
        ("registry/primitive_authority.json", "AUTHORITY"),
        ("runtime/example.py", "RUNTIME"),
        ("extension/package.json", "RELEASE_CRITICAL"),
    ),
)
def test_every_change_class_boundary(path: str, expected: str) -> None:
    assert classify_changes([{"path": path}])["change_class"] == expected
    assert ChangeClass[expected].name == expected


def test_runtime_cannot_be_classified_doc_only() -> None:
    with pytest.raises(ValueError, match="cannot reduce"):
        classify_changes(
            [
                {
                    "path": "runtime/example.py",
                    "override_class": "DOC_ONLY",
                    "override_evidence": {
                        "reference": "review.json",
                        "sha256": "a" * 64,
                        "approved_by": "reviewer",
                        "rationale": "claimed docs only",
                    },
                }
            ]
        )


def test_unknown_and_mixed_changes_preserve_highest_risk() -> None:
    result = classify_changes(
        [{"path": "docs/readme.md"}, {"path": "unknown.binary"}]
    )
    assert result["mixed"] is True
    assert result["change_class"] == "RELEASE_CRITICAL"


def test_evidence_bound_override_can_only_increase_risk() -> None:
    result = classify_changes(
        [
            {
                "path": "docs/readme.md",
                "override_class": "SCHEMA",
                "override_evidence": {
                    "reference": "review.json",
                    "sha256": "a" * 64,
                    "approved_by": "reviewer",
                    "rationale": "document defines an external schema",
                },
            }
        ]
    )
    assert result["change_class"] == "SCHEMA"


def test_conflicting_override_fails_closed() -> None:
    with pytest.raises(ValueError, match="conflicting"):
        classify_changes(
            [{"path": "docs/readme.md", "override_class": ["DOC_ONLY", "SCHEMA"]}]
        )
