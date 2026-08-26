"""Bounded JSON adapter for the versioned Agent, Workflow, and Skill studios."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from .agent_builder import (
    AgentBuilderGraph,
    agent_builder_graph_from_mapping,
    agent_builder_graph_from_spec,
    assert_agent_builder_graph_matches_spec,
    normalize_agent_editor_layout,
)
from .agent_runtime import AgentRuntimeController
from .knowledge_core_controller import KnowledgeCoreController
from .paths import framework_root
from .skill_studio import SkillStudio, _component
from .studio_authority import StudioAuthorityStore
from .studio_models import (
    AgentSpec,
    CapabilityBinding,
    EffectGrant,
    SkillPackage,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    allocate_studio_version,
    canonical_bytes,
    digest,
    require_initial_studio_identity,
    studio_identity_absence,
    StudioVersionConflict,
)
from .studio_protocol import ALL_STUDIO_OPERATIONS, STUDIO_KINDS, require_studio_operation
from .studio_run_control import DurableRunControl
from .workflow_studio import WorkflowStudio


MAX_PAYLOAD_BYTES = 256 * 1024
MAX_ENVELOPE_BYTES = (2 * MAX_PAYLOAD_BYTES) + (16 * 1024)
RESTRICTED_AGENT_NAMESPACE = re.compile(
    r"^(?:enterprise|microsoft|ms|azure|m365|dynamics)[.:/-]", re.IGNORECASE
)


def _skill_promotion_receipt_path(root: Path, skill_id: str, version: str) -> Path:
    return (
        root
        / ".engineering-bootstrap"
        / "studios"
        / "skills"
        / _component(skill_id)
        / "revisions"
        / version
        / "promotion-receipt.json"
    )


def _payload(encoded: str) -> Mapping[str, Any]:
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("studio payload exceeds the 256 KiB bound")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("studio payload must be an object")
    return value


def _stdin_payload() -> Mapping[str, Any]:
    raw = sys.stdin.buffer.read(MAX_ENVELOPE_BYTES + 1)
    if len(raw) > MAX_ENVELOPE_BYTES:
        raise ValueError("studio request envelope exceeds the 528 KiB bound")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("studio payload must be an object")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("expected an array of strings")
    return tuple(str(item) for item in value)


def _require_standard_agent_domain(value: Mapping[str, Any]) -> None:
    """Keep the generic Agent Studio inside the non-enterprise namespace."""
    if str(value.get("builder_domain") or "px-standard") != "px-standard":
        raise PermissionError(
            "Agent Studio is px-standard; use a separately governed domain flow"
        )
    candidates = [str(value.get("harness_id") or "")]
    for binding in value.get("bindings", []):
        if not isinstance(binding, Mapping):
            raise ValueError("agent authority bindings must be objects")
        candidates.extend(
            (
                str(binding.get("capability_id") or ""),
                str(binding.get("credential_namespace") or ""),
            )
        )
    if any(RESTRICTED_AGENT_NAMESPACE.match(candidate) for candidate in candidates):
        raise PermissionError(
            "px-standard Agent Studio cannot bind Microsoft/vendor or enterprise-restricted namespaces"
        )


def _agent(value: Mapping[str, Any]) -> tuple[AgentSpec, str]:
    _require_standard_agent_domain(value)
    body = str(value.get("instructions") or "")
    import hashlib

    spec = AgentSpec(
        str(value["agent_id"]),
        str(value["version"]),
        str(value["project_id"]),
        str(value["owner"]),
        str(value["harness_id"]),
        hashlib.sha256(body.encode("utf-8")).hexdigest(),
        _strings(value.get("capability_binding_ids", [])),
        _strings(value.get("effect_grant_ids", [])),
        _strings(value.get("required_tests", [])),
        str(value.get("lifecycle", "draft")),
        model=dict(
            value.get("model", {})
            or {
                "provider": "deterministic",
                "family": "px-bounded-worker",
                "model_id": "px-bounded-worker",
                "max_output_tokens": 1024,
                "temperature": 0.0,
            }
        ),
        tool_binding_ids=_strings(value.get("tool_binding_ids", [])),
        memory_binding_ids=_strings(value.get("memory_binding_ids", [])),
        handoff_agent_ids=_strings(value.get("handoff_agent_ids", [])),
        input_schema=dict(
            value.get("input_schema", {})
            or {"type": "object", "additionalProperties": True}
        ),
        output_schema=dict(
            value.get("output_schema", {})
            or {"type": "object", "additionalProperties": True}
        ),
    )
    return spec, body


def _agent_builder(
    value: Mapping[str, Any], spec: AgentSpec
) -> tuple[AgentBuilderGraph, dict[str, dict[str, float]], bool]:
    """Resolve a supplied graph or synthesize the exact legacy projection.

    Synthesis preserves the pre-graph API while ensuring every newly published
    revision has the same immutable graph artifacts.  Existing revisions are
    never backfilled or rewritten by this adapter.
    """

    raw_graph = value.get("builder_graph")
    explicit = raw_graph is not None
    if explicit:
        if not isinstance(raw_graph, Mapping):
            raise ValueError("agent builder_graph must be an object")
        graph = agent_builder_graph_from_mapping(raw_graph)
        assert_agent_builder_graph_matches_spec(graph, spec)
    else:
        graph = agent_builder_graph_from_spec(spec)
    raw_layout = value.get("editor_layout")
    if raw_layout is not None and not isinstance(raw_layout, Mapping):
        raise ValueError("agent editor_layout must be an object")
    layout = normalize_agent_editor_layout(graph, raw_layout)
    return graph, layout, explicit


def _port(value: Mapping[str, Any]) -> WorkflowPort:
    return WorkflowPort(
        str(value["name"]), str(value["data_type"]), bool(value.get("required", True))
    )


def _workflow(value: Mapping[str, Any]) -> WorkflowDefinition:
    nodes = tuple(
        WorkflowNode(
            str(node["node_id"]),
            str(node["executor_binding_id"]),
            tuple(_port(port) for port in node.get("inputs", [])),
            tuple(_port(port) for port in node.get("outputs", [])),
            _strings(node.get("effect_grant_ids", [])),
            str(node["failure_policy"]).strip().lower().replace("_", "-"),
            node["timeout_seconds"],
            int(node.get("retry_limit", 0)),
            bool(node.get("approval_required", False)),
            str(node.get("kind", "task")),
            dict(node.get("config", {})),
        )
        for node in value.get("nodes", [])
    )
    edges = tuple(
        WorkflowEdge(
            str(edge.get("source_node", edge.get("source_node_id", ""))),
            str(edge["source_port"]),
            str(edge.get("target_node", edge.get("target_node_id", ""))),
            str(edge["target_port"]),
            str(edge.get("condition", "always")),
        )
        for edge in value.get("edges", [])
    )
    return WorkflowDefinition(
        str(value["workflow_id"]),
        str(value["version"]),
        str(value["owner"]),
        nodes,
        edges,
        str(value.get("lifecycle", "draft")),
    )


def _workflow_editor_layout(
    value: Mapping[str, Any], definition: WorkflowDefinition
) -> dict[str, dict[str, int | float]]:
    """Validate the exact editor geometry bound to a workflow revision.

    Older callers did not supply editor geometry.  New revisions still receive
    a deterministic initial layout, while a supplied layout must cover exactly
    the immutable definition's node set.  Legacy revisions are never backfilled
    by this adapter.
    """

    supplied = value.get("editor_layout")
    if supplied is None:
        return {
            node.node_id: {
                "x": (index % 16) * 280,
                "y": (index // 16) * 180,
            }
            for index, node in enumerate(definition.nodes)
        }
    if not isinstance(supplied, Mapping):
        raise ValueError("workflow editor_layout must be an object")
    node_ids = {node.node_id for node in definition.nodes}
    if any(not isinstance(key, str) for key in supplied) or set(supplied) != node_ids:
        raise ValueError("workflow editor_layout must match the exact node set")
    normalized: dict[str, dict[str, int | float]] = {}
    for node in definition.nodes:
        position = supplied[node.node_id]
        if not isinstance(position, Mapping) or set(position) != {"x", "y"}:
            raise ValueError("workflow editor_layout positions require only x and y")
        x = position["x"]
        y = position["y"]
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
            or not math.isfinite(x)
            or not math.isfinite(y)
            or abs(x) > 20_000
            or abs(y) > 20_000
        ):
            raise ValueError(
                "workflow editor_layout coordinates must be finite and within 20000"
            )
        normalized[node.node_id] = {"x": x, "y": y}
    return normalized


def _skill(
    value: Mapping[str, Any], *, require_source_directory: bool = False
) -> tuple[SkillPackage, Path | None]:
    package = SkillPackage(
        str(value["skill_id"]),
        str(value["version"]),
        str(value["owner"]),
        _strings(value.get("triggers", [])),
        _strings(value.get("non_triggers", [])),
        _strings(value.get("permissions", [])),
        _strings(value.get("effects", [])),
        _strings(value.get("resources", [])),
        _strings(value.get("contracts", [])),
        _strings(value.get("tests", [])),
        {
            str(key): str(item)
            for key, item in dict(value.get("provenance", {})).items()
        },
        str(value.get("lifecycle", "draft")),
    )
    source_value = value.get("source_directory")
    if require_source_directory and not source_value:
        raise ValueError("skill creation requires an admitted source_directory")
    return package, Path(str(source_value)) if source_value else None


def _grant(value: Mapping[str, Any]) -> EffectGrant:
    return EffectGrant(
        str(value["grant_id"]),
        str(value["subject_id"]),
        _strings(value.get("effects", [])),
        _strings(value.get("scope_roots", [])),
        str(value.get("approved_by") or ""),
        _strings(value.get("evidence_refs", [])),
        str(value["expires_utc"]) if value.get("expires_utc") else None,
        str(value.get("state", "candidate")),
    )


def _binding(value: Mapping[str, Any]) -> CapabilityBinding:
    return CapabilityBinding(
        str(value["binding_id"]),
        str(value["subject_kind"]),
        str(value["subject_id"]),
        str(value["capability_id"]),
        str(value["capability_version"]),
        _strings(value.get("effect_grant_ids", [])),
        str(value["credential_namespace"])
        if value.get("credential_namespace")
        else None,
        str(value.get("cost_policy") or ""),
        str(value.get("egress_policy") or ""),
        str(value.get("state", "candidate")),
        _strings(value.get("evidence_refs", [])),
    )


def _authority(
    value: Mapping[str, Any],
) -> tuple[tuple[CapabilityBinding, ...], tuple[EffectGrant, ...]]:
    bindings = tuple(_binding(item) for item in value.get("bindings", []))
    authenticated_approver = str(value.get("approved_by") or "").strip()
    grants = tuple(
        _grant({**item, "approved_by": authenticated_approver} if authenticated_approver else item)
        for item in value.get("grants", [])
    )
    return bindings, grants


def _revision_authority_envelope(
    kind: str, identity: str, version: str, value: Mapping[str, Any]
) -> dict[str, object]:
    """Build and validate the authority sidecar before a revision is published."""
    bindings, grants = _authority(value)
    executor_adapters: dict[str, str] = {}
    if kind == "workflow":
        supplied = value.get("executor_adapters", {})
        if not isinstance(supplied, Mapping):
            raise ValueError("workflow executor adapters must be an object")
        executor_adapters = {str(key): str(item) for key, item in supplied.items()}
    run_inputs = value.get("run_inputs", {}) if kind == "workflow" else {}
    if not isinstance(run_inputs, Mapping):
        raise ValueError("workflow run inputs must be an object")
    run_input_contract: list[dict[str, object]] = []
    if kind == "workflow":
        supplied_contract = value.get("run_input_contract")
        if isinstance(supplied_contract, list) and supplied_contract:
            for item in supplied_contract:
                if not isinstance(item, Mapping) or not str(item.get("key") or ""):
                    raise ValueError("workflow run input contract contains an invalid entry")
                run_input_contract.append(
                    {
                        "key": str(item["key"]),
                        "value_type": str(item.get("value_type") or "json"),
                        "required": bool(item.get("required", True)),
                    }
                )
        else:
            driven = {
                f"{edge.get('target_node') or edge.get('target_node_id')}.{edge.get('target_port')}"
                for edge in value.get("edges", [])
                if isinstance(edge, Mapping)
            }
            for node in value.get("nodes", []):
                if not isinstance(node, Mapping):
                    continue
                node_id = str(node.get("node_id") or "")
                for port in node.get("inputs", []):
                    if not isinstance(port, Mapping):
                        continue
                    key = f"{node_id}.{port.get('name')}"
                    if key not in driven:
                        run_input_contract.append(
                            {
                                "key": key,
                                "value_type": str(port.get("data_type") or "json"),
                                "required": bool(port.get("required", True)),
                            }
                        )
            run_input_contract.sort(key=lambda item: str(item["key"]))
    authority = {
        "schema_version": "px.studio-authority-definition/1.0",
        "kind": kind,
        "subject_id": identity,
        "version": version,
        "builder_domain": str(value.get("builder_domain") or "px-standard"),
        "bindings": [asdict(binding) for binding in bindings],
        "grants": [asdict(grant) for grant in grants],
        "executor_adapters": executor_adapters,
        "run_input_contract": run_input_contract,
        "runtime_input_values_stored": False,
    }
    envelope = {"record": authority, "sha256": digest(authority)}
    return json.loads(canonical_bytes(envelope))


def create_draft(root: Path, kind: str, value: Mapping[str, Any]) -> dict[str, object]:
    root = root.resolve(strict=True)
    supplied_allocation = value.get("version_allocation")
    if supplied_allocation is not None and not isinstance(supplied_allocation, Mapping):
        raise StudioVersionConflict("allocation-envelope-invalid")
    if kind == "agent":
        spec, body = _agent(value)
        if supplied_allocation is None:
            require_initial_studio_identity(root, kind, spec.agent_id, spec.version)
        graph, editor_layout, explicit_graph = _agent_builder(value, spec)
        authority = _revision_authority_envelope(
            kind, spec.agent_id, spec.version, value
        )
        return AgentRuntimeController(root).create_candidate(
            spec,
            body,
            authority_definition=authority,
            builder_graph=graph,
            editor_layout=editor_layout,
            builder_graph_explicit=explicit_graph,
            version_allocation=supplied_allocation,
        )
    if kind == "workflow":
        definition = _workflow(value)
        if supplied_allocation is None:
            require_initial_studio_identity(
                root, kind, definition.workflow_id, definition.version
            )
        editor_layout = _workflow_editor_layout(value, definition)
        authority = _revision_authority_envelope(
            kind, definition.workflow_id, definition.version, value
        )
        return WorkflowStudio(root).save_revision(
            definition,
            authority_definition=authority,
            editor_layout=editor_layout,
            version_allocation=supplied_allocation,
        )
    if kind == "skill":
        package, source = _skill(value, require_source_directory=True)
        if supplied_allocation is None:
            require_initial_studio_identity(
                root, kind, package.skill_id, package.version
            )
        assert source is not None
        source_token = str(value.get("source_token") or "")
        if not source_token:
            raise PermissionError("skill draft requires a host-issued source token")
        return SkillStudio(root).stage_draft(
            package,
            source,
            source_token=source_token,
            version_allocation=supplied_allocation,
        )
    raise ValueError("studio kind must be agent, workflow, or skill")


def admit_skill_source(root: Path, value: Mapping[str, Any]) -> dict[str, object]:
    required = {
        "source_directory",
        "expected_tree_sha256",
        "expected_file_count",
        "approved",
        "approved_by",
    }
    if set(value) != required or value.get("approved") is not True:
        raise ValueError(
            "skill source admission requires the exact host-attested materialization envelope"
        )
    source = Path(str(value.get("source_directory") or ""))
    approved_by = str(value.get("approved_by") or "")
    admission = SkillStudio(root.resolve(strict=True)).admit_source(
        source,
        approved_by=approved_by,
        expected_tree_sha256=value.get("expected_tree_sha256"),
        expected_file_count=value.get("expected_file_count"),
    )
    if not isinstance(admission, Mapping):
        raise RuntimeError("attested skill source admission did not return a receipt")
    return {
        "schema_version": "px.skill-source-admission/1.0",
        "source_token": str(admission["source_token"]),
        "source_directory": str(admission["source_directory"]),
        "source_tree_sha256": str(admission["source_tree_sha256"]),
        "file_count": int(admission["file_count"]),
    }


READ_ONLY_STUDIO_OPERATIONS = frozenset(
    {"runs", "status", "browse", "dry-run", "preview", "next-version", "identity-absence"}
)


def _approval_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in value.items()
        if key not in {"approval_capability", "approved", "approved_by"}
    }


def studio_operation(
    root: Path, kind: str, operation: str, value: Mapping[str, Any]
) -> dict[str, object]:
    require_studio_operation(kind, operation)
    value = dict(value)
    if kind == "agent":
        _require_standard_agent_domain(value)
    if operation == "identity-absence":
        if set(value) != {"identity"}:
            raise ValueError("identity-absence requires exactly one identity")
        return studio_identity_absence(root.resolve(strict=True), kind, str(value["identity"]))
    if operation == "next-version":
        physical_keys = {"identity", "source_version"}
        external_keys = {
            "identity",
            "source_version",
            "source_scope",
            "source_revision_sha256",
            "source_content_sha256",
        }
        if frozenset(value) not in {
            frozenset(physical_keys),
            frozenset(external_keys),
        }:
            raise StudioVersionConflict("allocation-envelope-invalid")
        try:
            return allocate_studio_version(
                root.resolve(strict=True),
                kind,
                str(value["identity"]),
                str(value["source_version"]),
                source_scope=(
                    "studio-physical"
                    if "source_scope" not in value
                    else value["source_scope"]
                ),
                source_revision_sha256=(
                    value["source_revision_sha256"]
                    if "source_revision_sha256" in value
                    else None
                ),
                source_content_sha256=(
                    value["source_content_sha256"]
                    if "source_content_sha256" in value
                    else None
                ),
            )
        except StudioVersionConflict:
            raise
        except (TypeError, ValueError) as error:
            raise StudioVersionConflict("allocation-source-invalid") from error
    if operation not in READ_ONLY_STUDIO_OPERATIONS:
        if value.get("approved") is True and not value.get("approval_capability"):
            raise PermissionError("caller-authored approval booleans are not authority")
        proof = value.get("approval_capability")
        if not isinstance(proof, Mapping):
            raise PermissionError("payload-bound single-use operation approval is required")
        supplied_payload = _approval_payload(value)
        approval = StudioAuthorityStore(root.resolve(strict=True)).consume_host_operation_approval(
            proof,
            kind=kind,
            operation=operation,
            supplied_payload=supplied_payload or None,
        )
        approved_payload = approval.get("payload")
        if not isinstance(approved_payload, Mapping):
            raise PermissionError("host-signed Studio approval payload is invalid")
        value = dict(approved_payload)
        value["approved"] = True
        value["approved_by"] = str(approval["approved_by"])
    """Execute one explicit lifecycle transition through the canonical controller."""
    root = root.resolve(strict=True)
    if kind == "knowledge":
        controller = KnowledgeCoreController(
            root,
            policy_root=framework_root(),
            read_only=operation == "browse",
        )
        if operation == "browse":
            return controller.browse(
                query=str(value.get("query") or ""),
                limit=int(value.get("limit", 100)),
            )
        if operation == "observe-experience":
            measurements = value.get("measurements")
            if not isinstance(measurements, Mapping):
                raise ValueError("experience capture requires numeric measurements")
            return controller.observe_experience(
                pipeline_id=str(value.get("pipeline_id") or "") or None,
                operation_id=str(value.get("operation_id") or ""),
                task_class=str(value.get("task_class") or ""),
                outcome=str(value.get("outcome") or ""),
                measurements=measurements,
                capability_ids=_strings(value.get("capability_ids", [])),
                environment_sha256=str(value.get("environment_sha256") or ""),
                source_ids=_strings(value.get("source_ids", [])),
                evidence_refs=_strings(value.get("evidence_refs", [])),
                approved=bool(value.get("approved", False)),
                observed_by=str(value.get("approved_by") or ""),
            )
        if operation == "extract-pattern":
            return controller.extract_learning_pattern(
                str(value.get("pipeline_id") or ""),
                metric=str(value.get("metric") or ""),
                higher_is_better=bool(value.get("higher_is_better", True)),
                interpretation=str(value.get("interpretation") or ""),
                applicability=_strings(value.get("applicability", [])),
                approved=bool(value.get("approved", False)),
                extracted_by=str(value.get("approved_by") or ""),
            )
        if operation == "form-hypothesis":
            dependencies = value.get("dependency_sha256", {})
            if not isinstance(dependencies, Mapping):
                raise ValueError("learning dependencies must be an object")
            return controller.form_learning_hypothesis(
                str(value.get("pipeline_id") or ""),
                unit_id=str(value.get("unit_id") or ""),
                kind=str(value.get("kind") or ""),
                claim=str(value.get("claim") or ""),
                incumbent_artifact=value.get("incumbent_artifact"),
                challenger_artifact=value.get("challenger_artifact"),
                dependency_sha256={str(key): str(item) for key, item in dependencies.items()},
                approved=bool(value.get("approved", False)),
                formed_by=str(value.get("approved_by") or ""),
            )
        if operation == "record-trial":
            return controller.record_learning_trial(
                str(value.get("pipeline_id") or ""),
                winner=str(value.get("winner") or ""),
                evidence_ref=str(value.get("evidence_ref") or ""),
                approved=bool(value.get("approved", False)),
                recorded_by=str(value.get("approved_by") or ""),
            )
        if operation == "research-validate":
            references = value.get("references", [])
            if not isinstance(references, list) or any(
                not isinstance(item, Mapping) for item in references
            ):
                raise ValueError("research references must be an array of objects")
            return controller.validate_learning_research(
                str(value.get("pipeline_id") or ""),
                question=str(value.get("question") or ""),
                references=references,
                better_alternative_found=bool(value.get("better_alternative_found", False)),
                conclusion=str(value.get("conclusion") or ""),
                secondary_artifact=value.get("secondary_artifact"),
                approved=bool(value.get("approved", False)),
                validated_by=str(value.get("approved_by") or ""),
            )
        if operation == "final-validate":
            return controller.final_validate_learning(
                str(value.get("pipeline_id") or ""),
                validation_evidence_ref=str(value.get("validation_evidence_ref") or ""),
                partial_units=_strings(value.get("partial_units", [])),
                approved=bool(value.get("approved", False)),
                validated_by=str(value.get("approved_by") or ""),
            )
        if operation == "admit-learning":
            return controller.admit_learning_candidate(
                str(value.get("pipeline_id") or ""),
                approved=bool(value.get("approved", False)),
                admitted_by=str(value.get("approved_by") or ""),
            )
        if operation == "measure-reuse":
            return controller.measure_learning_reuse(
                str(value.get("pipeline_id") or ""),
                uses=int(value.get("uses", 0)),
                successes=int(value.get("successes", 0)),
                regressions=int(value.get("regressions", 0)),
                approved=bool(value.get("approved", False)),
                measured_by=str(value.get("approved_by") or ""),
            )
        if operation == "propose":
            candidate = value.get("candidate")
            if not isinstance(candidate, Mapping):
                raise ValueError("knowledge proposal requires a candidate object")
            return controller.propose(
                candidate,
                source_ids=_strings(value.get("source_ids", [])),
                evidence_refs=_strings(value.get("evidence_refs", [])),
                approved=bool(value.get("approved", False)),
                proposed_by=str(value.get("approved_by") or ""),
            )
        if operation == "verify":
            return controller.verify(
                str(value.get("proposal_id") or ""),
                approved=bool(value.get("approved", False)),
                verified_by=str(value.get("approved_by") or ""),
            )
        if operation == "approve":
            return controller.approve(
                str(value.get("proposal_id") or ""),
                approved=bool(value.get("approved", False)),
                approved_by=str(value.get("approved_by") or ""),
            )
        if operation == "promote":
            return controller.promote(
                str(value.get("proposal_id") or ""),
                approved=bool(value.get("approved", False)),
                promoted_by=str(value.get("approved_by") or ""),
            )
        if operation == "reject":
            return controller.reject(
                str(value.get("proposal_id") or ""),
                approved=bool(value.get("approved", False)),
                rejected_by=str(value.get("approved_by") or ""),
                reason=str(value.get("reason") or ""),
            )
        if operation == "rollback":
            return controller.rollback(
                str(value.get("record_id") or ""),
                str(value.get("target_sha256") or ""),
                approved=bool(value.get("approved", False)),
                approved_by=str(value.get("approved_by") or ""),
                evidence_refs=_strings(value.get("evidence_refs", [])),
                expected_head_sha256=str(value.get("expected_head_sha256") or "") or None,
            )
        if operation == "recover":
            return controller.recover(
                approved=bool(value.get("approved", False)),
                recovered_by=str(value.get("approved_by") or ""),
            )
        raise ValueError(f"unsupported knowledge Studio operation: {operation}")
    if operation == "create":
        return create_draft(root, kind, value)
    if operation == "admit-source":
        if kind != "skill":
            raise ValueError("source admission is only valid for Skill Studio")
        return admit_skill_source(root, value)
    if kind == "agent":
        if operation in {"runs", "status"}:
            run_root = root.resolve(strict=True) / ".engineering-bootstrap/studios/agents/sessions"
            if operation == "runs" and not run_root.is_dir():
                return {"schema_version": "px.studio-run-list/1.0", "kind": "agent", "runs": [], "returned": 0, "total_authenticated": 0, "has_more": False, "invalid": []}
            control = DurableRunControl.open_existing(
                root.resolve(strict=True),
                run_root,
            )
            return control.list_snapshots(kind="agent", limit=int(value.get("limit", 100))) if operation == "runs" else control.read_snapshot(str(value.get("run_id") or ""))
        controller = AgentRuntimeController(root)
        if operation in {"pause", "cancel", "stop"}:
            return controller.request_lifecycle(
                str(value.get("run_id") or ""),
                operation,
                approved=bool(value.get("approved", False)),
                approved_by=str(value.get("approved_by") or ""),
            )
        if operation == "reconcile":
            return controller.reconcile_sessions(
                approved=bool(value.get("approved", False)),
                approved_by=str(value.get("approved_by") or ""),
                stale_after_seconds=float(value.get("stale_after_seconds", 60.0)),
            )
        spec, _ = _agent(value)
        if operation == "preview":
            return controller.preview(spec)
        if operation == "test":
            return controller.test_candidate(spec)
        if operation == "register-authority":
            bindings, grants = _authority(value)
            return controller.register_revision_authority(spec, bindings, grants)
        if operation == "admit":
            return controller.admit(spec)
        if operation == "prepare-host-run":
            task = value.get("task")
            if not isinstance(task, Mapping):
                raise ValueError("agent host run requires a bounded task object")
            return controller.prepare_host_run(
                spec, task=task, approval=bool(value.get("approved", False))
            )
        if operation == "complete-host-run":
            task = value.get("task")
            host_result = value.get("host_result")
            if not isinstance(task, Mapping) or not isinstance(host_result, Mapping):
                raise ValueError("agent host completion requires task and host result objects")
            return controller.complete_host_run(
                spec,
                run_id=str(value.get("run_id") or ""),
                task=task,
                host_result=host_result,
                approval=bool(value.get("approved", False)),
            )
        if operation == "run":
            task = value.get("task")
            if not isinstance(task, Mapping):
                raise ValueError("agent run requires a bounded task object")
            return controller.invoke_harness(
                spec, task=task, approval=bool(value.get("approved", False))
            )
        if operation == "start":
            task = value.get("task")
            if not isinstance(task, Mapping):
                raise ValueError("agent start requires a bounded task object")
            if spec.harness_id == "harness:vscode-lm":
                return controller.prepare_host_run(
                    spec, task=task, approval=bool(value.get("approved", False))
                )
            return controller.start_harness(
                spec, task=task, approval=bool(value.get("approved", False))
            )
        if operation == "resume":
            task = value.get("task")
            if not isinstance(task, Mapping):
                raise ValueError("agent resume requires a bounded task object")
            return controller.resume_harness(
                spec,
                run_id=str(value.get("run_id") or ""),
                task=task,
                approval=bool(value.get("approved", False)),
            )
    elif kind == "workflow":
        if operation in {"runs", "status"}:
            run_root = root.resolve(strict=True) / ".engineering-bootstrap/studios/workflows/sessions"
            if operation == "runs" and not run_root.is_dir():
                return {"schema_version": "px.studio-run-list/1.0", "kind": "workflow", "runs": [], "returned": 0, "total_authenticated": 0, "has_more": False, "invalid": []}
            control = DurableRunControl.open_existing(
                root.resolve(strict=True),
                run_root,
            )
            return control.list_snapshots(kind="workflow", limit=int(value.get("limit", 100))) if operation == "runs" else control.read_snapshot(str(value.get("run_id") or ""))
        studio = WorkflowStudio(root)
        if operation in {"pause", "cancel", "stop"}:
            return studio.request_lifecycle(
                str(value.get("run_id") or ""),
                operation,
                approved=bool(value.get("approved", False)),
                approved_by=str(value.get("approved_by") or ""),
            )
        if operation == "reconcile":
            return studio.reconcile(
                approved=bool(value.get("approved", False)),
                approved_by=str(value.get("approved_by") or ""),
                stale_after_seconds=float(value.get("stale_after_seconds", 60.0)),
            )
        definition = _workflow(value)
        if operation == "register-authority":
            bindings, grants = _authority(value)
            adapters = value.get("executor_adapters", {})
            if not isinstance(adapters, Mapping):
                raise ValueError("workflow executor adapters must be an object")
            return studio.register_revision_authority(
                definition,
                bindings,
                grants,
                {str(key): str(item) for key, item in adapters.items()},
            )
        if operation == "validate":
            return studio.validate_and_admit(definition)
        if operation == "dry-run":
            return studio.dry_run(definition)
        if operation == "approve":
            return {
                "schema_version": "px.workflow-approval-result/1.0",
                "approval_id": studio.issue_approval(
                    definition,
                    str(value.get("node_id") or ""),
                    approved_by=str(value.get("approved_by") or ""),
                    ttl_seconds=int(value.get("ttl_seconds", 300)),
                ),
            }
        if operation == "run":
            inputs = value.get("run_inputs", {})
            approvals = value.get("approvals", {})
            if not isinstance(inputs, Mapping) or not isinstance(approvals, Mapping):
                raise ValueError("workflow inputs and approvals must be objects")
            return studio.execute(
                definition,
                {str(key): item for key, item in inputs.items()},
                {str(key): str(item) for key, item in approvals.items()},
                approval=bool(value.get("approved", False)),
            )
        if operation in {"start", "resume"}:
            inputs = value.get("run_inputs", {})
            approvals = value.get("approvals", {})
            if not isinstance(inputs, Mapping) or not isinstance(approvals, Mapping):
                raise ValueError("workflow inputs and approvals must be objects")
            normalized_inputs = {str(key): item for key, item in inputs.items()}
            normalized_approvals = {
                str(key): str(item) for key, item in approvals.items()
            }
            if operation == "start":
                return studio.start(
                    definition,
                    normalized_inputs,
                    normalized_approvals,
                    approval=bool(value.get("approved", False)),
                )
            return studio.resume(
                definition,
                normalized_inputs,
                normalized_approvals,
                run_id=str(value.get("run_id") or ""),
                approval=bool(value.get("approved", False)),
            )
    elif kind == "skill":
        studio = SkillStudio(root)
        package, _ = _skill(value)
        if operation == "validate":
            return studio.validate(package)
        if operation == "admit":
            return studio.admit(
                package,
                approved=bool(value.get("approved", False)),
                approver=str(value.get("approved_by") or ""),
            )
        if operation == "promote":
            receipt = studio.promote(package, approved=bool(value.get("approved", False)))
            receipt_path = _skill_promotion_receipt_path(
                root, package.skill_id, package.version
            )
            return {
                **receipt,
                "state": "promoted",
                "promotion_receipt_relative": receipt_path.relative_to(root).as_posix(),
            }
        if operation == "rollback":
            supplied = Path(str(value.get("promotion_receipt") or ""))
            receipt = supplied if supplied.is_absolute() else root / supplied
            resolved = receipt.resolve(strict=True)
            try:
                resolved.relative_to(
                    (root / ".engineering-bootstrap" / "studios" / "skills").resolve(
                        strict=True
                    )
                )
            except ValueError as error:
                raise PermissionError(
                    "skill rollback receipt escapes Studio custody"
                ) from error
            rollback = studio.rollback(
                resolved,
                approved=bool(value.get("approved", False)),
                approver=str(value.get("approved_by") or ""),
            )
            return {**rollback, "state": "rolled-back"}
    raise ValueError(f"unsupported {kind} Studio operation: {operation}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pacify-X versioned studio adapter")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--kind", choices=tuple(sorted(STUDIO_KINDS)), required=True
    )
    parser.add_argument(
        "--operation",
        choices=tuple(sorted(ALL_STUDIO_OPERATIONS)),
        default="create",
    )
    payload_group = parser.add_mutually_exclusive_group(required=True)
    payload_group.add_argument("--payload-base64")
    payload_group.add_argument("--payload-stdin", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = _stdin_payload() if args.payload_stdin else _payload(args.payload_base64)
        result = studio_operation(args.root, args.kind, args.operation, value)
    except StudioVersionConflict as error:
        envelope = {
            "schema_version": "px.studio-operation-error/1.0",
            "code": "STUDIO_VERSION_CONFLICT",
            "reason": error.reason,
        }
        sys.stderr.write(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n"
        )
        return 2
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
