from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import runtime.release_evidence as evidence

STAMP = "2026-09-09T00:00:00Z"


def roles(*names):
    return {
        name: {
            "type": "report",
            "required": True,
            "generation_gate": "focused",
            "producer": "fixture",
        }
        for name in names
    }


def fixture(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"alpha\r\n\x00")
    return evidence.build_evidence_manifest(
        tmp_path, roles=roles("a.txt"), generated_utc=STAMP
    )


def rehash(manifest):
    payload = {
        key: manifest[key] for key in ("schema_version", "generated_utc", "evidence")
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        evidence.canonical_bytes(payload)
    ).hexdigest()
    return manifest


def test_valid_manifest_preserves_exact_payload_hash_and_optional_missing(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"alpha\r\n\x00")
    declared = roles("a.txt")
    declared["optional.json"] = {"type": "report", "required": False}
    manifest = evidence.build_evidence_manifest(
        tmp_path, roles=declared, generated_utc=STAMP
    )
    expected = {
        "schema_version": "1.0",
        "generated_utc": STAMP,
        "evidence": [
            {
                "path": "a.txt",
                "type": "report",
                "required": True,
                "status": "present",
                "size_bytes": 8,
                "sha256": hashlib.sha256(b"alpha\r\n\x00").hexdigest(),
                "generation_gate": "focused",
                "generated_utc": STAMP,
                "producer": "fixture",
            },
            {
                "path": "optional.json",
                "type": "report",
                "required": False,
                "status": "missing",
                "size_bytes": None,
                "sha256": None,
                "generation_gate": "unknown",
                "generated_utc": STAMP,
                "producer": "unknown",
            },
        ],
    }
    assert {key: manifest[key] for key in expected} == expected
    assert (
        manifest["manifest_sha256"]
        == hashlib.sha256(
            (
                json.dumps(
                    expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                + "\n"
            ).encode()
        ).hexdigest()
    )
    assert (
        manifest["valid"]
        and evidence.verify_evidence_manifest(tmp_path, manifest)["valid"]
    )


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_role_required_flag_must_be_actual_boolean(tmp_path, value):
    (tmp_path / "a.txt").write_bytes(b"alpha")
    declaration = roles("a.txt")
    declaration["a.txt"]["required"] = value
    assert (
        evidence.build_evidence_manifest(tmp_path, roles=declaration)["valid"] is False
    )


@pytest.mark.parametrize(
    "field,value", [("type", 17), ("generation_gate", False), ("producer", ["fixture"])]
)
def test_role_metadata_cannot_be_stringified(tmp_path, field, value):
    (tmp_path / "a.txt").write_bytes(b"alpha")
    declaration = roles("a.txt")
    declaration["a.txt"][field] = value
    assert (
        evidence.build_evidence_manifest(tmp_path, roles=declaration)["valid"] is False
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("required", 1),
        ("status", "other"),
        ("type", 17),
        ("producer", False),
        ("generated_utc", "different"),
    ],
)
def test_rehashed_manifest_still_requires_typed_consistent_records(
    tmp_path, field, value
):
    manifest = fixture(tmp_path)
    manifest["evidence"][0][field] = value
    assert (
        evidence.verify_evidence_manifest(tmp_path, rehash(manifest))["valid"] is False
    )


def test_boolean_size_cannot_equal_empty_file_length(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"")
    manifest = evidence.build_evidence_manifest(
        tmp_path, roles=roles("a.txt"), generated_utc=STAMP
    )
    manifest["evidence"][0]["size_bytes"] = False
    assert (
        evidence.verify_evidence_manifest(tmp_path, rehash(manifest))["valid"] is False
    )


@pytest.mark.parametrize(
    "field,value", [("valid", False), ("valid", 1), ("errors", ["incomplete"])]
)
def test_manifest_cannot_discard_its_builder_failure_state(tmp_path, field, value):
    manifest = fixture(tmp_path)
    manifest[field] = value
    assert evidence.verify_evidence_manifest(tmp_path, manifest)["valid"] is False


def test_builder_failure_cannot_turn_into_empty_valid_verification(tmp_path):
    manifest = evidence.build_evidence_manifest(tmp_path, roles=roles("../outside.txt"))
    assert manifest["valid"] is False
    assert evidence.verify_evidence_manifest(tmp_path, manifest)["valid"] is False


@pytest.mark.parametrize("names", [("A.txt", "a.txt"), ("café.txt", "cafe\u0301.txt")])
def test_portable_aliases_refuse_before_any_body(tmp_path, monkeypatch, names):
    for name in names:
        (tmp_path / name).write_bytes(b"content")
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.parent == tmp_path:
            raise AssertionError("alias preflight must precede body read")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert (
        evidence.build_evidence_manifest(tmp_path, roles=roles(*names))["valid"]
        is False
    )


def test_hardlink_aliases_refuse(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"content")
    try:
        os.link(tmp_path / "a.txt", tmp_path / "b.txt")
    except OSError:
        pytest.skip("filesystem does not support hard links")
    assert (
        evidence.build_evidence_manifest(tmp_path, roles=roles("a.txt", "b.txt"))[
            "valid"
        ]
        is False
    )


def link_directory(source, target):
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(source), str(target))
    else:
        target.symlink_to(source, target_is_directory=True)


@pytest.mark.parametrize("root_link", [False, True])
def test_original_directory_link_is_refused_even_inside_root(tmp_path, root_link):
    source = tmp_path / "real"
    source.mkdir()
    (source / "a.txt").write_bytes(b"content")
    link = tmp_path / "linked"
    link_directory(source, link)
    root = link if root_link else tmp_path
    relative = "a.txt" if root_link else "linked/a.txt"
    assert (
        evidence.build_evidence_manifest(root, roles=roles(relative))["valid"] is False
    )


def test_verifier_rejects_rehashed_original_link(tmp_path):
    source = tmp_path / "real"
    source.mkdir()
    manifest = fixture(source)
    link = tmp_path / "linked"
    link_directory(source, link)
    manifest["evidence"][0]["path"] = "linked/a.txt"
    assert (
        evidence.verify_evidence_manifest(tmp_path, rehash(manifest))["valid"] is False
    )


def test_missing_optional_file_behind_link_is_still_unsafe(tmp_path):
    source = tmp_path / "real"
    source.mkdir()
    link = tmp_path / "linked"
    link_directory(source, link)
    result = evidence.build_evidence_manifest(
        tmp_path, roles={"linked/missing.json": {"required": False}}
    )
    assert result["valid"] is False


@pytest.mark.parametrize("name", ["quarantine", "_quarantine", ".quarantine"])
def test_explicit_custody_root_is_excluded_before_read(tmp_path, monkeypatch, name):
    root = tmp_path / name
    root.mkdir()
    (root / "a.txt").write_bytes(b"owned synthetic fixture")
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.parent == root:
            raise AssertionError("excluded root must not be acquired")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert (
        evidence.build_evidence_manifest(root, roles=roles("a.txt"))["valid"] is False
    )


@pytest.mark.parametrize("aggregate", [False, True])
def test_complete_size_preflight_precedes_first_body(tmp_path, monkeypatch, aggregate):
    (tmp_path / "a.txt").write_bytes(b"123456")
    (tmp_path / "b.txt").write_bytes(b"123456" if aggregate else b"123456789")
    monkeypatch.setattr(evidence, "MAX_FILE_BYTES", 8, raising=False)
    monkeypatch.setattr(
        evidence, "MAX_CORPUS_BYTES", 10 if aggregate else 100, raising=False
    )
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.parent == tmp_path:
            raise AssertionError("all sizes must be admitted before first body")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert (
        evidence.build_evidence_manifest(tmp_path, roles=roles("a.txt", "b.txt"))[
            "valid"
        ]
        is False
    )


def test_file_change_between_metadata_and_open_refuses(tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_bytes(b"old")
    original = Path.open
    changed = False

    def changing(candidate, *args, **kwargs):
        nonlocal changed
        if candidate == path and not changed:
            changed = True
            with original(path, "wb") as stream:
                stream.write(b"different bytes")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changing)
    assert (
        evidence.build_evidence_manifest(tmp_path, roles=roles("a.txt"))["valid"]
        is False
    )


def test_role_count_bound_precedes_canonicalization(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "MAX_RECORDS", 2, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("record count before canonicalization")

    monkeypatch.setattr(evidence, "canonical_bytes", forbidden)
    assert (
        evidence.build_evidence_manifest(
            tmp_path, roles={str(i): {"required": False} for i in range(3)}
        )["valid"]
        is False
    )


def test_opaque_role_metadata_is_not_stringified(tmp_path):
    class Opaque:
        def __str__(self):
            raise AssertionError("opaque metadata cannot be coerced")

    (tmp_path / "a.txt").write_bytes(b"content")
    assert (
        evidence.build_evidence_manifest(
            tmp_path, roles={"a.txt": {"producer": Opaque()}}
        )["valid"]
        is False
    )


def test_empty_manifest_is_only_empty_consistency_not_expected_role_proof(tmp_path):
    manifest = evidence.build_evidence_manifest(tmp_path, roles={}, generated_utc=STAMP)
    assert (
        manifest["valid"]
        and evidence.verify_evidence_manifest(tmp_path, manifest)["valid"]
    )
    assert manifest["evidence"] == []
    # The trusted expected-role denominator remains the separate D543 owner.


def test_verifier_preflights_all_current_sizes_before_first_body(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"alpha")
    (tmp_path / "b.txt").write_bytes(b"beta")
    manifest = evidence.build_evidence_manifest(
        tmp_path, roles=roles("a.txt", "b.txt"), generated_utc=STAMP
    )
    (tmp_path / "b.txt").write_bytes(b"123456789")
    monkeypatch.setattr(evidence, "MAX_FILE_BYTES", 8, raising=False)
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.parent == tmp_path:
            raise AssertionError("verifier must preflight all sizes before bodies")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert evidence.verify_evidence_manifest(tmp_path, manifest)["valid"] is False


def test_selected_file_is_acquired_once_per_build_or_verification(
    tmp_path, monkeypatch
):
    path = tmp_path / "a.txt"
    path.write_bytes(b"alpha")
    original = Path.open
    reads = []

    def tracked(candidate, *args, **kwargs):
        if candidate == path:
            reads.append(candidate)
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked)
    manifest = evidence.build_evidence_manifest(
        tmp_path, roles=roles("a.txt"), generated_utc=STAMP
    )
    assert manifest["valid"] and reads == [path]
    reads.clear()
    assert evidence.verify_evidence_manifest(tmp_path, manifest)["valid"] and reads == [
        path
    ]


def test_complete_output_budget_is_checked_before_any_body(tmp_path, monkeypatch):
    import runtime.numeric_inputs as numeric

    path = tmp_path / "a.txt"
    path.write_bytes(b"alpha")
    declaration = {"a.txt": {"required": True}}
    monkeypatch.setattr(numeric, "MAX_ANALYSIS_BYTES", 180)
    numeric.bounded_json_value(declaration)
    original = Path.open

    def guarded(candidate, *args, **kwargs):
        if candidate == path:
            raise AssertionError("output projection must be bounded before source body")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    result = evidence.build_evidence_manifest(
        tmp_path, roles=declaration, generated_utc=STAMP
    )
    assert result["valid"] is False and result["manifest_sha256"] is None
    assert result["evidence"] == []


def test_verification_uses_the_admitted_manifest_snapshot(tmp_path, monkeypatch):
    manifest = fixture(tmp_path)
    path = tmp_path / "a.txt"
    original = Path.open
    changed = False

    def change_caller_manifest(candidate, *args, **kwargs):
        nonlocal changed
        if candidate == path and not changed:
            changed = True
            manifest["evidence"][0]["sha256"] = "0" * 64
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", change_caller_manifest)
    assert evidence.verify_evidence_manifest(tmp_path, manifest)["valid"] is True
    assert changed
    assert evidence.verify_evidence_manifest(tmp_path, manifest)["valid"] is False
