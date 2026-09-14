"""Canonical wrapper boundary checks; namespace fixtures are not installed proof."""

import importlib.abc
import json
import os
from pathlib import Path
import runpy
import sys
from types import ModuleType

import pytest

from runtime import input_files, json_io, numeric_inputs


TEMPLATE = Path(__file__).resolve().parents[1] / "templates/generated/domain_tool.py"


def test_active_wrapper_projections_match_canonical_owner():
    from scripts.build_domain_tool_projections import reconcile

    # Read exactly this owner's seven projections. Repair campaigns retain
    # a stale result until their one ordered generated-output reconciliation.
    result = reconcile(TEMPLATE.parents[2], check=True)
    assert result["valid"], result["stale"]


def installed_namespace(monkeypatch, root, result=None):
    calls = []
    package = ModuleType("engineering_bootstrap")
    package.__path__ = []
    declared = ModuleType("engineering_bootstrap.declared_suite")

    def run(framework, outcome, payload):
        calls.append((framework, outcome, payload))
        return {"valid": True, "result": payload} if result is None else result

    declared.run_script_outcome = run
    paths = ModuleType("engineering_bootstrap.paths")
    paths.framework_root = lambda: root
    for name, module in {
        "": package,
        ".declared_suite": declared,
        ".paths": paths,
        ".input_files": input_files,
        ".json_io": json_io,
        ".numeric_inputs": numeric_inputs,
    }.items():
        monkeypatch.setitem(sys.modules, "engineering_bootstrap" + name, module)
    return calls


def invoke(monkeypatch, payload):
    monkeypatch.setattr(
        sys, "argv", [str(TEMPLATE), "fixture", "--input", str(payload)]
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(TEMPLATE), run_name="__main__")
    return stopped.value.code


def test_import_does_not_parse_read_or_dispatch(tmp_path, monkeypatch):
    calls = installed_namespace(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["importer"])
    module = runpy.run_path(str(TEMPLATE), run_name="wrapper_import_probe")
    assert callable(module["main"])
    assert calls == []


@pytest.mark.parametrize("valid,expected", [(True, 0), (False, 1)])
def test_external_input_and_validity_exit_preserved(
    tmp_path, monkeypatch, capsys, valid, expected
):
    calls = installed_namespace(
        monkeypatch, tmp_path / "framework", {"valid": valid, "text": "café\n"}
    )
    payload = tmp_path / "external.json"
    payload.write_text('{"target":"elsewhere","constraints":{}}', encoding="utf-8")
    assert invoke(monkeypatch, payload) == expected
    assert json.loads(capsys.readouterr().out) == {"valid": valid, "text": "café\n"}
    assert calls == [
        (tmp_path / "framework", "fixture", {"target": "elsewhere", "constraints": {}})
    ]


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b'{"x":1,"x":1}',
        b'{"x":NaN}',
        b'{"x":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
    ],
    ids=["nonobject", "duplicate", "nonfinite", "depth"],
)
def test_bad_json_refuses_before_dispatch(tmp_path, monkeypatch, capsys, raw):
    calls = installed_namespace(monkeypatch, tmp_path)
    payload = tmp_path / "input.json"
    payload.write_bytes(raw)
    assert invoke(monkeypatch, payload) == 2
    assert calls == []
    assert json.loads(capsys.readouterr().out)["valid"] is False


def test_oversize_input_refuses_before_open(tmp_path, monkeypatch, capsys):
    calls = installed_namespace(monkeypatch, tmp_path)
    payload = tmp_path / "input.json"
    with payload.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != payload, "oversize body opened before budget refusal"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert invoke(monkeypatch, payload) == 2
    assert calls == []
    assert "budget" in capsys.readouterr().out


@pytest.mark.parametrize(
    "result",
    [{"valid": 1}, [], {"result": "missing validity"}],
    ids=["integer-validity", "nonobject", "missing-validity"],
)
def test_malformed_runtime_result_refuses(tmp_path, monkeypatch, capsys, result):
    installed_namespace(monkeypatch, tmp_path, result)
    payload = tmp_path / "input.json"
    payload.write_text("{}")
    assert invoke(monkeypatch, payload) == 2
    assert json.loads(capsys.readouterr().out)["valid"] is False


def test_oversize_output_is_not_partially_emitted(tmp_path, monkeypatch, capsys):
    installed_namespace(
        monkeypatch, tmp_path, {"valid": True, "body": "x" * (8 * 1024 * 1024)}
    )
    payload = tmp_path / "input.json"
    payload.write_text("{}")
    code = invoke(monkeypatch, payload)
    output = capsys.readouterr().out
    assert code == 2
    assert len(output) < 4096
    assert json.loads(output)["valid"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_original_input_junction_refuses_before_dispatch(tmp_path, monkeypatch, capsys):
    import _winapi

    calls = installed_namespace(monkeypatch, tmp_path)
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "input.json").write_text("{}")
    linked = tmp_path / "linked"
    _winapi.CreateJunction(str(actual), str(linked))
    assert invoke(monkeypatch, linked / "input.json") == 2
    assert calls == []
    assert json.loads(capsys.readouterr().out)["valid"] is False


@pytest.mark.parametrize(
    "missing",
    ["engineering_bootstrap.declared_suite", "installed_dependency"],
    ids=["missing-submodule", "missing-dependency"],
)
def test_broken_installed_namespace_never_falls_back(
    tmp_path, monkeypatch, capsys, missing
):
    from runtime import declared_suite, paths

    calls = []
    monkeypatch.setattr(
        declared_suite,
        "run_script_outcome",
        lambda *args: calls.append(args) or {"valid": True},
    )
    monkeypatch.setattr(paths, "framework_root", lambda: tmp_path)
    package = ModuleType("engineering_bootstrap")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "engineering_bootstrap", package)
    monkeypatch.delitem(
        sys.modules, "engineering_bootstrap.declared_suite", raising=False
    )

    class BrokenDependency(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "engineering_bootstrap.declared_suite":
                raise ModuleNotFoundError(
                    "fixture installed import failure", name=missing
                )
            return None

    monkeypatch.setattr(sys, "meta_path", [BrokenDependency(), *sys.meta_path])
    monkeypatch.setattr(sys, "path", list(sys.path))
    payload = tmp_path / "input.json"
    payload.write_text("{}")
    assert invoke(monkeypatch, payload) == 2
    assert calls == []
    assert "ModuleNotFoundError" in capsys.readouterr().out


def test_changed_input_identity_refuses_before_dispatch(tmp_path, monkeypatch, capsys):
    calls = installed_namespace(monkeypatch, tmp_path)
    payload = tmp_path / "input.json"
    payload.write_text("{}")
    original = input_files.contained_file

    def replaced(root, relative):
        path, info = original(root, relative)
        replacement = tmp_path / "replacement.json"
        replacement.write_text('{"changed":true}')
        replacement.replace(path)
        return path, info

    monkeypatch.setattr(input_files, "contained_file", replaced)
    assert invoke(monkeypatch, payload) == 2
    assert calls == []
    assert json.loads(capsys.readouterr().out)["valid"] is False


def source_fixture(tmp_path):
    from tests.test_declared_suite_inputs import metadata_root

    root = metadata_root(tmp_path)
    for name in (
        "__init__",
        "declared_suite",
        "paths",
        "input_files",
        "json_io",
        "numeric_inputs",
        "archive_io",
        "bounded_walk",
    ):
        target = root / "runtime" / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            (TEMPLATE.parents[2] / "runtime" / (name + ".py")).read_bytes()
        )
    marker = root / "bootstrap/startup.toml"
    marker.parent.mkdir()
    marker.write_text("# disposable fixture marker\n")
    wrapper = root / ".px/skills/sample/scripts/domain_tool.py"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_bytes(TEMPLATE.read_bytes())
    return root, wrapper


@pytest.mark.parametrize(
    "valid_input", [True, False], ids=["generic-inventory", "refused-input"]
)
def test_owned_source_wrapper_cli(tmp_path, valid_input):
    from runtime.test_runner import run_test_command

    root, wrapper = source_fixture(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "exact.txt").write_bytes(b"exact\r\nbytes\x00")
    payload = tmp_path / "external-input.json"
    payload.write_text(
        json.dumps({"target": str(target), "constraints": {}}) if valid_input else "[]"
    )
    # -I/-S isolates this owned source fixture from installed/site packages.
    # The parent test runner remains the process and workspace owner.
    result = run_test_command(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(wrapper),
            "repo-mapper",
            "--input",
            str(payload),
        ],
        cwd=root,
        environment={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        timeout_seconds=30,
        run_id="declared-wrapper-fixture",
        lane_id="generic-cli",
        manage_process_temp=True,
    )
    assert result["process_tree_terminated"] and not result["timed_out"]
    assert result["test_workspace"]["reclaimed"]
    assert result["test_workspace"]["errors"] == []
    assert result["exit_code"] == (0 if valid_input else 2), result.get("stderr")
    body = json.loads(result["stdout"])
    assert body["valid"] is valid_input
    if valid_input:
        import hashlib

        rows = body["result"]["files"]
        assert len(rows) == 1 and rows[0]["path"] == "exact.txt"
        assert rows[0]["sha256"] == hashlib.sha256(b"exact\r\nbytes\x00").hexdigest()


def test_canonical_template_is_not_a_source_root(monkeypatch):
    module = runpy.run_path(str(TEMPLATE), run_name="wrapper_import_probe")
    with pytest.raises(ValueError, match="projected.*layout"):
        module["_source_root"]()


def test_cached_runtime_from_another_root_is_refused(tmp_path, monkeypatch):
    from runtime import declared_suite, paths

    root, wrapper = source_fixture(tmp_path)
    module = runpy.run_path(str(wrapper), run_name="wrapper_import_probe")
    imports = {
        "declared_suite": declared_suite,
        "paths": paths,
        "input_files": input_files,
        "json_io": json_io,
        "numeric_inputs": numeric_inputs,
    }

    def load(name):
        if name == "engineering_bootstrap.declared_suite":
            raise ModuleNotFoundError(
                "absent namespace fixture", name="engineering_bootstrap"
            )
        return imports[name.split(".")[-1]]

    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(module["importlib"], "import_module", load)
    with pytest.raises(ValueError, match="cached runtime module differs"):
        module["_runtime"]()


@pytest.mark.skipif(os.name != "nt", reason="Windows source junction boundary")
def test_linked_source_layout_is_refused(tmp_path):
    import _winapi

    root, wrapper = source_fixture(tmp_path)
    linked = tmp_path / "linked-source"
    _winapi.CreateJunction(str(root), str(linked))
    module = runpy.run_path(
        str(linked / wrapper.relative_to(root)), run_name="wrapper_import_probe"
    )
    with pytest.raises(ValueError, match="linked wrapper source"):
        module["_source_root"]()
