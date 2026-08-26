from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from runtime.agent_runtime import AgentRuntimeController
from tests.studio_approval_testkit import approval_proof, one_shot as _one_shot
from runtime.studio_models import (
    AgentSpec,
    CapabilityBinding,
    EffectGrant,
    StudioVersionConflict,
    write_versioned_record,
)


ROOT = Path(__file__).resolve().parents[1]


def fixtures(body: str):
    grant = EffectGrant(
        "grant:agent-read",
        "agent:demo",
        ("read",),
        ("workspace:demo",),
        "human:owner",
        ("receipt:grant",),
        state="admitted",
    )
    binding = CapabilityBinding(
        "binding:agent-search",
        "agent",
        "agent:demo",
        "capability:search",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:binding",),
    )
    spec = AgentSpec(
        "agent:demo",
        "1.0.0",
        "project:demo",
        "human:owner",
        "harness:px",
        hashlib.sha256(body.encode()).hexdigest(),
        (binding.binding_id,),
        (grant.grant_id,),
        ("identity", "sandbox"),
    )
    return spec, binding, grant


def test_agent_creation_admission_and_actual_owned_harness_are_separate(
    tmp_path,
) -> None:
    body = "Operate only inside the supplied task and effect grant.\n"
    spec, binding, grant = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    created = controller.create_candidate(spec, body)
    assert (
        created["admission_state"] == "unadmitted"
        and created["runtime_state"] == "stopped"
    )
    artifact_paths = [
        tmp_path / created["builder_graph_path"],
        tmp_path / created["editor_layout_path"],
        tmp_path / created["builder_compiler_receipt_path"],
    ]
    before_reopen = [path.read_bytes() for path in artifact_paths]
    assert created["builder_graph_state"] == "content-bound"
    assert created["authority_granted_by_builder"] is False
    assert created["host_authority_retained"] is True
    replay = controller.create_candidate(spec, body)
    assert replay["created"] is False and replay["idempotent_replay"] is True
    assert replay["builder_graph_state"] == "content-bound"
    assert [path.read_bytes() for path in artifact_paths] == before_reopen
    with pytest.raises(PermissionError, match="admission"):
        controller.invoke_harness(spec, task={"objective": "test"}, approval=True)
    assert controller.test_candidate(spec)["passed"] is True
    controller.register_authority([binding], [grant])
    assert controller.admit(spec)["decision"] == "admitted"
    run = controller.invoke_harness(spec, task={"objective": "test"}, approval=True)
    assert (
        run["process_started"] is True
        and run["process_status"] == "exited"
        and run["run_outcome"] == "succeeded"
        and run["tree_closed"] is True
    )
    assert (
        run["worker_invoked"] is True
        and run["model_invoked"] is False
        and run["authority_state"] == "codex-host-retained"
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "year-zero",
        "invalid-calendar",
        "excess-precision",
        "undeclared-key",
        "record-hash",
        "instruction-hash",
        "builder-graph-hash",
        "editor-layout-hash",
        "compiler-hash",
        "identity",
        "version",
        "builder-path",
        "editor-path",
        "compiler-path",
        "authority-state",
        "authority-path",
        "host-authority",
        "created-state",
    ),
)
def test_agent_replay_rejects_each_invalid_creation_receipt_field(
    tmp_path, mutation
) -> None:
    body = "Bounded receipt.\n"
    spec, _, _ = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    created = controller.create_candidate(spec, body)
    receipt_path = (tmp_path / str(created["builder_graph_path"])).with_name(
        "creation-receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "year-zero":
        receipt["created_utc"] = "0000-01-01T00:00:00Z"
    elif mutation == "invalid-calendar":
        receipt["created_utc"] = "2026-02-31T00:00:00Z"
    elif mutation == "excess-precision":
        receipt["created_utc"] = "2026-08-16T00:00:00.1234Z"
    elif mutation == "undeclared-key":
        receipt["undeclared"] = True
    elif mutation == "record-hash":
        receipt["record_sha256"] = "f" * 64
    elif mutation == "instruction-hash":
        receipt["instruction_sha256"] = "f" * 64
    elif mutation == "builder-graph-hash":
        receipt["builder_graph_sha256"] = "f" * 64
    elif mutation == "editor-layout-hash":
        receipt["editor_layout_sha256"] = "f" * 64
    elif mutation == "compiler-hash":
        receipt["builder_compiler_receipt_sha256"] = "f" * 64
    elif mutation == "identity":
        receipt["agent_id"] = "agent:substituted"
    elif mutation == "version":
        receipt["version"] = "9.9.9"
    elif mutation == "builder-path":
        receipt["builder_graph_path"] = "substituted"
    elif mutation == "editor-path":
        receipt["editor_layout_path"] = "substituted"
    elif mutation == "compiler-path":
        receipt["builder_compiler_receipt_path"] = "substituted"
    elif mutation == "authority-state":
        receipt["authority_state"] = "granted"
    elif mutation == "authority-path":
        receipt["authority_definition_path"] = "substituted"
    elif mutation == "host-authority":
        receipt["host_authority_retained"] = False
    else:
        receipt["created"] = False
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(StudioVersionConflict) as refused:
        controller.create_candidate(spec, body)
    assert refused.value.reason == "immutable-agent-revision-differs"


def test_agent_create_returns_bounded_cleanup_warnings_after_commit(
    tmp_path, monkeypatch
) -> None:
    body = "Committed despite degraded cleanup.\n"
    spec, _, _ = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    monkeypatch.setattr(
        controller.manager,
        "reclaim",
        lambda *args, **kwargs: SimpleNamespace(
            errors=tuple("x" * 300 for _ in range(12))
        ),
    )
    created = controller.create_candidate(spec, body)
    assert created["created"] is True
    assert len(created["cleanup_warnings"]) == 8
    assert all(len(warning) == 240 for warning in created["cleanup_warnings"])
    assert (tmp_path / str(created["builder_graph_path"])).is_file()


def test_agent_publish_failure_remains_authoritative_when_reconciliation_fails(
    tmp_path, monkeypatch
) -> None:
    body = "Fail publication deterministically.\n"
    spec, _, _ = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    calls = []

    def fail_publication(*_args):
        raise ValueError("authoritative-publication-failure")

    def fail_closure(*_args, **_kwargs):
        calls.append("closure")
        raise RuntimeError("closure-failure")

    def fail_reclaim(*_args, **_kwargs):
        calls.append("reclaim")
        raise RuntimeError("reclaim-failure")

    monkeypatch.setattr("runtime.agent_runtime.publish_directory_no_replace", fail_publication)
    monkeypatch.setattr(controller.manager, "mark_run_ended", fail_closure)
    monkeypatch.setattr(controller.manager, "reclaim", fail_reclaim)
    with pytest.raises(ValueError, match="authoritative-publication-failure") as refused:
        controller.create_candidate(spec, body)
    assert calls == ["closure", "reclaim"]
    assert any("closure-failure" in note for note in refused.value.__notes__)
    assert any("reclaim-failure" in note for note in refused.value.__notes__)


def test_agent_revision_reopen_fails_closed_on_builder_artifact_tampering(
    tmp_path,
) -> None:
    body = "Bounded.\n"
    spec, _, _ = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    created = controller.create_candidate(spec, body)
    graph_path = tmp_path / created["builder_graph_path"]
    envelope = json.loads(graph_path.read_text(encoding="utf-8"))
    envelope["record"]["agent_id"] = "agent:substituted"
    graph_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(PermissionError, match="builder artifacts are invalid"):
        controller._existing_record_path(spec)


@pytest.mark.parametrize("mutation", ("unexpected-entry", "undeclared-authority"))
def test_agent_exact_replay_rejects_undeclared_revision_topology(
    tmp_path, mutation
) -> None:
    body = "Exact topology.\n"
    spec, _, _ = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    created = controller.create_candidate(spec, body)
    revision = (tmp_path / created["builder_graph_path"]).parent
    name = "unexpected.txt" if mutation == "unexpected-entry" else "authority-definition.json"
    (revision / name).write_text("{}", encoding="utf-8")
    with pytest.raises(StudioVersionConflict) as refused:
        controller.create_candidate(spec, body)
    assert refused.value.reason == "immutable-agent-revision-differs"


def test_agent_exact_replay_allows_only_bounded_owned_run_receipts(tmp_path) -> None:
    body = "Runtime evidence stays separate from the immutable definition.\n"
    spec, _, _ = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    created = controller.create_candidate(spec, body)
    revision = (tmp_path / created["builder_graph_path"]).parent
    runs = revision / "runs"
    runs.mkdir()
    (runs / f"run-{'a' * 32}.json").write_text("{}", encoding="utf-8")
    replay = controller.create_candidate(spec, body)
    assert replay["created"] is False and replay["idempotent_replay"] is True

    (runs / "rogue.txt").write_text("{}", encoding="utf-8")
    with pytest.raises(StudioVersionConflict) as refused:
        controller.create_candidate(spec, body)
    assert refused.value.reason == "immutable-agent-revision-differs"


def test_legacy_agent_revision_reopens_without_graph_backfill(tmp_path) -> None:
    body = "Legacy bounded.\n"
    spec, _, _ = fixtures(body)
    record_path = write_versioned_record(
        tmp_path, "agents", spec.agent_id, spec.version, spec
    )
    record_path.with_name("instructions.md").write_text(
        body, encoding="utf-8", newline="\n"
    )
    record_path.with_name("creation-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": "px.agent-creation-receipt/1.0",
                "agent_id": spec.agent_id,
                "version": spec.version,
                "created": True,
            }
        ),
        encoding="utf-8",
    )
    replay = AgentRuntimeController(tmp_path).create_candidate(spec, body)
    assert replay["created"] is False
    assert replay["builder_graph_state"] == "legacy-unavailable"
    assert not record_path.with_name("builder-graph.json").exists()


def test_new_agent_revision_rejects_missing_builder_triplet(tmp_path) -> None:
    body = "Bounded.\n"
    spec, _, _ = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    created = controller.create_candidate(spec, body)
    for key in (
        "builder_graph_path",
        "editor_layout_path",
        "builder_compiler_receipt_path",
    ):
        (tmp_path / created[key]).unlink()
    with pytest.raises(PermissionError, match="builder artifacts are missing"):
        controller.create_candidate(spec, body)


def test_agent_admission_rejects_caller_assertions_without_current_receipt(
    tmp_path,
) -> None:
    body = "Bounded.\n"
    spec, binding, grant = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    assert controller.admit(spec)["decision"] == "rejected"


def test_unknown_declared_agent_test_fails_instead_of_passing_by_presence(
    tmp_path,
) -> None:
    body = "Bounded.\n"
    spec, _, _ = fixtures(body)
    spec = AgentSpec(
        spec.agent_id,
        spec.version,
        spec.project_id,
        spec.owner,
        spec.harness_id,
        spec.instruction_sha256,
        spec.capability_binding_ids,
        spec.effect_grant_ids,
        ("does-not-exist",),
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    receipt = controller.test_candidate(spec)
    assert receipt["passed"] is False and receipt["test_results"][0]["known"] is False


def test_forged_agent_admission_receipt_is_rejected_before_process_launch(
    tmp_path,
) -> None:
    body = "Bounded.\n"
    spec, binding, grant = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    # Locate by immutable revision rather than trusting the component in this test.
    record_path = next(
        controller.state_root.glob("*/revisions/1.0.0/admission-receipt.json")
    )
    value = __import__("json").loads(record_path.read_text(encoding="utf-8"))
    value["decision"] = "rejected"
    record_path.write_text(__import__("json").dumps(value), encoding="utf-8")
    with pytest.raises(PermissionError, match="authentication"):
        controller.invoke_harness(spec, task={"objective": "test"}, approval=True)


def test_agent_harness_requires_host_approval_and_dispatches_only_closed_tools(
    tmp_path,
) -> None:
    body = "Bounded local worker.\n"
    spec, binding, grant = fixtures(body)
    binding = CapabilityBinding(
        binding.binding_id,
        binding.subject_kind,
        binding.subject_id,
        "capability:local-worker",
        binding.capability_version,
        binding.effect_grant_ids,
        binding.credential_namespace,
        binding.cost_policy,
        binding.egress_policy,
        binding.state,
        binding.evidence_refs,
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    with pytest.raises(PermissionError, match="host approval"):
        controller.invoke_harness(spec, task={"objective": "test"}, approval=False)
    result = controller.invoke_harness(
        spec,
        task={
            "objective": "use pure local tools",
            "tool_calls": [
                {"tool": "sha256", "input": {"value": 1}},
                {"tool": "json-keys", "input": {"b": 2, "a": 1}},
            ],
        },
        approval=True,
    )
    assert [item["tool"] for item in result["tools_dispatched"]] == [
        "sha256",
        "json-keys",
    ]
    assert result["task_content_retained"] is False
    assert not list(
        (tmp_path / ".engineering-bootstrap/studios/agents/tasks").glob("*/task.json")
    )


def test_agent_harness_enforces_declared_task_schema_before_session_start(
    tmp_path,
) -> None:
    body = "Bounded local worker.\n"
    spec, binding, grant = fixtures(body)
    spec = replace(
        spec,
        input_schema={
            "type": "object",
            "properties": {"objective": {"type": "string"}},
            "required": ["objective"],
            "additionalProperties": False,
        },
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    with pytest.raises(TypeError, match="agent input type mismatch: objective"):
        controller.invoke_harness(spec, task={"objective": 1}, approval=True)
    with pytest.raises(ValueError, match="agent input is missing required keys"):
        controller.invoke_harness(spec, task={}, approval=True)
    with pytest.raises(ValueError, match="agent input has undeclared keys"):
        controller.start_harness(
            spec, task={"objective": "okay", "scope": "extra"}, approval=True
        )


def test_agent_harness_allows_non_objective_payload_when_schema_declares_it(tmp_path) -> None:
    body = "Bounded local worker.\n"
    spec, binding, grant = fixtures(body)
    spec = replace(
        spec,
        input_schema={
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    run = controller.invoke_harness(
        spec,
        task={"topic": "standup"},
        approval=True,
    )
    assert run["run_outcome"] == "succeeded"
    assert run["worker_invoked"] is True
    assert run["model_invoked"] is False


def test_agent_harness_rejects_non_objective_task_envelope_type(tmp_path) -> None:
    body = "Bounded local worker.\n"
    spec, binding, grant = fixtures(body)
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    with pytest.raises(TypeError, match="agent input is not an object"):
        controller.invoke_harness(spec, task=["objective", "only"], approval=True)


def test_host_run_validates_task_against_schema_on_completion(tmp_path) -> None:
    body = "Host model path.\n"
    spec, binding, grant = fixtures(body)
    spec = replace(
        spec,
        harness_id="harness:vscode-lm",
        model={
            "provider": "vscode-lm",
            "vendor": "copilot",
            "family": "gpt-5",
            "model_id": "gpt-5",
            "version": "1.0.0",
            "max_output_tokens": 1024,
            "temperature": 0.0,
        },
        input_schema={
            "type": "object",
            "properties": {"objective": {"type": "string"}},
            "required": ["objective"],
            "additionalProperties": False,
        },
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    prepared = controller.prepare_host_run(
        spec, task={"objective": "status-check"}, approval=True
    )
    valid_host_result: dict[str, object] = {
        "status": "completed",
        "output": {"done": True},
        "model": {
            "id": "gpt-5",
            "vendor": "copilot",
            "family": "gpt-5",
            "version": "1.0.0",
            "requested_model_options": {
                "maxOutputTokens": 1024,
                "temperature": 0.0,
            },
            "output_tokens": 5,
            "output_token_limit": 1024,
            "aggregate_input_tokens": 12,
            "aggregate_input_token_limit": 24,
        },
    }
    with pytest.raises(ValueError, match="agent input is missing required keys"):
        controller.complete_host_run(
            spec,
            run_id=str(prepared["run_id"]),
            task={},
            host_result=valid_host_result,
            approval=True,
        )
    prepared = controller.prepare_host_run(
        spec, task={"objective": "status-check"}, approval=True
    )
    with pytest.raises(TypeError, match="agent input is not an object"):
        controller.complete_host_run(
            spec,
            run_id=str(prepared["run_id"]),
            task=["objective", "status-check"],
            host_result=valid_host_result,
            approval=True,
        )


def test_agent_host_run_receipt_records_model_execution_metadata(tmp_path) -> None:
    body = "Host model path.\n"
    spec, binding, grant = fixtures(body)
    spec = replace(
        spec,
        harness_id="harness:vscode-lm",
        model={
            "provider": "vscode-lm",
            "vendor": "copilot",
            "family": "gpt-5",
            "model_id": "gpt-5",
            "version": "1.0.0",
            "max_output_tokens": 256,
            "temperature": 0.0,
        },
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    prepared = controller.prepare_host_run(
        spec, task={"objective": "status-check"}, approval=True
    )
    run = controller.complete_host_run(
        spec,
        run_id=str(prepared["run_id"]),
        task={"objective": "status-check"},
        host_result={
            "status": "completed",
            "output": {"status": "done"},
            "model": {
                "id": "gpt-5",
                "vendor": "copilot",
                "family": "gpt-5",
                "version": "1.0.0",
                "requested_model_options": {
                    "maxOutputTokens": 256,
                    "temperature": 0.0,
                },
                "output_tokens": 5,
                "output_token_limit": 256,
                "aggregate_input_tokens": 11,
                "aggregate_input_token_limit": 22,
            },
        },
        approval=True,
    )
    assert run["run_outcome"] == "succeeded"
    assert run["execution_mode"] == "host-model"
    assert run["model_request_completed"] is True
    assert run["requested_model_route"]["vendor"] == "copilot"
    assert run["worker_invoked"] is False


def test_vscode_host_tool_binding_passes_structural_preflight_and_live_authority_preview(
    tmp_path,
) -> None:
    body = "Use only the exact admitted VS Code host tool.\n"
    spec, binding, grant = fixtures(body)
    spec = replace(
        spec,
        harness_id="harness:vscode-lm",
        model={
            "provider": "vscode-lm",
            "vendor": "copilot",
            "family": "gpt-5",
            "model_id": "gpt-5",
            "version": "1.0.0",
            "max_output_tokens": 1024,
            "temperature": 0,
        },
        tool_binding_ids=(binding.binding_id,),
        required_tests=("identity", "sandbox", "tool-bindings"),
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    preflight = controller.test_candidate(spec)
    assert preflight["passed"] is True
    assert preflight["checks"]["host_tool_implementation_attested"] is True
    controller.register_authority([binding], [grant])
    assert controller.admit(spec)["decision"] == "admitted"
    preview = controller.preview(spec)
    assert preview["eligible"] is True
    assert preview["tools"] == [
        {
            "binding_id": binding.binding_id,
            "binding_sha256": preview["tools"][0]["binding_sha256"],
            "tool_name": binding.capability_id,
            "capability_version": binding.capability_version,
            "effect_grant_ids": [grant.grant_id],
        }
    ]


def _wait_for_agent_state(controller, run_id: str, expected: set[str]) -> dict:
    # CI/certification hosts may be under sustained I/O load from preceding
    # groups. The runtime remains autonomous; this observer-only assertion has
    # a bounded 45-second scheduling allowance. Cross-platform CI can retain
    # an exited detached child as a zombie until its parent is scheduled to
    # reap it; the runtime observer still owns autonomous publication.
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        # This intentionally bypasses session_status(): terminal publication
        # must be autonomous and cannot depend on a polling API mutating state.
        state = controller.run_control.read(run_id)
        if state["state"] in expected:
            return state
        time.sleep(0.02)
    raise AssertionError(
        f"agent session did not reach {expected}; last state={state.get('state')} "
        f"sequence={state.get('sequence')} failure={state.get('failure')}"
    )


def test_agent_session_pause_resume_cancel_and_denial_are_real_owned_lifecycle(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PX_STUDIO_KEY_ROOT", str(tmp_path.parent / f"{tmp_path.name}-host-keys")
    )
    body = "Bounded local worker.\n"
    spec, binding, grant = fixtures(body)
    binding = CapabilityBinding(
        binding.binding_id,
        binding.subject_kind,
        binding.subject_id,
        "capability:local-worker",
        binding.capability_version,
        binding.effect_grant_ids,
        binding.credential_namespace,
        binding.cost_policy,
        binding.egress_policy,
        binding.state,
        binding.evidence_refs,
    )
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    controller.test_candidate(spec)
    controller.register_authority([binding], [grant])
    controller.admit(spec)
    task = {
        "objective": "exercise durable lifecycle",
        # Keep a real lifecycle-control window after a clean-room status
        # subprocess starts on Windows while preserving the worker's closed
        # per-call delay bound.
        "tool_calls": [{"tool": "delay", "input": 1.5}] * 4,
    }
    start_payload = {**asdict(spec), "instructions": body, "task": task}
    approval = approval_proof(tmp_path, "agent", "start", start_payload)
    started = _one_shot(tmp_path, "agent", "start", {**start_payload, "approval_capability": approval})
    assert _one_shot(tmp_path, "agent", "status", {"run_id": started["run_id"]})["state"] != "queued"
    _wait_for_agent_state(controller, started["run_id"], {"running"})
    with pytest.raises(PermissionError, match="explicit host approval"):
        controller.request_lifecycle(
            started["run_id"],
            "pause",
            approved=False,
            approved_by="human:owner",
        )
    controller.request_lifecycle(
        started["run_id"],
        "pause",
        approved=True,
        approved_by="human:owner",
    )
    paused = _wait_for_agent_state(controller, started["run_id"], {"paused"})
    assert paused["checkpoint"]["shutdown_policy"] == "bounded-process-tree-termination"
    resumed = controller.resume_harness(
        spec, run_id=started["run_id"], task=task, approval=True
    )
    assert resumed["schema_version"] == "px.agent-session-start/1.1"
    assert resumed["accepted"] is True
    assert resumed["run_id"] == started["run_id"]
    assert resumed["state"] == "running"
    completed = _wait_for_agent_state(controller, started["run_id"], {"succeeded"})
    assert completed["state"] == "succeeded"
    paused_observer = next(
        record
        for record in controller.manager.ledger.load()
        if record.run_id.startswith(f"studio-finalizer-{started['run_id']}-")
        and record.creator == "px-studio-terminal-observer"
    )
    assert paused_observer.active is False

    approval = approval_proof(tmp_path, "agent", "start", start_payload)
    second = _one_shot(tmp_path, "agent", "start", {**start_payload, "approval_capability": approval})
    _wait_for_agent_state(controller, second["run_id"], {"running"})
    controller.request_lifecycle(
        second["run_id"],
        "cancel",
        approved=True,
        approved_by="human:owner",
    )
    cancelled = _wait_for_agent_state(controller, second["run_id"], {"cancelled"})
    assert cancelled["state"] == "cancelled"
    worker = next(
        record
        for record in controller.manager.ledger.load()
        if record.resource_type == "process" and record.run_id == second["run_id"]
    )
    assert worker.active is False and worker.status == "reclaimed"
