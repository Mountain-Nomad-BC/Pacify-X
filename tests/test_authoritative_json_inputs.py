"""Classified metadata and read/validator boundaries; owned fixtures only."""

import json
import os
from pathlib import Path

import pytest

import runtime.authoritative_json as owner


def registry_root(tmp_path, classification="authoritative"):
    root = tmp_path / "framework"
    path = root / "registry/state_artifact_classes.json"
    path.parent.mkdir(parents=True)
    (root / "owner.py").write_text("# owned fixture\n")
    payload = {
        "schema_version": "1.0",
        "policy": "explicit fixture classification",
        "classes": [
            {
                "artifact_kind": "fixture",
                "classification": classification,
                "owner": "owner.py",
                "corruption_disposition": "rebuild"
                if classification == "derived"
                else "quarantine_fail_closed",
            }
        ],
    }
    path.write_text(json.dumps(payload))
    return root, path, payload


def load(root, path, allowed, validator=None):
    return owner.load_classified_json(
        root,
        path,
        artifact_kind="fixture",
        allowed_root=allowed,
        quarantine_root=allowed / "quarantine",
        validator=validator,
    )


@pytest.mark.parametrize("classification", ["authoritative", "derived"])
@pytest.mark.parametrize("raw", ["{}", "not-json"])
def test_outside_state_refuses_before_open(tmp_path, monkeypatch, classification, raw):
    root, _, _ = registry_root(tmp_path, classification)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    state = tmp_path / "outside.json"
    state.write_text(raw)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != state, "outside source body was opened"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, allowed)


@pytest.mark.parametrize("error_type", [ValueError, TypeError])
def test_validator_exception_never_requests_custody(tmp_path, monkeypatch, error_type):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    original = b'{"valid":"source"}'
    state.write_bytes(original)

    def validator(value):
        raise error_type("validator failed independently")

    def custody(*args, **kwargs):
        pytest.fail("validator error was misclassified as parse corruption")

    monkeypatch.setattr(owner, "_quarantine_corrupt", custody)
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, tmp_path, validator)
    assert state.read_bytes() == original


@pytest.mark.parametrize(
    "result", [False, True, {}, "valid"], ids=["false", "true", "object", "string"]
)
def test_validator_requires_none_return(tmp_path, result):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    state.write_text("{}")
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, tmp_path, lambda value: result)
    assert state.read_text() == "{}"


def test_state_budget_refuses_before_body_and_custody(tmp_path, monkeypatch):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    with state.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != state, "oversize state opened"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    monkeypatch.setattr(
        owner,
        "_quarantine_corrupt",
        lambda *a, **k: pytest.fail("budget is not corruption"),
    )
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, tmp_path)


@pytest.mark.parametrize(
    "raw",
    ['{"x":1,"x":1}', '{"x":NaN}', "[]", '{"x":' + "[" * 33 + "0" + "]" * 33 + "}"],
    ids=["duplicate", "nonfinite", "nonobject", "depth"],
)
def test_decoder_refusal_does_not_guess_custody(tmp_path, monkeypatch, raw):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(raw)
    monkeypatch.setattr(
        owner,
        "_quarantine_corrupt",
        lambda *a, **k: pytest.fail("decoder refusal guessed custody"),
    )
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, tmp_path)
    assert state.read_text() == raw


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_kind", 7),
        ("artifact_kind", "../escape"),
        ("owner", "../outside.py"),
        ("owner", True),
    ],
    ids=["typed-kind", "kind-path", "owner-traversal", "typed-owner"],
)
def test_registry_rejects_coerced_or_escaping_records(tmp_path, field, value):
    root, path, payload = registry_root(tmp_path)
    (tmp_path / "outside.py").write_text("# outside boundary\n")
    (root / "True").write_text("# coercion witness\n")
    payload["classes"][0][field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        owner.load_state_classifications(root)


def test_duplicate_registry_key_is_refused(tmp_path):
    root, path, _ = registry_root(tmp_path)
    raw = path.read_text().replace(
        '"schema_version": "1.0"', '"schema_version": "1.0", "schema_version": "1.0"'
    )
    path.write_text(raw)
    with pytest.raises(ValueError):
        owner.load_state_classifications(root)


def test_oversize_registry_refuses_before_body(tmp_path, monkeypatch):
    root, path, _ = registry_root(tmp_path)
    with path.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    original = Path.open

    def guarded(current, *args, **kwargs):
        assert current != path, "oversize classification image opened"
        return original(current, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        owner.load_state_classifications(root)


def test_snapshot_budget_refuses_before_body(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    with state.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != state, "oversize snapshot opened"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        owner._snapshot(state)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_original_allowed_root_junction_refuses(tmp_path):
    import _winapi

    root, _, _ = registry_root(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "state.json").write_text("{}")
    linked = tmp_path / "linked"
    _winapi.CreateJunction(str(allowed), str(linked))
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, linked / "state.json", linked)


def test_missing_derived_state_preserves_rebuild_contract(tmp_path):
    root, _, _ = registry_root(tmp_path, "derived")
    result = load(root, tmp_path / "missing.json", tmp_path)
    assert result["status"] == "rebuild_required" and result["data"] is None


def test_installed_owner_and_source_only_availability_preserved(tmp_path):
    root, path, payload = registry_root(tmp_path)
    payload["classes"][0]["owner"] = "runtime/authoritative_json.py"
    path.write_text(json.dumps(payload))
    assert (
        owner.load_state_classifications(root)["fixture"]["owner"]
        == "runtime/authoritative_json.py"
    )
    payload["classes"][0]["owner"] = "scripts/source-only.py"
    path.write_text(json.dumps(payload))
    assert (
        owner.load_state_classifications(root)["fixture"]["owner"]
        == "scripts/source-only.py"
    )


def test_post_move_snapshot_refusal_retains_recovery_receipt(tmp_path, monkeypatch):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    state.write_text("not-json")
    original = owner._snapshot
    calls = 0

    def refused(path):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ValueError("owned injected post-move snapshot refusal")
        return original(path)

    monkeypatch.setattr(owner, "_snapshot", refused)
    with pytest.raises(owner.AuthoritativeStateError) as caught:
        load(root, state, tmp_path)
    receipt = json.loads(caught.value.receipt.read_text())
    assert receipt["decision"] == "quarantine_recovery_required"
    assert receipt["moved"] is True
    assert Path(receipt["custody_path"]).read_text() == "not-json"


def test_derived_permission_error_is_not_a_rebuild(tmp_path, monkeypatch):
    root, _, _ = registry_root(tmp_path, "derived")
    state = tmp_path / "state.json"
    state.write_text("{}")
    original = Path.open

    def denied(path, *args, **kwargs):
        if path == state:
            raise PermissionError("owned denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, tmp_path)


def test_policy_requires_actual_text(tmp_path):
    root, path, payload = registry_root(tmp_path)
    payload["policy"] = True
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        owner.load_state_classifications(root)


def test_portable_artifact_aliases_are_not_distinct_custody_owners(tmp_path):
    root, path, payload = registry_root(tmp_path)
    payload["classes"].append({**payload["classes"][0], "artifact_kind": "FIXTURE"})
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        owner.load_state_classifications(root)


@pytest.mark.parametrize("mutation", ["opaque", "nonfinite", "cycle"])
def test_validator_cannot_report_non_json_state_as_valid(
    tmp_path, monkeypatch, mutation
):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    state.write_text("{}")

    def validator(value):
        value["added"] = {
            "opaque": object(),
            "nonfinite": float("nan"),
            "cycle": value,
        }[mutation]

    monkeypatch.setattr(
        owner,
        "_quarantine_corrupt",
        lambda *a, **k: pytest.fail("validator mutation is not stored corruption"),
    )
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, tmp_path, validator)
    assert state.read_text() == "{}"


def test_valid_validator_observes_original_json_and_preserves_file(tmp_path):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    original = b'{"text":"caf\\u00e9"}\r\n'
    state.write_bytes(original)
    seen = []
    result = load(root, state, tmp_path, lambda value: seen.append(dict(value)))
    assert seen == [{"text": "café"}]
    assert result["data"] == seen[0] and result["status"] == "valid"
    assert state.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="Windows metadata junction boundary")
@pytest.mark.parametrize("boundary", ["framework", "owner"])
def test_original_registry_or_owner_link_is_refused(tmp_path, boundary):
    import _winapi

    root, path, payload = registry_root(tmp_path)
    if boundary == "framework":
        linked = tmp_path / "linked-framework"
        _winapi.CreateJunction(str(root), str(linked))
        root = linked
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "owner.py").write_text("# owned fixture\n")
        _winapi.CreateJunction(str(outside), str(root / "linked-owner"))
        payload["classes"][0]["owner"] = "linked-owner/owner.py"
        path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        owner.load_state_classifications(root)


def test_changed_state_image_is_not_classified_as_corrupt(tmp_path, monkeypatch):
    root, _, _ = registry_root(tmp_path)
    state = tmp_path / "state.json"
    state.write_text("{}")
    original = owner.read_file_image

    def changed(path, info, **kwargs):
        if path == state:
            replacement = tmp_path / "replacement.json"
            replacement.write_text('{"changed":true}')
            replacement.replace(state)
        return original(path, info, **kwargs)

    monkeypatch.setattr(owner, "read_file_image", changed)
    monkeypatch.setattr(
        owner,
        "_quarantine_corrupt",
        lambda *a, **k: pytest.fail("identity refusal is not parse corruption"),
    )
    with pytest.raises(owner.AuthoritativeStateError):
        load(root, state, tmp_path)
    assert state.read_text() == '{"changed":true}'
