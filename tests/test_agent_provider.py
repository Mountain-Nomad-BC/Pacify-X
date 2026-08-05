from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from runtime.agent_provider import (
    build_agent_graph,
    classify_projection,
    compile_agent_prompt,
    discover_agents,
    hydrate_agents,
    load_registry,
    route_agents,
    validate_provider,
    validate_agent_orchestration,
)
from runtime.cli import main
from runtime.contracts import validate_instance


ROOT = Path(__file__).resolve().parents[1]


def test_provider_is_complete_hash_bound_and_lazy() -> None:
    status = validate_provider(ROOT)
    assert status["valid"], status["errors"]
    assert status["agent_count"] == 270
    assert status["body_count"] == status["manifest_count"] == 270
    assert status["source_audit_status_counts"] == {
        "HARDEN": 195,
        "READY": 9,
        "REWRITE": 66,
    }
    assert status["eager_body_hydration"] == 0
    graph = build_agent_graph(ROOT)
    assert graph["metrics"] == {
        "node_count": 346,
        "edge_count": 3640,
        "agent_nodes": 270,
        "capability_nodes": 59,
        "division_nodes": 17,
    }


def test_every_manifest_satisfies_the_target_contract() -> None:
    registry = load_registry(ROOT)
    schema = ROOT / "contracts" / "agents" / "agency-agent-manifest.schema.json"
    for item in registry["agents"]:
        manifest = json.loads(
            (ROOT / item["manifest_path"]).read_text(encoding="utf-8")
        )
        validate_instance(manifest, schema, contract_root=ROOT / "contracts")


def test_metadata_discovery_does_not_read_agent_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_self: Path) -> bytes:
        raise AssertionError("metadata discovery hydrated a file body")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    envelope, candidates = discover_agents(
        ROOT, "review a Python API implementation for security and correctness"
    )
    assert envelope.raw_request
    assert candidates


def test_route_is_deterministic_bounded_and_rejects_keyword_only_noise() -> None:
    request = "review a Python API implementation for security and correctness"
    first = route_agents(ROOT, request)
    second = route_agents(ROOT, request)
    assert first == second
    assert first["primary_agent"]
    assert len(first["reviewers"]) <= 3
    assert first["primary_agent"] not in first["reviewers"]
    assert len(first["reviewers"]) == len(set(first["reviewers"]))
    assert first["authority_granted"] is False
    unrelated = route_agents(ROOT, "write a cheerful birthday poem")
    assert unrelated["valid"] is False
    assert unrelated["primary_agent"] is None


def test_high_risk_route_requires_accountable_human_review() -> None:
    route = route_agents(ROOT, "deploy a clinical patient payment system to production")
    assert route["risk_tier"] == "high"
    assert route["requires_human_review"] is True
    assert route["reviewers"]
    assert route["authority_granted"] is False


def test_hydration_is_selected_bounded_hash_checked_and_project_scoped() -> None:
    route = route_agents(ROOT, "review a Python API for security and correctness")
    selected = [route["primary_agent"], *route["reviewers"]]
    result = hydrate_agents(ROOT, selected, project_id="project_alpha")
    assert result["valid"] is True
    assert result["receipt"]["hydrated_agent_count"] == len(selected)
    assert result["receipt"]["authority_granted"] is False
    assert all(
        item["memory_namespace"].startswith("project:project_alpha:agent:")
        for item in result["agents"]
    )
    with pytest.raises(ValueError, match="byte budget"):
        hydrate_agents(
            ROOT,
            [route["primary_agent"]],
            project_id="project_alpha",
            max_total_bytes=1,
        )


def test_reference_only_agent_cannot_be_hydrated() -> None:
    item = next(
        value
        for value in load_registry(ROOT)["agents"]
        if value["lifecycle_state"] == "reference_only"
    )
    with pytest.raises(ValueError, match="reference-only"):
        hydrate_agents(ROOT, [item["agent_id"]], project_id="project_alpha")


def test_compilation_preserves_authority_and_memory_boundaries() -> None:
    request = "review a Python API for security and correctness"
    route = route_agents(ROOT, request)
    task = {
        "task_id": route["task_id"],
        "objective": request,
        "deliverable": "evidence-backed review",
        "scope": {"included": ["supplied code"], "excluded": ["production changes"]},
        "authority": {
            "read": True,
            "write": False,
            "execute": False,
            "external_action": False,
            "destructive": False,
            "approved_targets": [],
        },
        "acceptance_criteria": ["findings cite inspected evidence"],
        "memory_namespace": "project:project_alpha",
    }
    result = compile_agent_prompt(
        ROOT,
        task,
        route,
        project_id="project_alpha",
        selected_skills=["verify-outcome"],
        permitted_tools=["read_local"],
    )
    assert result["valid"] is True
    assert result["authority_granted"] is False
    assert '"authority_granted_by_compilation": false' in result["compiled_prompt"]
    assert '"memory_scope": "project:project_alpha"' in result["compiled_prompt"]
    assert "This compilation is context, not authorization" in result["compiled_prompt"]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"disk_sha256": None, "recorded_rendered_sha256": "old"}, "Removed"),
        ({"disk_sha256": None, "recorded_rendered_sha256": None}, "Foreign"),
        ({"disk_sha256": "different", "recorded_rendered_sha256": "old"}, "Modified"),
        (
            {
                "disk_sha256": "old",
                "recorded_rendered_sha256": "old",
                "recorded_source_sha256": "before",
            },
            "Outdated",
        ),
        ({"disk_sha256": "current", "recorded_rendered_sha256": None}, "Current"),
    ],
)
def test_projection_reconciliation_uses_five_explicit_states(
    values: dict[str, str | None], expected: str
) -> None:
    inputs = {
        "disk_sha256": "current",
        "recorded_rendered_sha256": "current",
        "current_rendered_sha256": "current",
        "recorded_source_sha256": "source",
        "current_source_sha256": "source",
        **values,
    }
    assert classify_projection(**inputs) == expected


def test_agent_cli_status_and_route(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(ROOT), "agents", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["agent_count"] == 270
    assert (
        main(
            [
                "--root",
                str(ROOT),
                "agents",
                "route",
                "--task",
                "review a Python API for security and correctness",
            ]
        )
        == 0
    )
    routed = json.loads(capsys.readouterr().out)
    assert routed["primary_agent"]
    assert routed["hydrated_agent_count"] == 0


def test_specialist_skill_wrapper_and_orchestration_are_executable() -> None:
    orchestration = validate_agent_orchestration(ROOT)
    assert orchestration["valid"], orchestration["errors"]
    command = [
        sys.executable,
        str(
            ROOT
            / ".agents"
            / "skills"
            / "route-specialist-agents"
            / "scripts"
            / "route_specialist_agents.py"
        ),
        "review a Python API for security and correctness",
        "--root",
        str(ROOT),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["primary_agent"]
    graph_check = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_agency_agent_graph.py"),
            "--root",
            str(ROOT),
            "--check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert graph_check.returncode == 0, graph_check.stderr
    assert json.loads(graph_check.stdout)["valid"] is True
