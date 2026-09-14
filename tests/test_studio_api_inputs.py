from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import runtime.studio_api as api


def agent():
    return {
        "agent_id": "agent:inputs",
        "version": "1.0.0",
        "project_id": "project:demo",
        "owner": "human:owner",
        "harness_id": "harness:px",
        "instructions": "Exact café\n",
        "required_tests": ["identity"],
        "capability_binding_ids": [],
        "effect_grant_ids": [],
    }


def workflow():
    return {
        "workflow_id": "workflow:inputs",
        "version": "1.0.0",
        "owner": "human:owner",
        "nodes": [
            {
                "node_id": "task",
                "executor_binding_id": "binding:task",
                "inputs": [{"name": "input", "data_type": "json", "required": True}],
                "outputs": [{"name": "output", "data_type": "json", "required": True}],
                "effect_grant_ids": ["grant:read"],
                "failure_policy": "fail-closed",
                "timeout_seconds": 1.5,
                "retry_limit": 0,
                "approval_required": False,
            }
        ],
        "edges": [],
    }


def encoded(value):
    raw = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    )
    return base64.urlsafe_b64encode(raw).decode("ascii")


def forbidden(*args, **kwargs):
    raise AssertionError("input admission must precede owner construction or effect")


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", 42),
        ("instructions", False),
        ("harness_id", ["harness:px"]),
        ("required_tests", [1]),
        ("effect_grant_ids", [True]),
        ("required_tests", "identity"),
        ("model", []),
        ("input_schema", False),
        ("output_schema", ""),
    ],
    ids=[
        "owner-number",
        "instructions-bool",
        "harness-array",
        "tests-number",
        "grants-bool",
        "tests-string",
        "model-array",
        "input-bool",
        "output-string",
    ],
)
def test_agent_original_types_refuse_before_model_coercion(field, value):
    payload = agent()
    payload[field] = value
    with pytest.raises(ValueError):
        api._agent(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", True),
        ("temperature", "0.5"),
        ("max_output_tokens", "1024"),
        ("max_output_tokens", True),
        ("family", 123),
        ("vendor", False),
    ],
)
def test_agent_model_fields_refuse_before_agentspec_coercion(field, value):
    payload = agent()
    payload["model"] = {
        "provider": "deterministic",
        "family": "px-bounded-worker",
        "model_id": "px-bounded-worker",
        "temperature": 0.5,
        "max_output_tokens": 1024,
    }
    payload["model"][field] = value
    with pytest.raises(ValueError):
        api._agent(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("retry_limit", True),
        ("retry_limit", "1"),
        ("approval_required", "false"),
        ("approval_required", 0),
        ("timeout_seconds", True),
        ("kind", ["task"]),
    ],
)
def test_workflow_node_types_refuse_before_constructor(field, value):
    payload = workflow()
    payload["nodes"][0][field] = value
    with pytest.raises(ValueError):
        api._workflow(payload)


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_workflow_port_requires_actual_boolean(value):
    with pytest.raises(ValueError):
        api._port({"name": "input", "data_type": "json", "required": value})


@pytest.mark.parametrize(
    "payload",
    [
        {"approved": "false"},
        {"higher_is_better": "false"},
        {"better_alternative_found": 0},
        {"limit": "10"},
        {"uses": True},
        {"successes": 1.5},
        {"stale_after_seconds": "30"},
        {"executor_adapters": {"binding:one": 123}},
        {"approvals": {"node:one": True}},
        {"dependency_sha256": {"source:one": 99}},
        {"bindings": False},
        {"grants": {}},
        {"run_input_contract": "missing"},
    ],
    ids=[
        "approved",
        "higher",
        "alternative",
        "limit",
        "uses",
        "successes",
        "stale",
        "adapters",
        "approvals",
        "dependencies",
        "bindings",
        "grants",
        "input-contract",
    ],
)
def test_all_routes_validate_types_before_authority_or_controller(
    tmp_path, monkeypatch, payload
):
    monkeypatch.setattr(api, "StudioAuthorityStore", forbidden)
    monkeypatch.setattr(api, "KnowledgeCoreController", forbidden)
    with pytest.raises(ValueError):
        api.studio_operation(tmp_path, "knowledge", "browse", payload)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"limit":1,"limit":2}',
        b'{"unused":NaN}',
        b'{"unused":1e999}',
        b'{"unused":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
    ],
)
@pytest.mark.parametrize("route", ["stdin", "base64"])
def test_transport_rejects_ambiguous_or_excessively_nested_json(
    monkeypatch, raw, route
):
    monkeypatch.setattr(api.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    with pytest.raises(ValueError):
        api._stdin_payload() if route == "stdin" else api._payload(encoded(raw))


def test_base64_checks_encoded_size_before_decoder(monkeypatch):
    monkeypatch.setattr(api.base64, "b64decode", forbidden)
    monkeypatch.setattr(api.base64, "urlsafe_b64decode", forbidden)
    with pytest.raises(ValueError):
        api._payload("A" * (4 * ((api.MAX_ENVELOPE_BYTES + 2) // 3) + 4))


@pytest.mark.parametrize("route", ["stdin", "base64"])
def test_logical_payload_bound_is_same_without_approval_envelope(monkeypatch, route):
    raw = json.dumps({"unused": "x" * api.MAX_PAYLOAD_BYTES}).encode()
    monkeypatch.setattr(api.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    with pytest.raises(ValueError):
        api._stdin_payload() if route == "stdin" else api._payload(encoded(raw))


def test_direct_request_bound_precedes_owner_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "KnowledgeCoreController", forbidden)
    with pytest.raises(ValueError):
        api.studio_operation(
            tmp_path, "knowledge", "browse", {"unused": "x" * api.MAX_PAYLOAD_BYTES}
        )


def test_valid_transport_keeps_unicode_and_approval_bytes(monkeypatch):
    payload = agent()
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Parsing this synthetic proof is data validation only; no signature is admitted.
    envelope = {
        **payload,
        "approval_capability": {
            "claim": {},
            "payload_json": payload_json,
            "signature": "synthetic",
        },
    }
    raw = json.dumps(envelope, ensure_ascii=False).encode()
    monkeypatch.setattr(api.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    assert api._stdin_payload() == api._payload(encoded(raw)) == envelope
    assert (
        api._payload(encoded(raw))["approval_capability"]["payload_json"]
        == payload_json
    )


@pytest.mark.parametrize(
    "raw", ['{"approved":"false"}', '{"limit":1,"limit":2}', '{"unused":NaN}']
)
def test_signed_payload_data_preflight_precedes_one_time_consumption(
    tmp_path, monkeypatch, raw
):
    monkeypatch.setattr(api, "StudioAuthorityStore", forbidden)
    proof = {"claim": {}, "payload_json": raw, "signature": "unverified"}
    with pytest.raises(ValueError):
        api.studio_operation(
            tmp_path, "agent", "create", {"approval_capability": proof}
        )


def test_valid_workflow_preserves_real_booleans_numbers_and_arbitrary_json():
    payload = workflow()
    definition = api._workflow(payload)
    assert definition.nodes[0].inputs[0].required is True
    assert definition.nodes[0].approval_required is False
    assert definition.nodes[0].timeout_seconds == 1.5
    assert definition.nodes[0].retry_limit == 0


def test_user_json_field_names_are_not_studio_field_rules(monkeypatch):
    payload = agent()
    payload["input_schema"] = {
        "type": "object",
        "properties": {"approved": {"type": "string"}},
    }
    spec, instructions = api._agent(payload)
    assert spec.input_schema == payload["input_schema"]
    assert instructions == payload["instructions"]


def test_direct_opaque_mapping_refuses_without_iteration(tmp_path):
    from collections.abc import Mapping

    class Opaque(Mapping):
        def __iter__(self):
            forbidden()

        def __len__(self):
            forbidden()

        def __getitem__(self, key):
            forbidden()

    with pytest.raises(ValueError):
        api.studio_operation(tmp_path, "knowledge", "browse", Opaque())


def test_workflow_raw_count_refuses_before_node_materialization(monkeypatch):
    payload = workflow()
    payload["nodes"] *= 257
    monkeypatch.setattr(api, "WorkflowNode", forbidden)
    with pytest.raises(ValueError):
        api._workflow(payload)


def test_malformed_main_returns_structured_error_without_echo(tmp_path, capsys):
    secret = "synthetic-do-not-echo"
    rc = api.main(
        [
            "--root",
            str(tmp_path),
            "--kind",
            "knowledge",
            "--operation",
            "browse",
            "--payload-base64",
            encoded({"limit": secret}),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2 and not captured.out and secret not in captured.err
    assert json.loads(captured.err)["code"] == "STUDIO_INPUT_INVALID"


def test_actual_cli_refuses_invalid_request_before_project_effect(tmp_path):
    from runtime.test_runner import run_test_command

    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    result = run_test_command(
        [
            sys.executable,
            "-m",
            "runtime.studio_api",
            "--root",
            str(project),
            "--kind",
            "agent",
            "--operation",
            "create",
            "--payload-base64",
            encoded({"approved": "false"}),
        ],
        cwd=root,
        environment={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        timeout_seconds=30,
        run_id="studio-input-cli",
        lane_id="causal-input",
        manage_process_temp=True,
    )
    assert result["process_tree_terminated"] and result["test_workspace"]["reclaimed"]
    assert not result["test_workspace"]["errors"] and not result["timed_out"]
    assert result["exit_code"] == 2 and not result["stdout"]
    assert json.loads(result["stderr"])["code"] == "STUDIO_INPUT_INVALID"
    assert not list(project.iterdir())


def test_signed_envelope_larger_than_payload_limit_has_transport_parity(monkeypatch):
    payload = agent()
    payload["instructions"] = "x" * 150000
    payload_json = json.dumps(payload, separators=(",", ":"))
    envelope = {
        **payload,
        "approval_capability": {
            "claim": {},
            "payload_json": payload_json,
            "signature": "synthetic",
        },
    }
    raw = json.dumps(envelope).encode()
    assert api.MAX_PAYLOAD_BYTES < len(raw) < api.MAX_ENVELOPE_BYTES
    monkeypatch.setattr(api.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    assert api._stdin_payload() == api._payload(encoded(raw)) == envelope


def test_base64_does_not_silently_ignore_junk():
    with pytest.raises(ValueError):
        api._payload(encoded({"query": "normal"}) + "$$$$")


def test_authority_list_elements_are_not_stringified():
    with pytest.raises(ValueError):
        api._grant(
            {
                "grant_id": "grant:one",
                "subject_id": "agent:one",
                "effects": [True],
                "scope_roots": ["."],
                "approved_by": "human:owner",
                "evidence_refs": ["evidence:one"],
            }
        )


def test_binding_policy_is_not_stringified():
    with pytest.raises(ValueError):
        api._binding(
            {
                "binding_id": "binding:one",
                "subject_kind": "agent",
                "subject_id": "agent:one",
                "capability_id": "capability:one",
                "capability_version": "1.0.0",
                "effect_grant_ids": ["grant:one"],
                "cost_policy": 42,
                "egress_policy": "local",
                "evidence_refs": ["evidence:one"],
            }
        )


def test_validation_check_identifiers_are_typed_before_workflow_model():
    payload = workflow()
    payload["nodes"][0].update(
        kind="validation",
        config={
            "checks": [
                {
                    "id": True,
                    "source": "input",
                    "port": "input",
                    "operator": "equals",
                    "expected": 1,
                }
            ]
        },
    )
    with pytest.raises(ValueError):
        api._workflow(payload)
