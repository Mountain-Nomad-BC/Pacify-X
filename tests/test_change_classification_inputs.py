"""Prepared causal cases; install only after the classification slice is admitted."""

import pytest

from runtime.change_classification import classify_changes


@pytest.mark.parametrize(
    "path,effects",
    [
        ("policies/authority.json", ["write"]),
        ("contracts/item.schema.json", ["write"]),
        ("runtime/authority.py", []),
    ],
)
def test_classification_joins_all_impacts_at_maximum_severity(path, effects):
    result = classify_changes([{"path": path, "effects": effects}])
    assert result["change_class"] == "RUNTIME"


def test_conversion_document_is_not_a_release_version_marker():
    assert (
        classify_changes([{"path": "docs/conversion.md"}])["change_class"] == "DOC_ONLY"
    )


@pytest.mark.parametrize(
    "record",
    [
        {"path": "docs/guide.md", "effects": "write"},
        {"path": "docs/guide.md", "symbols": {"hidden": "symbol"}},
        {"path": 7},
        {"path": "docs/guide.md", "effects": [False]},
    ],
)
def test_malformed_metadata_is_not_silently_coerced(record):
    with pytest.raises(ValueError):
        classify_changes([record])


@pytest.mark.parametrize(
    "path",
    [
        "../runtime/hidden.py",
        "docs/../runtime/hidden.py",
        "./runtime/hidden.py",
        "C:/outside.py",
        "docs/guide.md:stream",
    ],
)
def test_unsafe_path_spelling_cannot_lower_proof(path):
    with pytest.raises(ValueError):
        classify_changes([{"path": path}])


def test_opaque_approver_cannot_become_override_evidence():
    with pytest.raises(ValueError):
        classify_changes(
            [
                {
                    "path": "docs/guide.md",
                    "override_class": "SCHEMA",
                    "override_evidence": {
                        "reference": "review.json",
                        "sha256": "a" * 64,
                        "approved_by": {"who": "unknown"},
                        "rationale": "Review request",
                    },
                }
            ]
        )


def test_supplied_root_cannot_hide_an_original_junction(tmp_path):
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "guide.md").write_text("external", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    linked = root / "docs"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(linked))
    else:
        linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        classify_changes([{"path": "docs/guide.md"}], root=root)


def test_deleted_contained_locator_remains_classifiable(tmp_path):
    result = classify_changes([{"path": "runtime/deleted.py"}], root=tmp_path)
    assert result["change_class"] == "RUNTIME"
    assert result["diff_verified"] is False


def test_metadata_only_classification_does_not_claim_an_observed_diff():
    result = classify_changes([{"path": "docs/guide.md"}])
    assert result["diff_verified"] is False


@pytest.mark.parametrize(
    "paths",
    [
        ("docs/guide.md", "docs/guide.md"),
        ("docs/guide.md", "DOCS/GUIDE.MD"),
        ("docs/guide.md", "docs\\guide.md"),
        ("docs/caf\u00e9.md", "docs/cafe\u0301.md"),
    ],
    ids=["duplicate", "case", "separators", "unicode"],
)
def test_portable_path_aliases_cannot_drop_an_impact(paths):
    with pytest.raises(ValueError):
        classify_changes([{"path": paths[0]}, {"path": paths[1], "effects": ["write"]}])


@pytest.mark.parametrize(
    "path",
    [
        "VERSION",
        "registry/product-version.json",
        "release_identity.py",
        "extension/package-lock.json",
        "artifacts/product.vsix",
    ],
)
def test_exact_release_markers_remain_conservative(path):
    assert classify_changes([{"path": path}])["change_class"] == "RELEASE_CRITICAL"


def test_oversized_row_set_rejects_before_root_inspection(tmp_path, monkeypatch):
    import runtime.change_classification as classification

    def forbidden(*args):
        pytest.fail("oversized row set reached filesystem inspection")

    monkeypatch.setattr(classification, "reject_path_links", forbidden, raising=False)
    with pytest.raises(ValueError):
        classify_changes([{"path": "docs/guide.md"}] * 10001, root=tmp_path / "absent")


def test_declared_override_is_not_reported_as_verified_approval():
    result = classify_changes(
        [
            {
                "path": "docs/guide.md",
                "override_class": "SCHEMA",
                "override_evidence": {
                    "reference": "review.json",
                    "sha256": "a" * 64,
                    "approved_by": "reviewer",
                    "rationale": "Declared schema impact",
                },
            }
        ]
    )
    assert result["records"][0]["override_evidence_verified"] is False


def test_declared_effect_remains_visible_alongside_authority_reason():
    result = classify_changes(
        [{"path": "policies/admission.json", "effects": ["write"]}]
    )
    assert {"authority_or_policy_surface", "declared_effect_surface"} <= set(
        result["records"][0]["inferred_reasons"]
    )


def test_aggregate_metadata_refuses_before_classification(monkeypatch):
    import runtime.change_classification as classification

    def forbidden(*args):
        pytest.fail("oversized metadata reached classification")

    monkeypatch.setattr(classification, "_infer", forbidden)
    labels = [str(i) + "x" * 490 for i in range(256)]
    records = [{"path": "docs/" + str(i) + ".md", "symbols": labels} for i in range(80)]
    with pytest.raises(ValueError):
        classify_changes(records)


@pytest.mark.parametrize(
    "extra",
    [
        {"effects": ["write", "write"]},
        {"surprise": True},
        {"override_evidence": {"reference": "unused"}},
    ],
    ids=["duplicate-label", "unknown-field", "orphan-evidence"],
)
def test_incomplete_or_ambiguous_metadata_does_not_disappear(extra):
    with pytest.raises(ValueError):
        classify_changes([{"path": "docs/guide.md", **extra}])


def test_release_critical_remains_above_all_other_impacts():
    result = classify_changes(
        [
            {
                "path": "runtime/release_identity.py",
                "effects": ["write"],
                "symbols": ["identity"],
            }
        ]
    )
    assert result["change_class"] == "RELEASE_CRITICAL"


@pytest.mark.parametrize(
    "metadata",
    [{"symbols": ["changed"]}, {"effects": ["write"]}],
    ids=["symbol", "effect"],
)
def test_unknown_path_cannot_gain_lower_risk_from_metadata(metadata):
    assert (
        classify_changes([{"path": "unknown.binary", **metadata}])["change_class"]
        == "RELEASE_CRITICAL"
    )


def test_supplied_root_is_bounded_before_component_inspection(tmp_path, monkeypatch):
    import runtime.change_classification as classification

    def forbidden(*args):
        pytest.fail("oversized original root reached filesystem inspection")

    monkeypatch.setattr(classification, "reject_path_links", forbidden)
    root = tmp_path.joinpath(*(["part"] * 900))
    with pytest.raises(ValueError):
        classify_changes([{"path": "docs/guide.md"}], root=root)


def test_original_root_junction_is_refused(tmp_path):
    import os

    outside = tmp_path / "outside-root"
    outside.mkdir()
    linked = tmp_path / "linked-root"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(linked))
    else:
        linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        classify_changes([{"path": "docs/guide.md"}], root=linked)


def test_windows_separator_normalization_preserves_valid_metadata():
    result = classify_changes([{"path": "docs\\guide.md"}])
    assert result["change_class"] == "DOC_ONLY"
    assert result["records"][0]["path"] == "docs/guide.md"


def test_added_impacts_never_lower_any_base_class():
    from runtime.change_classification import ChangeClass

    boundaries = [
        ("docs/guide.md", 0),
        ("registry/items.json", 1),
        (".px/skills/item/SKILL.md", 2),
        ("tests/test_item.py", 3),
        ("contracts/item.schema.json", 4),
        ("policies/access.json", 5),
        ("runtime/item.py", 6),
        ("unknown.binary", 7),
    ]
    for path, base in boundaries:
        for symbols in ([], ["changed"]):
            for effects in ([], ["write"]):
                result = classify_changes(
                    [{"path": path, "symbols": symbols, "effects": effects}]
                )
                expected = max(base, 2 if symbols else 0, 6 if effects else 0)
                assert ChangeClass[result["change_class"]].value == expected


def test_expanded_output_refuses_after_bounded_input_admission(monkeypatch):
    import runtime.change_classification as classification

    original = classification._infer
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(classification, "_infer", counted)
    prefix = "docs/" + ("x" * 200 + "/") * 16
    records = [{"path": prefix + str(i) + ".md"} for i in range(2450)]
    with pytest.raises(ValueError, match="byte budget"):
        classify_changes(records)
    assert calls > 0, "The test must exercise expanded output, not oversized input"
