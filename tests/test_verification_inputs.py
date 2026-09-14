"""Prepared verification-input counterexamples; next proof admission required."""
from collections import Counter
import json
import os
from pathlib import Path

import pytest

from runtime import test_profiles as owner
from runtime.verification_inputs import CapturedInputs, resolve_test_section


from tests.verification_fixtures import fixture


def test_multifile_chunks_preserve_the_exact_ordered_member_denominator(tmp_path):
    policy = fixture(tmp_path, count=19)
    policy["sections"]["fixture"]["chunk_size"] = 8
    (tmp_path / "registry/test_profiles.json").write_text(
        json.dumps(policy), encoding="utf-8"
    )

    section = owner.resolve_test_section(tmp_path, "fixture")
    expected = policy["sections"]["fixture"]["command"][3:]
    actual = [member for chunk in section["chunks"] for member in chunk["members"]]

    assert [chunk["member_count"] for chunk in section["chunks"]] == [8, 8, 3]
    assert actual == expected
    assert len(actual) == len(set(actual))


def test_one_section_does_not_reacquire_each_shared_input_for_every_chunk(tmp_path, monkeypatch):
    fixture(tmp_path)
    opened = Counter()
    original = Path.open

    def counted(path, *args, **kwargs):
        if path.is_relative_to(tmp_path):
            opened[path.relative_to(tmp_path).as_posix()] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    result = owner.resolve_test_section(tmp_path, "fixture")
    assert result["valid"] is True and len(result["chunks"]) == 6
    assert opened["runtime/shared.py"] <= 2, dict(opened)
    assert opened["registry/test_profiles.json"] <= 2, dict(opened)


def test_policy_parse_and_input_identity_cannot_use_different_images(tmp_path, monkeypatch):
    fixture(tmp_path)
    policy_path = tmp_path / "registry/test_profiles.json"
    original = json.loads
    changed = False

    def loads(raw, *args, **kwargs):
        nonlocal changed
        value = original(raw, *args, **kwargs)
        if not changed and type(value) is dict and "fixture" in value.get("sections", {}):
            changed = True
            replacement = original(policy_path.read_text(encoding="utf-8"))
            replacement["sections"]["fixture"]["chunk_timeout_seconds"] = 11
            policy_path.write_text(json.dumps(replacement), encoding="utf-8")
        return value

    monkeypatch.setattr(json, "loads", loads)
    with pytest.raises(ValueError):
        owner.resolve_test_section(tmp_path, "fixture")
    assert changed


def test_same_size_same_mtime_edit_changes_next_request_identity(tmp_path):
    fixture(tmp_path)
    source = tmp_path / "runtime/shared.py"
    info = source.stat()
    before = owner.resolve_test_section(tmp_path, "fixture")
    source.write_text("VALUE = 2\n", encoding="utf-8")
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
    after = owner.resolve_test_section(tmp_path, "fixture")
    assert before["input_sha256"] != after["input_sha256"]
    assert before["chunks"][0]["input_sha256"] != after["chunks"][0]["input_sha256"]


def test_same_metadata_edit_during_resolution_cannot_produce_mixed_chunk_identity(tmp_path, monkeypatch):
    fixture(tmp_path)
    source = tmp_path / "runtime/shared.py"
    info = source.stat()
    original = Path.open
    changed = False

    class MutatingClose:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            nonlocal changed
            result = self.stream.__exit__(*args)
            if not changed:
                changed = True
                with original(source, "wb") as stream:
                    stream.write(b"VALUE = 2\n")
                os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
            return result

    def opened(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return MutatingClose(stream) if path == source and not changed else stream

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError):
        owner.resolve_test_section(tmp_path, "fixture")
    assert changed


def test_sibling_workspace_creation_does_not_invalidate_captured_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    fixture(root)
    capture = CapturedInputs(root)
    result = resolve_test_section(root, "fixture", capture=capture)

    (tmp_path / "unrelated-sibling").mkdir()
    capture.verify()

    assert result["valid"] is True


@pytest.mark.parametrize("kind", ["absolute", "relative", "imported-submodule", "test-helper", "conftest", "literal-dynamic"])
def test_section_identity_covers_actual_local_dependency_edits(tmp_path, kind):
    policy = fixture(tmp_path, count=2)
    test = tmp_path / "tests/test_fixture_0.py"
    shared = tmp_path / "runtime/shared.py"
    dependent = tmp_path / "runtime/deep.py"
    dependent.write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "runtime/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests/__init__.py").write_text("", encoding="utf-8")
    if kind == "absolute":
        shared.write_text("import runtime.deep\n", encoding="utf-8")
    elif kind == "relative":
        shared.write_text("from .deep import VALUE\n", encoding="utf-8")
    elif kind == "imported-submodule":
        shared.write_text("from runtime import deep\n", encoding="utf-8")
    elif kind == "test-helper":
        dependent = tmp_path / "tests/helpers.py"
        dependent.write_text("VALUE = 1\n", encoding="utf-8")
        test.write_text("from tests.helpers import VALUE\n", encoding="utf-8")
    elif kind == "conftest":
        dependent = tmp_path / "conftest.py"
        dependent.write_text("VALUE = 1\n", encoding="utf-8")
    else:
        shared.write_text("import importlib\nimportlib.import_module('runtime.deep')\n", encoding="utf-8")
    assert dependent.relative_to(tmp_path).as_posix() not in policy["sections"]["fixture"]["source_patterns"]
    before = owner.resolve_test_section(tmp_path, "fixture")
    dependent.write_text("VALUE = 2\n", encoding="utf-8")
    after = owner.resolve_test_section(tmp_path, "fixture")
    assert before["input_sha256"] != after["input_sha256"], kind
    assert before["chunks"][0]["input_sha256"] != after["chunks"][0]["input_sha256"], kind


@pytest.mark.parametrize("statement", ["from . import deep", "from runtime import deep", "from .deep import VALUE"])
def test_existing_group_dependency_owner_resolves_relative_and_submodule_imports(tmp_path, statement):
    fixture(tmp_path, count=2)
    (tmp_path / "runtime/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "runtime/shared.py").write_text(statement + "\n", encoding="utf-8")
    (tmp_path / "runtime/deep.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = owner._local_python_dependencies(tmp_path, ["runtime/shared.py"])
    assert "runtime/deep.py" in result


def test_declared_nonpython_asset_remains_an_input(tmp_path):
    policy = fixture(tmp_path, count=2)
    (tmp_path / "assets").mkdir()
    path = tmp_path / "assets/config.json"
    path.write_bytes(b'{"mode":1}')
    policy["sections"]["fixture"]["source_patterns"].append("assets/config.json")
    (tmp_path / "registry/test_profiles.json").write_text(json.dumps(policy), encoding="utf-8")
    before = owner.resolve_test_section(tmp_path, "fixture")
    path.write_bytes(b'{"mode":2}')
    after = owner.resolve_test_section(tmp_path, "fixture")
    assert before["input_sha256"] != after["input_sha256"]
