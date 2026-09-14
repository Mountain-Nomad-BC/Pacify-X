"""Licensing corpus and pre-effect report path contracts; owned fixtures only."""

import hashlib
import json
import os
from pathlib import Path
import tomllib

import pytest

import runtime.licensing as licensing
import runtime.input_files as inputs

ROOT = Path(__file__).resolve().parents[1]


def _fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    for relative in ["LICENSE", "NOTICE", "README.md", *licensing.THIRD_PARTY_LICENSES]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    for relative in licensing.REQUIRED_ROOT_FILES - {"LICENSE", "NOTICE"}:
        (root / relative).write_text("fixture metadata\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nlicense="Apache-2.0"\nauthors=[{name='
        + json.dumps(licensing.AUTHOR)
        + "}]\n"
        'license-files=["LICENSE","NOTICE"]\n[project.urls]\nRepository='
        + json.dumps(licensing.REPOSITORY)
        + "\nHomepage="
        + json.dumps(licensing.REPOSITORY)
        + "\n",
        encoding="utf-8",
    )
    (root / "registry/skills").mkdir(parents=True)
    (root / "registry/skills/fixture.json").write_text(
        '{"license":"Apache-2.0"}', encoding="utf-8"
    )
    (root / "policies").mkdir()
    (root / "policies/release-artifact-policy.json").write_text(
        json.dumps({"product_root_files": sorted(licensing.REQUIRED_ROOT_FILES)}),
        encoding="utf-8",
    )
    return root


def _forbid(*args, **kwargs):
    raise AssertionError("invalid input must be refused before body or effect")


def _junction(path, target):
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(path))
    else:
        path.symlink_to(target, target_is_directory=True)


def test_owned_valid_corpus_and_report_framing(tmp_path):
    root = _fixture(tmp_path / "project")
    (root / "registry/skills/caf\u00e9.json").write_text(
        '{"license":"Apache-2.0"}', encoding="utf-8"
    )
    result = licensing.write_licensing_report(root)
    assert result["valid"], result["errors"]
    relative = result.pop("report")
    expected = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    assert (root / relative).read_bytes() == expected
    for row in result["files"]:
        assert (
            row["sha256"]
            == hashlib.sha256((root / row["path"]).read_bytes()).hexdigest()
        )


def test_outside_report_refusal_leaves_owned_external_sentinel_and_parent(tmp_path):
    root = _fixture(tmp_path / "project")
    outside = tmp_path / "outside/report.json"
    with pytest.raises(ValueError):
        licensing.write_licensing_report(root, outside)
    assert not outside.exists()
    assert not outside.parent.exists()


@pytest.mark.parametrize(
    "destination",
    [
        "report.json",
        False,
        True,
        0,
        Path("../outside.json"),
        Path("nested/../report.json"),
    ],
)
def test_bad_report_destination_precedes_validation(tmp_path, monkeypatch, destination):
    monkeypatch.setattr(licensing, "validate_licensing", _forbid)
    with pytest.raises(ValueError):
        licensing.write_licensing_report(tmp_path, destination)
    assert list(tmp_path.iterdir()) == []


def test_linked_report_parent_precedes_validation(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _junction(root / "linked", outside)
    monkeypatch.setattr(licensing, "validate_licensing", _forbid)
    with pytest.raises(ValueError):
        licensing.write_licensing_report(root, Path("linked/report.json"))
    assert list(outside.iterdir()) == []


def test_directory_report_target_precedes_validation(tmp_path, monkeypatch):
    (tmp_path / "directory").mkdir()
    monkeypatch.setattr(licensing, "validate_licensing", _forbid)
    with pytest.raises(ValueError):
        licensing.write_licensing_report(tmp_path, Path("directory"))


@pytest.mark.parametrize(
    "field", ["pyproject.toml", "registry/skills/fixture.json", "LICENSE"]
)
def test_oversized_input_refuses_before_any_body(tmp_path, monkeypatch, field):
    root = _fixture(tmp_path)
    with (root / field).open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    monkeypatch.setattr(Path, "open", _forbid)
    result = licensing.validate_licensing(root)
    assert result["valid"] is False and result["checked_file_count"] is None


@pytest.mark.parametrize(
    "constant,limit",
    [
        ("MAX_LICENSING_CORPUS_BYTES", 1),
        ("MAX_LICENSING_FILES", 2),
        ("MAX_LICENSING_DIRECTORY_ENTRIES", 1),
    ],
)
def test_complete_corpus_preflight_precedes_body(
    tmp_path, monkeypatch, constant, limit
):
    root = _fixture(tmp_path)
    (root / "registry/skills/other.txt").write_text("noncontract", encoding="utf-8")
    monkeypatch.setattr(licensing, constant, limit, raising=False)
    monkeypatch.setattr(Path, "open", _forbid)
    result = licensing.validate_licensing(root)
    assert result["valid"] is False and result["files"] == []


@pytest.mark.parametrize(
    "original,replacement",
    [
        ('authors=[{name="Ben J. Cikovic"}]', "authors=true"),
        ('authors=[{name="Ben J. Cikovic"}]', 'authors=["bad"]'),
        ('authors=[{name="Ben J. Cikovic"}]', "authors=[{name=1}]"),
        ('license-files=["LICENSE","NOTICE"]', "license-files=[{bad=1}]"),
        ("[project.urls]\nRepository=", "urls=1\n[irrelevant]\nRepository="),
    ],
)
def test_malformed_project_fields_return_structured_invalid(
    tmp_path, original, replacement
):
    root = _fixture(tmp_path)
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    assert original in text
    path.write_text(text.replace(original, replacement), encoding="utf-8")
    result = licensing.validate_licensing(root)
    assert result["valid"] is False and result["errors"]


def test_policy_root_paths_require_a_real_list(tmp_path):
    root = _fixture(tmp_path)
    (root / "policies/release-artifact-policy.json").write_text(
        json.dumps(
            {
                "product_root_files": {
                    name: True for name in licensing.REQUIRED_ROOT_FILES
                }
            }
        ),
        encoding="utf-8",
    )
    assert licensing.validate_licensing(root)["valid"] is False


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"license":"Apache-2.0","license":"Apache-2.0"}',
        '{"license":"Apache-2.0","number":NaN}',
        '{"license":"Apache-2.0","value":' + "[" * 33 + "0" + "]" * 33 + "}",
    ],
)
def test_contract_json_must_be_actual_unambiguous_bounded_object(tmp_path, payload):
    root = _fixture(tmp_path)
    (root / "registry/skills/fixture.json").write_text(payload, encoding="utf-8")
    result = licensing.validate_licensing(root)
    assert result["valid"] is False and result["errors"]


def test_report_hashes_match_evaluated_images_and_each_body_is_read_once(
    tmp_path, monkeypatch
):
    root = _fixture(tmp_path)
    notice = root / "NOTICE"
    expected = hashlib.sha256(notice.read_bytes()).hexdigest()
    loads = tomllib.loads

    def mutate_after_earlier_text_evaluation(text):
        value = loads(text)
        notice.write_text("replacement after acquisition", encoding="utf-8")
        return value

    monkeypatch.setattr(tomllib, "loads", mutate_after_earlier_text_evaluation)
    original = Path.open
    reads = {}

    def count(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if "r" in mode and path.is_relative_to(root):
            reads[path] = reads.get(path, 0) + 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", count)
    result = licensing.validate_licensing(root)
    assert result["valid"], result["errors"]
    row = next(r for r in result["files"] if r["path"] == "NOTICE")
    assert row["sha256"] == expected
    assert {reads[root / r["path"]] for r in result["files"]} == {1}


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_metadata_newlines_preserve_attribution_and_toml(tmp_path, ending):
    root = _fixture(tmp_path)
    for name in ["NOTICE", "README.md", "pyproject.toml"]:
        path = root / name
        path.write_bytes(
            path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", ending)
        )
    result = licensing.validate_licensing(root)
    assert result["valid"], result["errors"]


def test_report_size_refusal_precedes_parent_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        licensing,
        "validate_licensing",
        lambda root: {"valid": False, "errors": ["bounded report"]},
    )
    monkeypatch.setattr(licensing, "MAX_LICENSING_REPORT_BYTES", 10, raising=False)
    with pytest.raises(ValueError):
        licensing.write_licensing_report(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_nonjson_report_refusal_precedes_parent_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        licensing,
        "validate_licensing",
        lambda root: {"valid": True, "bad": float("nan")},
    )
    with pytest.raises(ValueError):
        licensing.write_licensing_report(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_original_linked_licensing_root_refuses_before_bodies(tmp_path, monkeypatch):
    actual = _fixture(tmp_path / "actual")
    linked = tmp_path / "linked"
    _junction(linked, actual)
    monkeypatch.setattr(Path, "open", _forbid)
    assert licensing.validate_licensing(linked)["valid"] is False


@pytest.mark.parametrize("value", [".", None, True])
def test_directory_root_requires_actual_native_path(value):
    with pytest.raises(ValueError):
        inputs.directory_root(value)


def test_directory_root_refuses_file_traversal_and_original_link(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    file = actual / "input.json"
    file.write_text("{}", encoding="utf-8")
    assert inputs.directory_root(actual) == actual.resolve()
    with pytest.raises(ValueError):
        inputs.directory_root(file)
    with pytest.raises(ValueError):
        inputs.directory_root(actual / "../actual")
    linked = tmp_path / "linked"
    _junction(linked, actual)
    with pytest.raises(ValueError):
        inputs.directory_root(linked)


def test_report_parent_changed_during_validation_refuses_before_writing(
    tmp_path, monkeypatch
):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    def validate(_root):
        _junction(root / "evidence", outside)
        return {"valid": True, "errors": []}

    monkeypatch.setattr(licensing, "validate_licensing", validate)
    with pytest.raises(ValueError):
        licensing.write_licensing_report(root)
    assert list(outside.iterdir()) == []
