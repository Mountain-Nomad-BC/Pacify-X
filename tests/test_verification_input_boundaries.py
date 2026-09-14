"""Adversarial captured-input cases on owned minimal project trees only."""

import hashlib
import json
from pathlib import Path

import pytest

from runtime import verification_inputs as candidate
from tests.verification_fixtures import fixture


@pytest.mark.parametrize(
    "pattern",
    [
        "../*.py",
        "/runtime/*.py",
        "runtime/../tests/*",
        "runtime//*.py",
        "quarantine/**",
        "runtime/C:bad",
        "runtime/./*.py",
    ],
)
def test_unsafe_pattern_is_rejected_before_expansion(tmp_path, pattern):
    capture = candidate.CapturedInputs(tmp_path)
    with pytest.raises(ValueError):
        capture.match([pattern])
    assert not capture.directories


@pytest.mark.parametrize(
    "field,value",
    [
        ("chunk_size", True),
        ("chunk_size", "1"),
        ("max_parallel_chunks", False),
        ("max_parallel_chunks", 1.5),
    ],
)
def test_chunk_bounds_do_not_coerce_wrong_types(tmp_path, field, value):
    policy = fixture(tmp_path)
    policy["sections"]["fixture"][field] = value
    (tmp_path / candidate.POLICY).write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError):
        candidate.resolve_test_section(tmp_path, "fixture")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"sections":{},"sections":{}}',
        b'{"sections":{},"x":NaN}',
        b"[]",
        b'{"x":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
    ],
)
def test_strict_policy_image_rejects_ambiguous_or_unbounded_json(tmp_path, raw):
    (tmp_path / "registry").mkdir()
    (tmp_path / candidate.POLICY).write_bytes(raw)
    with pytest.raises(ValueError):
        candidate.resolve_test_section(tmp_path, "fixture")


def test_new_wildcard_member_invalidates_capture(tmp_path):
    fixture(tmp_path)
    capture = candidate.CapturedInputs(tmp_path)
    capture.closure(capture.match(["runtime/*.py"]))
    (tmp_path / "runtime/new.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="membership"):
        capture.verify()


def test_wildcard_reuses_directory_entry_images_then_rechecks_fresh_state(
    tmp_path, monkeypatch
):
    fixture(tmp_path, count=4)
    capture = candidate.CapturedInputs(tmp_path)
    original = capture._stat
    calls = []
    current_original = capture._current_stat
    current_calls = []

    def counted(relative):
        calls.append(relative)
        return original(relative)

    def counted_current(relative):
        current_calls.append(relative)
        return current_original(relative)

    monkeypatch.setattr(capture, "_stat", counted)
    monkeypatch.setattr(capture, "_current_stat", counted_current)
    members = capture.match(["tests/*.py"])
    assert members == [f"tests/test_fixture_{index}.py" for index in range(4)]
    assert calls == ["tests"]

    current_calls.clear()
    capture.verify()
    assert current_calls == []


def test_previously_absent_import_becoming_local_invalidates_capture(tmp_path):
    fixture(tmp_path)
    (tmp_path / "runtime/shared.py").write_text(
        "import runtime.future\n", encoding="utf-8"
    )
    capture = candidate.CapturedInputs(tmp_path)
    capture.closure(["runtime/shared.py"])
    (tmp_path / "runtime/future.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="membership"):
        capture.verify()


def test_cross_member_dependency_is_preserved_in_each_affected_chunk(tmp_path):
    fixture(tmp_path, count=2)
    (tmp_path / "tests/test_fixture_0.py").write_text(
        "import tests.test_fixture_1\n", encoding="utf-8"
    )
    first = candidate.resolve_test_section(tmp_path, "fixture")
    assert "tests/test_fixture_1.py" in first["chunks"][0]["inputs"]
    (tmp_path / "tests/test_fixture_1.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = candidate.resolve_test_section(tmp_path, "fixture")
    assert first["chunks"][0]["input_sha256"] != second["chunks"][0]["input_sha256"]


@pytest.mark.parametrize(
    "statement",
    [
        "import importlib as loader\nloader.import_module('runtime.deep')",
        "from importlib import import_module as load\nload('runtime.deep')",
        "__import__('runtime.deep')",
        "from .deep import VALUE",
    ],
)
def test_import_aliases_and_relative_imports_use_the_same_closure(tmp_path, statement):
    fixture(tmp_path)
    (tmp_path / "runtime/shared.py").write_text(statement + "\n", encoding="utf-8")
    (tmp_path / "runtime/deep.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = candidate.resolve_test_section(tmp_path, "fixture")
    assert "runtime/deep.py" in result["inputs"]


def test_nonliteral_dynamic_import_remains_explicitly_unresolved(tmp_path):
    fixture(tmp_path)
    (tmp_path / "runtime/shared.py").write_text(
        "import importlib\nimportlib.import_module(NAME)\n", encoding="utf-8"
    )
    result = candidate.resolve_test_section(tmp_path, "fixture")
    assert result["dependency_analysis"]["runtime_coverage_complete"] is False
    assert result["dependency_analysis"]["unresolved_dynamic_imports"] == {
        "runtime/shared.py": [2]
    }


def test_syntax_error_cannot_silently_shrink_closure(tmp_path):
    fixture(tmp_path)
    (tmp_path / "runtime/shared.py").write_text("def invalid(\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dependency closure"):
        candidate.resolve_test_section(tmp_path, "fixture")


def test_cycle_is_finite_and_preserves_both_sources(tmp_path):
    fixture(tmp_path)
    (tmp_path / "runtime/shared.py").write_text(
        "import runtime.deep\n", encoding="utf-8"
    )
    (tmp_path / "runtime/deep.py").write_text(
        "import runtime.shared\n", encoding="utf-8"
    )
    result = candidate.resolve_test_section(tmp_path, "fixture")
    assert len(result["inputs"]) == len(set(result["inputs"]))
    assert {"runtime/shared.py", "runtime/deep.py"} <= set(result["inputs"])


def test_file_byte_budget_is_enforced_before_open(tmp_path, monkeypatch):
    fixture(tmp_path)
    capture = candidate.CapturedInputs(tmp_path)
    monkeypatch.setattr(candidate, "MAX_FILE_BYTES", 4)
    original = Path.open
    opened = []

    def observe(path, *args, **kwargs):
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe)
    with pytest.raises(ValueError, match="byte budget"):
        capture.capture("runtime/shared.py")
    assert not opened


def test_aggregate_limit_and_ast_limit_fail_closed(tmp_path, monkeypatch):
    fixture(tmp_path)
    capture = candidate.CapturedInputs(tmp_path)
    monkeypatch.setattr(candidate, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="byte budget"):
        capture.capture("runtime/shared.py")
    monkeypatch.setattr(candidate, "MAX_BYTES", 1024)
    monkeypatch.setattr(candidate, "MAX_AST_NODES", 1)
    with pytest.raises(ValueError, match="AST node budget"):
        candidate.CapturedInputs(tmp_path).capture("runtime/shared.py")


def test_directory_and_probe_budgets_fail_closed(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setattr(candidate, "MAX_ENTRIES", 1)
    with pytest.raises(ValueError, match="entry budget"):
        candidate.CapturedInputs(tmp_path).match(["tests/*.py"])
    monkeypatch.setattr(candidate, "MAX_PROBES", 1)
    capture = candidate.CapturedInputs(tmp_path)
    capture.probe("runtime/shared.py")
    with pytest.raises(ValueError, match="probe budget"):
        capture.probe("tests/test_fixture_0.py")


def test_capture_fingerprint_preserves_existing_digest_algorithm(tmp_path):
    fixture(tmp_path)
    capture = candidate.CapturedInputs(tmp_path)
    paths = capture.closure(["runtime/shared.py"])
    digest = hashlib.sha256()
    for relative in paths:
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256((tmp_path / relative).read_bytes()).digest())
    assert capture.fingerprint(paths) == digest.hexdigest()
    capture.verify()


@pytest.mark.parametrize(
    "paths,name,expected",
    [
        ([], "absent.deep.Symbol", set()),
        (["pkg/__init__.py"], "pkg.absent.Symbol", {"pkg/__init__.py"}),
        (["ns/deep.py"], "ns.deep.Symbol", {"ns/deep.py"}),
        (["pkg.py", "pkg/deep.py"], "pkg.deep.Symbol", {"pkg.py", "pkg/deep.py"}),
        (
            ["pkg.py", "pkg/__init__.py", "pkg/deep.py"],
            "pkg.deep.Symbol",
            {"pkg/__init__.py", "pkg/deep.py"},
        ),
    ],
)
def test_module_ancestor_pruning_preserves_positive_closure(
    tmp_path, paths, name, expected
):
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")
    capture = candidate.CapturedInputs(tmp_path)
    assert capture._module(name) == expected
    capture.verify()
    # Once a missing ancestor is established, no deeper filesystem work occurs.
    assert name.replace(".", "/") + "/__init__.py" not in capture.probes


@pytest.mark.parametrize("ancestor", ["future", "pkg/future"])
def test_pruned_ancestor_appearance_invalidates_capture(tmp_path, ancestor):
    (tmp_path / "pkg").mkdir()
    capture = candidate.CapturedInputs(tmp_path)
    assert capture._module(ancestor.replace("/", ".") + ".child.Symbol") == set()
    assert capture.probes[ancestor] is None
    path = tmp_path / ancestor
    path.mkdir()
    (path / "child.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="membership"):
        capture.verify()
    fresh = candidate.CapturedInputs(tmp_path)
    assert fresh._module(ancestor.replace("/", ".") + ".child.Symbol") == {
        ancestor + "/child.py"
    }


def test_module_pruning_preserves_probe_errors(tmp_path, monkeypatch):
    capture = candidate.CapturedInputs(tmp_path)

    def fail(relative):
        raise PermissionError("unreadable ancestor")

    monkeypatch.setattr(capture, "_stat", fail)
    with pytest.raises(PermissionError, match="unreadable"):
        capture._module("blocked.child.Symbol")


def test_captured_file_paths_preserve_identity_without_repeated_resolution(
    tmp_path, monkeypatch
):
    from runtime.input_files import contained_file

    fixture(tmp_path)

    class PriorPathCapture(candidate.CapturedInputs):
        def _file(self, relative):
            return contained_file(self.root, relative)

    original = Path.resolve
    counts = []
    fingerprints = []
    for kind in (PriorPathCapture, candidate.CapturedInputs):
        calls = []

        def counted(path, *args, **kwargs):
            calls.append(path)
            return original(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "resolve", counted)
            capture = kind(tmp_path)
            members = capture.closure(["runtime/shared.py"])
            capture.verify()
            fingerprints.append((members, capture.fingerprint(members)))
        counts.append(len(calls))
    assert fingerprints[0] == fingerprints[1]
    assert counts[1] < counts[0]


@pytest.mark.parametrize(
    "relative", ["../escape.py", "/escape.py", "C:/escape.py", "pkg/../escape.py"]
)
def test_captured_file_path_refuses_lexical_escape(tmp_path, relative):
    with pytest.raises(ValueError):
        candidate.CapturedInputs(tmp_path)._file(relative)


def test_captured_file_path_refuses_directory_input(tmp_path):
    (tmp_path / "directory").mkdir()
    with pytest.raises(ValueError, match="regular file"):
        candidate.CapturedInputs(tmp_path)._file("directory")


@pytest.mark.parametrize("replace_root", [False, True])
def test_captured_file_refuses_ancestor_or_replaced_root_link(tmp_path, replace_root):
    import os

    root = tmp_path / "root"
    target = tmp_path / "target"
    root.mkdir()
    target.mkdir()
    (target / "module.py").write_text("VALUE = 1\n")
    capture = candidate.CapturedInputs(root)
    link = root if replace_root else root / "alias"
    if replace_root:
        root.rmdir()  # Only the empty directory just created by this fixture.
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="linked"):
        capture.capture("module.py" if replace_root else "alias/module.py")
    assert not capture.digests


def test_captured_file_refuses_leaf_symlink(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("VALUE = 1\n")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(target)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip(
                "Windows file symlink privilege unavailable; junction cases remain mandatory"
            )
        raise
    with pytest.raises(ValueError, match="linked"):
        candidate.CapturedInputs(tmp_path).capture("linked.py")
