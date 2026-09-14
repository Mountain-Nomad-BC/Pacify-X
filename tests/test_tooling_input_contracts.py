"""Prepared tooling/search contracts; install only after the next admission."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

import runtime.tool_recommendations as owner


ROOT = Path(__file__).resolve().parents[1]


def registry_root(tmp_path):
    root = tmp_path / "framework"
    path = root / "registry/initial_tool_recommendations.json"
    path.parent.mkdir(parents=True)
    payload = json.loads(
        (ROOT / "registry/initial_tool_recommendations.json").read_text()
    )
    path.write_text(json.dumps(payload))
    return root, path, payload


def test_resolver_availability_cannot_select_a_different_search_corpus(tmp_path):
    (tmp_path / ".hidden.txt").write_text("needle")
    (tmp_path / "ignored.txt").write_text("needle")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")

    def unavailable_evidence(_):
        raise AssertionError("search asked availability to select execution")

    assert owner.search_project_text(
        tmp_path, "needle", resolver=unavailable_evidence
    ) == (".hidden.txt", "ignored.txt")


def test_search_does_not_launch_unowned_native_child(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("needle")

    def unowned(*args, **kwargs):
        pytest.fail("availability caused native execution without current eligibility")

    monkeypatch.setattr(
        owner,
        "subprocess",
        SimpleNamespace(run=unowned, TimeoutExpired=subprocess.TimeoutExpired),
        raising=False,
    )
    assert owner.search_project_text(
        tmp_path, "needle", resolver=lambda _: "fixture-rg.exe"
    ) == ("a.txt",)


@pytest.mark.parametrize(
    "raw,needle",
    [
        (b"a\r\nb\rc", "a\nb\nc"),
        (b"prefix\xfftail", "\ufffdtail"),
        (b"binary\x00tail", "\x00"),
        (b"line -n end", "-n"),
        (b" spaced text ", " "),
    ],
    ids=["newlines", "replacement", "nul", "option-prefix", "literal-space"],
)
def test_literal_text_semantics_are_preserved(tmp_path, raw, needle):
    (tmp_path / "a.txt").write_bytes(raw)
    assert owner.search_project_text(tmp_path, needle, resolver=lambda _: None) == (
        "a.txt",
    )


@pytest.mark.parametrize(
    "needle", ["", 7, "x" * 4097], ids=["empty", "typed", "oversize"]
)
def test_invalid_needle_refuses_before_resolver(tmp_path, needle):
    calls = []
    with pytest.raises(ValueError):
        owner.search_project_text(
            tmp_path, needle, resolver=lambda name: calls.append(name)
        )
    assert calls == []


def test_search_preflights_every_source_before_any_body(tmp_path, monkeypatch):
    small = tmp_path / "a.txt"
    small.write_text("needle")
    big = tmp_path / "z.txt"
    with big.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path not in (small, big), "source body read before global size preflight"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        owner.search_project_text(tmp_path, "needle", resolver=lambda _: None)


@pytest.mark.skipif(os.name != "nt", reason="Windows root junction")
def test_original_project_link_is_refused(tmp_path):
    import _winapi

    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "a.txt").write_text("needle")
    linked = tmp_path / "linked"
    _winapi.CreateJunction(str(actual), str(linked))
    with pytest.raises(ValueError):
        owner.search_project_text(linked, "needle", resolver=lambda _: None)


@pytest.mark.parametrize(
    "limit", [True, "3", 0, 20001], ids=["bool", "string", "zero", "oversize"]
)
def test_assessment_limit_is_actual_integer_before_callback(tmp_path, limit):
    root, _, _ = registry_root(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    calls = []
    with pytest.raises(ValueError):
        owner.assess_project_tooling(
            root, project, maximum_files=limit, resolver=lambda name: calls.append(name)
        )
    assert calls == []


def test_truncated_inventory_cannot_publish_negative_recommendations(tmp_path):
    root, _, _ = registry_root(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("small")
    (project / "z.py").write_text("pass\n")
    result = owner.assess_project_tooling(
        root, project, maximum_files=1, resolver=lambda _: None
    )
    assert result["valid"] is False
    assert result["inventory"]["truncated"] is True
    assert result["recommendations"] == []


def test_missing_rule_is_not_an_implicit_directory_trigger(tmp_path):
    root, _, _ = registry_root(tmp_path)
    project = tmp_path / "project"
    (project / "missing").mkdir(parents=True)
    result = owner.assess_project_tooling(root, project, resolver=lambda _: None)
    assert result["valid"]
    assert all(item["relevant"] is False for item in result["recommendations"])


@pytest.mark.parametrize(
    "field,value",
    [("auto_install", True), ("approval_required", "true"), ("candidates", [7])],
    ids=["auto-install", "typed-approval", "typed-candidate"],
)
def test_registry_refuses_unsafe_or_coerced_records_before_callbacks(
    tmp_path, field, value
):
    root, path, payload = registry_root(tmp_path)
    payload["tools"][-1][field] = value
    path.write_text(json.dumps(payload))
    project = tmp_path / "project"
    project.mkdir()
    calls = []
    with pytest.raises(ValueError):
        owner.assess_project_tooling(
            root, project, resolver=lambda name: calls.append(name)
        )
    assert calls == []


def test_duplicate_registry_tool_ids_refuse_before_callbacks(tmp_path):
    root, path, payload = registry_root(tmp_path)
    payload["tools"].append(dict(payload["tools"][0]))
    path.write_text(json.dumps(payload))
    project = tmp_path / "project"
    project.mkdir()
    calls = []
    with pytest.raises(ValueError):
        owner.assess_project_tooling(
            root, project, resolver=lambda name: calls.append(name)
        )
    assert calls == []


def test_threshold_requires_actual_bounded_integer(tmp_path):
    root, path, payload = registry_root(tmp_path)
    payload["tools"][0]["recommend_when"]["minimum_markdown_files"] = "20"
    path.write_text(json.dumps(payload))
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError):
        owner.assess_project_tooling(root, project, resolver=lambda _: None)


def test_resolver_location_is_not_coerced(tmp_path):
    root, _, _ = registry_root(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError):
        owner.assess_project_tooling(root, project, resolver=lambda _: object())


def test_optional_status_separates_availability_from_eligibility():
    result = owner.optional_tool_status(resolver=lambda _: "fixture-rg.exe")
    assert result["available"] is True
    assert result["eligible"] is False
    assert result["required"] is False


def test_quarantine_variants_are_excluded_before_body_reads(tmp_path, monkeypatch):
    folder = tmp_path / "_QUARANTINE"
    folder.mkdir()
    excluded = folder / "owned-fixture.txt"
    excluded.write_text("needle")
    (tmp_path / "included.txt").write_text("needle")
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != excluded, "excluded fixture body read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert owner.search_project_text(tmp_path, "needle", resolver=lambda _: None) == (
        "included.txt",
    )


def test_directory_only_budget_refusal_is_not_a_complete_assessment(
    tmp_path, monkeypatch
):
    from dataclasses import replace
    from runtime.bounded_walk import bounded_walk

    root, _, _ = registry_root(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    for index in range(5):
        (project / str(index)).mkdir()

    def small_budget(path, *, limits, **kwargs):
        return bounded_walk(path, limits=replace(limits, max_directories=3), **kwargs)

    monkeypatch.setattr(owner, "bounded_walk", small_budget, raising=False)
    result = owner.assess_project_tooling(root, project, resolver=lambda _: None)
    assert result["valid"] is False
    assert result["recommendations"] == []


def test_explicit_quarantine_root_is_refused_before_body(tmp_path, monkeypatch):
    project = tmp_path / "_quarantine"
    project.mkdir()
    target = project / "owned-fixture.txt"
    target.write_text("needle")
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != target, "excluded root body read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        owner.search_project_text(project, "needle", resolver=lambda _: None)


def test_regular_file_named_build_is_not_a_directory_exclusion(tmp_path):
    (tmp_path / "build").write_text("needle")
    assert owner.search_project_text(tmp_path, "needle", resolver=lambda _: None) == (
        "build",
    )


def test_duplicate_registry_keys_refuse_before_callbacks(tmp_path):
    root, path, _ = registry_root(tmp_path)
    path.write_text(
        path.read_text().replace(
            '"schema_version": "1.0"',
            '"schema_version": "1.0", "schema_version": "1.0"',
        )
    )
    project = tmp_path / "project"
    project.mkdir()
    calls = []
    with pytest.raises(ValueError):
        owner.assess_project_tooling(
            root, project, resolver=lambda name: calls.append(name)
        )
    assert calls == []


def test_oversize_registry_refuses_before_open(tmp_path, monkeypatch):
    root, path, _ = registry_root(tmp_path)
    with path.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    project = tmp_path / "project"
    project.mkdir()
    original = Path.open

    def guarded(current, *args, **kwargs):
        assert current != path, "oversize registry image opened"
        return original(current, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        owner.assess_project_tooling(root, project, resolver=lambda _: None)


def test_resolver_cache_is_exact_and_request_local(tmp_path):
    root, path, payload = registry_root(tmp_path)
    for row in payload["tools"]:
        row["candidates"] = ["shared"]
    path.write_text(json.dumps(payload))
    project = tmp_path / "project"
    project.mkdir()
    calls = []
    for _ in range(2):
        result = owner.assess_project_tooling(
            root, project, resolver=lambda name: calls.append(name)
        )
        assert result["valid"]
    assert calls == ["shared", "shared"]


def test_assessment_counts_large_file_metadata_without_reading_body(
    tmp_path, monkeypatch
):
    root, _, _ = registry_root(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    target = project / "large.py"
    with target.open("wb") as stream:
        stream.truncate(2 * 1024 * 1024)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != target, "assessment read a project body"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    result = owner.assess_project_tooling(root, project, resolver=lambda _: None)
    assert result["valid"] and result["inventory"]["source_files"] == 1


def test_recommendation_output_is_bounded(tmp_path):
    root, path, payload = registry_root(tmp_path)
    template = payload["tools"][0]
    payload["tools"] = [
        {
            **template,
            "id": f"tool-{i}",
            "candidates": [f"candidate-{j}" for j in range(16)],
        }
        for i in range(256)
    ]
    path.write_text(json.dumps(payload))
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match="budget"):
        owner.assess_project_tooling(
            root, project, resolver=lambda candidate: candidate + "x" * 3900
        )


def test_relative_root_cannot_hide_quarantine_ancestor(tmp_path, monkeypatch):
    project = tmp_path / "_quarantine"
    project.mkdir()
    (project / "owned-fixture.txt").write_text("needle")
    monkeypatch.chdir(project)
    with pytest.raises(ValueError, match="excluded"):
        owner.search_project_text(Path("."), "needle", resolver=lambda _: None)


@pytest.mark.parametrize(
    "existing", [True, False], ids=["valid-assessment", "missing-project"]
)
def test_owned_actual_tooling_cli(tmp_path, existing):
    import sys
    from runtime.test_runner import run_test_command

    root, _, _ = registry_root(tmp_path)
    project = tmp_path / "project"
    if existing:
        project.mkdir()
        (project / "note.md").write_text("owned fixture\n")
    result = run_test_command(
        [
            sys.executable,
            "-m",
            "runtime.cli",
            "--root",
            str(root),
            "tooling",
            "assess",
            "--project",
            str(project),
        ],
        cwd=ROOT,
        environment={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        timeout_seconds=30,
        run_id="tooling-cli-fixture",
        lane_id="read-only-assessment",
        manage_process_temp=True,
    )
    assert result["process_tree_terminated"] and not result["timed_out"]
    assert (
        result["test_workspace"]["reclaimed"]
        and result["test_workspace"]["errors"] == []
    )
    assert result["exit_code"] == (0 if existing else 1), result.get("stderr")
    body = json.loads(result["stdout"])
    assert body["valid"] is existing
    assert body["read_only"] is True and body["executed_changes"] is False
    if existing:
        assert body["inventory"]["markdown_files"] == 1
