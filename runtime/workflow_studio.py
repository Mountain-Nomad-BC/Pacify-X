"""Authenticated DAG authoring and owned, deadline-bound workflow execution."""

from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Mapping, Sequence
from uuid import uuid4

from .file_lock import FileLock
from .process_supervisor import ProcessSupervisor
from .resource_lifecycle import ResourceManager, RunState
from .studio_filesystem import (
    assert_exact_tree,
    publish_directory_no_replace,
    read_bounded_regular_file,
)
from .studio_authority import (
    StudioAuthorityStore,
    studio_authority_locator_environment,
)
from .studio_run_control import DurableControlSignal, DurableRunControl, TERMINAL_STATES
from .studio_worker_launch import (
    launch_studio_worker,
    wait_for_paused_worker_closure,
)
from .studio_models import (
    CapabilityBinding,
    EffectGrant,
    WorkflowDefinition,
    WorkflowNode,
    canonical_bytes,
    digest,
    record as studio_record,
    revalidate_studio_version_allocation,
    studio_revision_lock,
    StudioVersionConflict,
    valid_canonical_utc,
    verify_safe_ancestors,
    write_json_atomic,
    write_versioned_record,
)


class _WorkflowLifecycleSignal(RuntimeError):
    def __init__(self, requested_state: str) -> None:
        self.requested_state = requested_state
        super().__init__(requested_state)


class _WorkflowBranchSkipped(RuntimeError):
    def __init__(self, node_id: str, ports: Sequence[str]) -> None:
        self.node_id = node_id
        self.ports = tuple(sorted(map(str, ports)))
        super().__init__(
            f"workflow branch disabled required inputs for {node_id}: {', '.join(self.ports)}"
        )


_READ_ONLY_WORKFLOW_EFFECTS = frozenset(
    {"read", "inspect", "list", "observe", "query"}
)

_WORKFLOW_EDITOR_LAYOUT_SCHEMA = "px.workflow-editor-layout/1.0"
_WORKFLOW_REVISION_RECEIPT_SCHEMA = "px.workflow-revision-receipt/1.2"
_WORKFLOW_EDITOR_COORDINATE_BOUND = 20_000
_MAX_CREATE_CLEANUP_WARNINGS = 8
_MAX_CREATE_CLEANUP_WARNING_CHARS = 240
_MAX_WORKFLOW_REVISION_FILE_BYTES = 4 * 1024 * 1024


def _bounded_cleanup_warnings(errors: Sequence[object]) -> list[str]:
    """Return bounded warnings without converting a committed create into failure."""

    warnings: list[str] = []
    for error in errors[:_MAX_CREATE_CLEANUP_WARNINGS]:
        warning = str(error).strip()
        if warning:
            warnings.append(warning[:_MAX_CREATE_CLEANUP_WARNING_CHARS])
    return warnings


def _read_revision_bytes(path: Path) -> bytes:
    return read_bounded_regular_file(
        path,
        _MAX_WORKFLOW_REVISION_FILE_BYTES,
        lambda: ValueError("workflow revision file is invalid or oversized"),
    )


def _read_revision_json(path: Path) -> object:
    return json.loads(_read_revision_bytes(path).decode("utf-8"))


def _validate_workflow_revision_receipt(
    value: object, expected_values: Mapping[str, object]
) -> dict[str, object]:
    """Validate the exact durable workflow receipt contract."""

    if (
        not isinstance(value, Mapping)
        or set(value) != {*expected_values, "created_utc"}
        or not valid_canonical_utc(value.get("created_utc"))
        or any(value.get(key) != expected for key, expected in expected_values.items())
    ):
        raise ValueError("immutable workflow creation receipt does not match revision")
    return dict(value)


def _normalize_editor_layout(
    definition: WorkflowDefinition, editor_layout: Mapping[str, object]
) -> dict[str, dict[str, int | float]]:
    node_ids = {node.node_id for node in definition.nodes}
    if any(not isinstance(key, str) for key in editor_layout) or set(editor_layout) != node_ids:
        raise ValueError("workflow editor layout must match the exact node set")
    normalized: dict[str, dict[str, int | float]] = {}
    for node in definition.nodes:
        position = editor_layout[node.node_id]
        if not isinstance(position, Mapping) or set(position) != {"x", "y"}:
            raise ValueError("workflow editor layout positions require only x and y")
        x = position["x"]
        y = position["y"]
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
            or not math.isfinite(x)
            or not math.isfinite(y)
            or abs(x) > _WORKFLOW_EDITOR_COORDINATE_BOUND
            or abs(y) > _WORKFLOW_EDITOR_COORDINATE_BOUND
        ):
            raise ValueError(
                "workflow editor layout coordinates must be finite and within 20000"
            )
        normalized[node.node_id] = {"x": x, "y": y}
    return normalized


def _editor_layout_envelope(
    definition: WorkflowDefinition,
    editor_layout: Mapping[str, object],
    revision_sha256: str,
) -> dict[str, object]:
    normalized = _normalize_editor_layout(definition, editor_layout)
    return {
        "schema_version": _WORKFLOW_EDITOR_LAYOUT_SCHEMA,
        "workflow_id": definition.workflow_id,
        "version": definition.version,
        "revision_sha256": revision_sha256,
        "layout": normalized,
        "layout_sha256": digest(normalized),
    }


def _normalized_scope(value: object) -> str:
    scope = str(value or "").strip().replace("\\", "/").rstrip("/")
    return scope.casefold() or "*"


def _scopes_overlap(left: str, right: str) -> bool:
    if "*" in {left, right} or left == right:
        return True
    return left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _claims_conflict(
    left: Sequence[tuple[str, str, str]],
    right: Sequence[tuple[str, str, str]],
) -> bool:
    for left_scope, left_mode, _left_effect in left:
        for right_scope, right_mode, _right_effect in right:
            if _scopes_overlap(left_scope, right_scope) and "exclusive" in {
                left_mode,
                right_mode,
            }:
                return True
    return False


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _topology(definition: WorkflowDefinition) -> tuple[str, ...]:
    adjacency = {node.node_id: [] for node in definition.nodes}
    indegree = {node.node_id: 0 for node in definition.nodes}
    for edge in definition.edges:
        adjacency[edge.source_node].append(edge.target_node)
        indegree[edge.target_node] += 1
    ready = sorted(node for node, count in indegree.items() if count == 0)
    result = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for target in sorted(adjacency[current]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    return tuple(result)


def _matches(value: object, data_type: str) -> bool:
    return {
        "json": True,
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, Mapping),
        "array": isinstance(value, (list, tuple)),
    }.get(data_type, False)


def _edge_enabled(condition: str, source: Mapping[str, object], port: str) -> bool:
    if condition == "always":
        return True
    if condition == "never":
        return False
    if condition == "source-present":
        return port in source
    if condition == "source-truthy":
        return bool(source.get(port))
    if condition == "source-falsy":
        return port in source and not bool(source.get(port))
    raise ValueError(f"unsupported edge condition: {condition}")


def _adapter_contract_reasons(node: WorkflowNode, adapter: str) -> list[str]:
    inputs = {port.name: port.data_type for port in node.inputs}
    outputs = {port.name: port.data_type for port in node.outputs}
    numeric = {"integer", "number"}
    if node.kind in {"branch", "join"} and adapter != "identity":
        return [f"{node.kind}_requires_identity_adapter"]
    if adapter == "identity":
        return [] if inputs == outputs else ["identity_requires_matching_input_output_ports"]
    if adapter == "increment":
        return [] if set(inputs) == {"value"} and set(outputs) == {"value"} and inputs["value"] in numeric and outputs["value"] in numeric else ["increment_requires_numeric_value_input_and_output"]
    if adapter == "double":
        return [] if set(inputs) == {"value"} and set(outputs) == {"result"} and inputs["value"] in numeric and outputs["result"] in numeric else ["double_requires_numeric_value_input_and_result_output"]
    if adapter == "sleep":
        return [] if set(inputs) == {"seconds"} and set(outputs) == {"seconds"} and inputs["seconds"] in numeric and outputs["seconds"] in numeric else ["sleep_requires_numeric_seconds_input_and_output"]
    if adapter == "fail":
        return []
    return ["executor_adapter_not_admitted"]


class WorkflowStudio:
    MAX_PARALLEL_NODES = 4

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve(strict=True)
        if self.project_root == Path(self.project_root.anchor):
            raise ValueError("workflow root must be bounded")
        self.state_root = (
            self.project_root / ".engineering-bootstrap" / "studios" / "workflows"
        )
        self.manager = ResourceManager(self.state_root / "resources.json")
        self.supervisor = ProcessSupervisor(self.manager)
        self.authority = StudioAuthorityStore(self.project_root)
        self.run_control = DurableRunControl(
            self.project_root, self.state_root / "sessions"
        )

    def register_authority(
        self,
        bindings: Sequence[CapabilityBinding],
        grants: Sequence[EffectGrant],
        executor_adapters: Mapping[str, str],
    ) -> dict[str, object]:
        return self.authority.register_authority_transaction(
            tuple(bindings), tuple(grants), executor_adapters
        )

    def register_revision_authority(
        self,
        definition: WorkflowDefinition,
        bindings: Sequence[CapabilityBinding],
        grants: Sequence[EffectGrant],
        executor_adapters: Mapping[str, str],
    ) -> dict[str, object]:
        component = (
            f"{re.sub(r'[^a-z0-9._-]+', '-', definition.workflow_id).strip('-')}-"
            f"{hashlib.sha256(definition.workflow_id.encode()).hexdigest()[:8]}"
        )
        revision = self.state_root / component / "revisions" / definition.version
        record_path = revision / "record.json"
        authority_path = revision / "authority-definition.json"
        if not record_path.is_file() or _read_revision_json(record_path) != json.loads(
            canonical_bytes(studio_record(definition))
        ):
            raise PermissionError("immutable workflow revision does not match")
        if not authority_path.is_file():
            raise PermissionError("immutable workflow revision has no authority definition")
        envelope = _read_revision_json(authority_path)
        record = envelope.get("record") if isinstance(envelope, Mapping) else None
        if (
            not isinstance(record, Mapping)
            or envelope.get("sha256") != digest(record)
            or record.get("kind") != "workflow"
            or record.get("subject_id") != definition.workflow_id
            or record.get("version") != definition.version
            or record.get("bindings")
            != json.loads(canonical_bytes([asdict(item) for item in bindings]))
            or record.get("grants")
            != json.loads(canonical_bytes([asdict(item) for item in grants]))
            or record.get("executor_adapters")
            != {str(key): str(value) for key, value in executor_adapters.items()}
        ):
            raise PermissionError("workflow authority does not match its immutable revision")
        return self.register_authority(bindings, grants, executor_adapters)

    def save_revision(
        self,
        definition: WorkflowDefinition,
        *,
        authority_definition: Mapping[str, object] | None = None,
        editor_layout: Mapping[str, object] | None = None,
        version_allocation: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if editor_layout is None:
            if version_allocation is not None:
                raise ValueError(
                    "version allocations require a content-bound workflow revision"
                )
            return self._save_revision_locked(
                definition,
                authority_definition=authority_definition,
                editor_layout=None,
            )
        lock_path = studio_revision_lock(
            self.project_root, "workflow", definition.workflow_id
        )
        component = (
            f"{re.sub(r'[^a-z0-9._-]+', '-', definition.workflow_id).strip('-')}-"
            f"{hashlib.sha256(definition.workflow_id.encode()).hexdigest()[:8]}"
        )
        revision = self.state_root / component / "revisions" / definition.version
        verify_safe_ancestors(self.project_root, lock_path)
        verify_safe_ancestors(
            self.project_root,
            revision,
            include_target=os.path.lexists(revision),
        )
        with FileLock(
            lock_path,
            timeout_seconds=10,
        ):
            verify_safe_ancestors(self.project_root, lock_path)
            verify_safe_ancestors(
                self.project_root,
                revision,
                include_target=os.path.lexists(revision),
            )
            if version_allocation is not None and not revision.exists():
                revalidate_studio_version_allocation(
                    self.project_root,
                    "workflow",
                    definition.workflow_id,
                    definition.version,
                    version_allocation,
                )
            return self._save_revision_locked(
                definition,
                authority_definition=authority_definition,
                editor_layout=editor_layout,
            )

    def _save_revision_locked(
        self,
        definition: WorkflowDefinition,
        *,
        authority_definition: Mapping[str, object] | None = None,
        editor_layout: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        # Preserve the pre-layout direct API for existing runtime callers.  The
        # bounded Studio API always supplies editor_layout and therefore always
        # takes the content-bound publication path below.
        if editor_layout is None:
            if authority_definition is not None:
                raise ValueError(
                    "workflow Studio revisions require a content-bound editor layout"
                )
            path, created = write_versioned_record(
                self.project_root,
                "workflows",
                definition.workflow_id,
                definition.version,
                definition,
                include_created=True,
            )
            return {
                "schema_version": "px.workflow-revision-receipt/1.1",
                "workflow_id": definition.workflow_id,
                "version": definition.version,
                "revision_sha256": hashlib.sha256(_read_revision_bytes(path)).hexdigest(),
                "definition_state": "saved",
                "runnable_state": "unvalidated",
                "run_state": "never_run",
                "path": path.relative_to(self.project_root).as_posix(),
                "created": created,
                "authority_state": "none",
                "authority_definition_path": None,
                "editor_layout_state": "legacy-unavailable",
            }

        normalized_layout = _normalize_editor_layout(definition, editor_layout)
        component = (
            f"{re.sub(r'[^a-z0-9._-]+', '-', definition.workflow_id).strip('-')}-"
            f"{hashlib.sha256(definition.workflow_id.encode()).hexdigest()[:8]}"
        )
        revision = self.state_root / component / "revisions" / definition.version
        path = revision / "record.json"
        authority_path = revision / "authority-definition.json"
        layout_path = revision / "editor-layout.json"
        receipt_path = revision / "creation-receipt.json"
        expected_record = json.loads(canonical_bytes(studio_record(definition)))
        expected_authority = (
            json.loads(canonical_bytes(dict(authority_definition)))
            if authority_definition is not None
            else None
        )
        if revision.exists():
            try:
                optional_names = {"authority-definition.json", "admission-receipt.json"}
                present_optional = {
                    name
                    for name in optional_names
                    if (revision / name).exists() or (revision / name).is_symlink()
                }
                assert_exact_tree(
                    revision,
                    {
                        "record.json",
                        "editor-layout.json",
                        "creation-receipt.json",
                        *present_optional,
                    },
                    set(),
                    5,
                    lambda: StudioVersionConflict(
                        "immutable-workflow-revision-differs"
                    ),
                )
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or _read_revision_json(path) != expected_record
                    or not layout_path.is_file()
                    or layout_path.is_symlink()
                    or not receipt_path.is_file()
                    or receipt_path.is_symlink()
                    or (
                        expected_authority is None
                        and (authority_path.exists() or authority_path.is_symlink())
                    )
                    or (
                        expected_authority is not None
                        and (
                            not authority_path.is_file()
                            or authority_path.is_symlink()
                            or _read_revision_json(authority_path)
                            != expected_authority
                        )
                    )
                ):
                    raise FileExistsError
                revision_sha256 = hashlib.sha256(_read_revision_bytes(path)).hexdigest()
                expected_layout = _editor_layout_envelope(
                    definition, normalized_layout, revision_sha256
                )
                if _read_revision_json(layout_path) != expected_layout:
                    raise FileExistsError
                existing = _read_revision_json(receipt_path)
                expected_receipt_values = {
                    "schema_version": _WORKFLOW_REVISION_RECEIPT_SCHEMA,
                    "operation": "workflow.save_revision",
                    "workflow_id": definition.workflow_id,
                    "version": definition.version,
                    "revision_sha256": revision_sha256,
                    "definition_sha256": expected_record["sha256"],
                    "definition_state": "saved",
                    "runnable_state": "unvalidated",
                    "run_state": "never_run",
                    "path": path.relative_to(self.project_root).as_posix(),
                    "created": True,
                    "editor_layout_state": "content-bound",
                    "editor_layout_path": layout_path.relative_to(
                        self.project_root
                    ).as_posix(),
                    "editor_layout_sha256": expected_layout["layout_sha256"],
                    "authority_state": (
                        "defined" if expected_authority is not None else "none"
                    ),
                    "authority_definition_path": (
                        authority_path.relative_to(self.project_root).as_posix()
                        if expected_authority is not None
                        else None
                    ),
                    "host_authority_retained": True,
                }
                existing = _validate_workflow_revision_receipt(
                    existing, expected_receipt_values
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError, FileExistsError) as error:
                raise StudioVersionConflict(
                    "immutable-workflow-revision-differs:immutable workflow revision differs or is incomplete"
                ) from error
            return {**existing, "created": False, "idempotent_replay": True}

        prepared_root = self.state_root / "prepared"
        verify_safe_ancestors(self.project_root, prepared_root)
        prepared_root.mkdir(parents=True, exist_ok=True)
        run_id = f"workflow-create-{uuid4().hex}"
        resource = self.manager.create_workspace(
            prepared_root,
            project_id=definition.workflow_id,
            run_id=run_id,
            lane_id=definition.workflow_id,
            creator=definition.owner,
            prefix=f"{component}-{definition.version}-",
        )
        prepared = Path(str(resource.path))
        try:
            prepared_record = prepared / "record.json"
            write_json_atomic(prepared_record, expected_record)
            revision_sha256 = hashlib.sha256(prepared_record.read_bytes()).hexdigest()
            expected_layout = _editor_layout_envelope(
                definition, normalized_layout, revision_sha256
            )
            if expected_authority is not None:
                write_json_atomic(
                    prepared / "authority-definition.json", expected_authority
                )
            write_json_atomic(prepared / "editor-layout.json", expected_layout)
            receipt = {
                "schema_version": _WORKFLOW_REVISION_RECEIPT_SCHEMA,
                "operation": "workflow.save_revision",
                "created_utc": _now(),
                "workflow_id": definition.workflow_id,
                "version": definition.version,
                "revision_sha256": revision_sha256,
                "definition_sha256": expected_record["sha256"],
                "definition_state": "saved",
                "runnable_state": "unvalidated",
                "run_state": "never_run",
                "path": path.relative_to(self.project_root).as_posix(),
                "created": True,
                "authority_state": (
                    "defined" if expected_authority is not None else "none"
                ),
                "authority_definition_path": (
                    authority_path.relative_to(self.project_root).as_posix()
                    if expected_authority is not None
                    else None
                ),
                "editor_layout_state": "content-bound",
                "editor_layout_path": layout_path.relative_to(
                    self.project_root
                ).as_posix(),
                "editor_layout_sha256": expected_layout["layout_sha256"],
                "host_authority_retained": True,
            }
            receipt = _validate_workflow_revision_receipt(
                receipt,
                {key: value for key, value in receipt.items() if key != "created_utc"},
            )
            write_json_atomic(prepared / "creation-receipt.json", receipt)
            verify_safe_ancestors(self.project_root, revision)
            revision.parent.mkdir(parents=True, exist_ok=True)
            verify_safe_ancestors(self.project_root, revision)
            try:
                publish_directory_no_replace(prepared, revision)
            except OSError as error:
                if os.path.lexists(revision):
                    raise StudioVersionConflict("publication-collision") from error
                raise
        except Exception as publish_error:
            try:
                self.manager.mark_run_ended(run_id, RunState.FAILED)
            except Exception as cleanup_error:
                publish_error.add_note(
                    f"run failure closure degraded: {str(cleanup_error)[:240]}"
                )
            try:
                self.manager.reclaim(
                    resource.resource_id,
                    reason="workflow_revision_publish_failed",
                    apply=True,
                )
            except Exception as cleanup_error:
                publish_error.add_note(
                    f"failed resource reclaim degraded: {str(cleanup_error)[:240]}"
                )
            raise
        post_publish_errors: list[object] = []
        try:
            self.manager.mark_run_ended(run_id, RunState.COMPLETED)
        except Exception as error:  # Publication is already immutable at this point.
            post_publish_errors.append(f"run closure degraded: {error}")
        try:
            cleanup = self.manager.reclaim(
                resource.resource_id,
                reason="workflow_revision_published",
                apply=True,
            )
        except Exception as error:  # Preserve committed-create truth in the response.
            post_publish_errors.append(f"resource reclaim degraded: {error}")
        else:
            post_publish_errors.extend(cleanup.errors)
        cleanup_warnings = _bounded_cleanup_warnings(post_publish_errors)
        return {
            **receipt,
            **({"cleanup_warnings": cleanup_warnings} if cleanup_warnings else {}),
        }

    def validate_and_admit(self, definition: WorkflowDefinition) -> dict[str, object]:
        path = write_versioned_record(
            self.project_root,
            "workflows",
            definition.workflow_id,
            definition.version,
            definition,
        )
        reasons: list[str] = []
        authority_hashes: dict[str, str] = {}
        for node in definition.nodes:
            try:
                binding, authority_hashes[f"binding:{node.executor_binding_id}"] = (
                    self.authority.resolve_binding(
                        node.executor_binding_id,
                        subject_kind="workflow",
                        subject_id=definition.workflow_id,
                    )
                )
                executor, authority_hashes[f"executor:{node.executor_binding_id}"] = (
                    self.authority.resolve_executor(node.executor_binding_id)
                )
                reasons.extend(
                    f"{node.node_id}:{reason}"
                    for reason in _adapter_contract_reasons(
                        node, str(executor.get("adapter_id") or "")
                    )
                )
                if set(node.effect_grant_ids) != set(
                    binding.get("effect_grant_ids", [])
                ):
                    reasons.append(f"{node.node_id}:grant_binding_mismatch")
            except PermissionError as error:
                reasons.append(f"{node.node_id}:authority_invalid:{error}")
            for grant_id in node.effect_grant_ids:
                try:
                    _, authority_hashes[f"grant:{grant_id}"] = (
                        self.authority.resolve_grant(
                            grant_id, subject_id=definition.workflow_id
                        )
                    )
                except PermissionError as error:
                    reasons.append(f"{node.node_id}:grant_invalid:{error}")
        receipt = self.authority.sign_receipt(
            {
                "schema_version": "px.workflow-admission-receipt/1.1",
                "workflow_id": definition.workflow_id,
                "version": definition.version,
                "revision_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "definition_state": "valid",
                "binding_state": "complete" if not reasons else "incomplete",
                "runnable_state": "runnable" if not reasons else "not_runnable",
                "run_state": "never_run",
                "decision": "admitted" if not reasons else "rejected",
                "status": "admitted" if not reasons else "rejected",
                "reasons": reasons,
                "authority_record_hashes": authority_hashes,
                "topological_order": list(_topology(definition)),
                "validated_utc": _now(),
                "nonce": uuid4().hex,
            }
        )
        write_json_atomic(path.with_name("admission-receipt.json"), receipt)
        return receipt

    def _admitted_plan(
        self, definition: WorkflowDefinition
    ) -> tuple[dict[str, object], dict[str, str]]:
        path = write_versioned_record(
            self.project_root,
            "workflows",
            definition.workflow_id,
            definition.version,
            definition,
        )
        admission_path = path.with_name("admission-receipt.json")
        raw = (
            json.loads(admission_path.read_text(encoding="utf-8"))
            if admission_path.is_file()
            else {}
        )
        admission = self.authority.verify_receipt(raw) if raw else {}
        if (
            admission.get("runnable_state") != "runnable"
            or admission.get("revision_sha256")
            != hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise PermissionError("current runnable admission is required")
        live_hashes: dict[str, str] = {}
        for node in definition.nodes:
            _, live_hashes[f"binding:{node.executor_binding_id}"] = (
                self.authority.resolve_binding(
                    node.executor_binding_id,
                    subject_kind="workflow",
                    subject_id=definition.workflow_id,
                )
            )
            _, live_hashes[f"executor:{node.executor_binding_id}"] = (
                self.authority.resolve_executor(node.executor_binding_id)
            )
            for grant_id in node.effect_grant_ids:
                _, live_hashes[f"grant:{grant_id}"] = self.authority.resolve_grant(
                    grant_id, subject_id=definition.workflow_id
                )
        if live_hashes != admission.get("authority_record_hashes"):
            raise PermissionError("workflow authority changed after admission")
        return admission, live_hashes

    def dry_run(self, definition: WorkflowDefinition) -> dict[str, object]:
        admission, hashes = self._admitted_plan(definition)
        return {
            "schema_version": "px.workflow-dry-run/1.1",
            "workflow_id": definition.workflow_id,
            "version": definition.version,
            "revision_sha256": admission["revision_sha256"],
            "topological_order": admission["topological_order"],
            "authority_record_hashes": hashes,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "binding_id": node.executor_binding_id,
                    "kind": node.kind,
                    "config": dict(node.config),
                    "effects": list(node.effect_grant_ids),
                    "approval_required": node.approval_required,
                    "failure_policy": node.failure_policy,
                    "retry_limit": node.retry_limit,
                    "timeout_seconds": node.timeout_seconds,
                }
                for node in definition.nodes
            ],
            "effects_executed": False,
            "status": "ready",
        }

    def issue_approval(
        self,
        definition: WorkflowDefinition,
        node_id: str,
        *,
        approved_by: str,
        ttl_seconds: int = 300,
    ) -> str:
        plan = self.dry_run(definition)
        if approved_by != "human:vscode-local-user":
            raise PermissionError(
                "workflow node approval must originate from the authenticated host"
            )
        node = next(
            (item for item in definition.nodes if item.node_id == node_id), None
        )
        if node is None or not node.approval_required:
            raise ValueError("workflow approval target is not an approval-gated node")
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=max(1, min(ttl_seconds, 3600))
        )
        receipt = self.authority.issue_approval(
            subject_id=definition.workflow_id,
            revision_sha256=str(plan["revision_sha256"]),
            node_id=node_id,
            effects=node.effect_grant_ids,
            approved_by=approved_by,
            expires_utc=expires.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
        )
        return str(receipt["record"]["approval_id"])

    def _node_authority(
        self, definition: WorkflowDefinition, node
    ) -> tuple[dict[str, str], tuple[tuple[str, str, str], ...]]:
        binding, binding_sha256 = self.authority.resolve_binding(
            node.executor_binding_id,
            subject_kind="workflow",
            subject_id=definition.workflow_id,
        )
        if set(map(str, binding.get("effect_grant_ids", ()))) != set(
            node.effect_grant_ids
        ):
            raise PermissionError(
                f"workflow node grant binding changed: {node.node_id}"
            )
        _, executor_sha256 = self.authority.resolve_executor(
            node.executor_binding_id
        )
        hashes = {
            f"binding:{node.executor_binding_id}": binding_sha256,
            f"executor:{node.executor_binding_id}": executor_sha256,
        }
        claims: set[tuple[str, str, str]] = set()
        for grant_id in node.effect_grant_ids:
            grant, grant_sha256 = self.authority.resolve_grant(
                grant_id, subject_id=definition.workflow_id
            )
            hashes[f"grant:{grant_id}"] = grant_sha256
            effects = tuple(map(str, grant.get("effects", ())))
            scopes = tuple(map(_normalized_scope, grant.get("scope_roots", ())))
            for effect in effects:
                mode = (
                    "read"
                    if effect.strip().casefold() in _READ_ONLY_WORKFLOW_EFFECTS
                    else "exclusive"
                )
                for scope in scopes or ("*",):
                    claims.add((scope, mode, effect.strip().casefold()))
        if not claims:
            # Missing/unknown scope must serialize rather than create a false-safe
            # parallel lane.
            claims.add(("*", "exclusive", "undeclared"))
        return hashes, tuple(sorted(claims))

    @staticmethod
    def _ready_node_ids(
        definition: WorkflowDefinition, completed_nodes: set[str]
    ) -> list[str]:
        dependencies = {node.node_id: set() for node in definition.nodes}
        for edge in definition.edges:
            dependencies[edge.target_node].add(edge.source_node)
        return sorted(
            node_id
            for node_id, required in dependencies.items()
            if node_id not in completed_nodes and required <= completed_nodes
        )

    def _select_ready_batch(
        self,
        ready: Sequence[str],
        nodes: Mapping[str, object],
        authority_claims: Mapping[str, Sequence[tuple[str, str, str]]],
    ) -> list[str]:
        selected: list[str] = []
        for node_id in ready:
            node = nodes[node_id]
            if node.approval_required or node.kind == "approval":
                if not selected:
                    return [node_id]
                continue
            if any(
                _claims_conflict(authority_claims[node_id], authority_claims[prior])
                for prior in selected
            ):
                continue
            selected.append(node_id)
            if len(selected) >= self.MAX_PARALLEL_NODES:
                break
        return selected or [str(ready[0])]

    @staticmethod
    def _checkpoint_value(
        completed_nodes: set[str],
        results: Mapping[str, Mapping[str, object]],
        node_receipts: Sequence[Mapping[str, object]],
        ready_nodes: Sequence[str],
    ) -> dict[str, object]:
        ordered_results = {key: dict(results[key]) for key in sorted(results)}
        ordered_receipts = sorted(
            (dict(row) for row in node_receipts),
            key=lambda row: str(row.get("node_id", "")),
        )
        ready = list(map(str, ready_nodes))
        return {
            "completed_nodes": sorted(completed_nodes),
            "results": ordered_results,
            "node_receipts": ordered_receipts,
            "ready_nodes": ready,
            "next_node": ready[0] if ready else None,
        }

    @staticmethod
    def _node_inputs(
        definition: WorkflowDefinition,
        node,
        inputs: Mapping[str, object],
        results: Mapping[str, Mapping[str, object]],
    ) -> dict[str, object]:
        node_inputs: dict[str, object] = {}
        disabled_required_ports: list[str] = []
        for port in node.inputs:
            key = f"{node.node_id}.{port.name}"
            if key in inputs:
                node_inputs[port.name] = inputs[key]
            incoming = [
                edge
                for edge in definition.edges
                if edge.target_node == node.node_id
                and edge.target_port == port.name
                and edge.source_node in results
            ]
            enabled = [
                edge
                for edge in incoming
                if _edge_enabled(
                    edge.condition,
                    results[edge.source_node],
                    edge.source_port,
                )
            ]
            for edge in enabled:
                source = results[edge.source_node]
                if edge.source_port not in source:
                    raise ValueError(
                        f"workflow source output missing: {edge.source_node}.{edge.source_port}"
                    )
                node_inputs[port.name] = source[edge.source_port]
            if port.required and port.name not in node_inputs:
                if incoming and not enabled:
                    disabled_required_ports.append(port.name)
                else:
                    raise ValueError(f"workflow input missing: {key}")
            if port.name in node_inputs and not _matches(
                node_inputs[port.name], port.data_type
            ):
                raise TypeError(f"workflow input type mismatch: {key}")
        if disabled_required_ports:
            raise _WorkflowBranchSkipped(node.node_id, disabled_required_ports)
        return node_inputs

    def _run_node(
        self,
        definition: WorkflowDefinition,
        node,
        node_inputs: Mapping[str, object],
        run_id: str,
        attempt: int,
        control_signal: DurableControlSignal,
        approval_execution: Mapping[str, object] | None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        executor, _ = self.authority.resolve_executor(node.executor_binding_id)
        authority_hashes, _ = self._node_authority(definition, node)
        request = self.authority.sign_receipt(
            {
                "schema_version": "px.workflow-node-task/1.0",
                "workflow_id": definition.workflow_id,
                "node_id": node.node_id,
                "run_id": run_id,
                "attempt": attempt,
                "adapter_id": executor["adapter_id"],
                "executor_binding_id": node.executor_binding_id,
                "authority_record_hashes": authority_hashes,
                "node_kind": node.kind,
                "node_config": dict(node.config),
                "approval_required": node.approval_required,
                "approval_execution": dict(approval_execution or {}),
                "inputs": dict(node_inputs),
                "effect_grant_ids": list(node.effect_grant_ids),
                "created_utc": _now(),
                "nonce": uuid4().hex,
            }
        )
        node_component = hashlib.sha256(node.node_id.encode("utf-8")).hexdigest()[:16]
        task_root = self.state_root / "node-tasks"
        task_root.mkdir(parents=True, exist_ok=True)
        run_component = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
        request_dir = task_root / f"{run_component}-{node_component}-{attempt}"
        request_path = request_dir / "request.json"
        request_resource = self.manager.register_path(
            request_dir,
            allowed_cleanup_root=task_root,
            project_id=definition.workflow_id,
            run_id=run_id,
            lane_id=node.node_id,
            creator=definition.owner,
            expected_cleanup_event="node_attempt_end",
        )
        timeout = float(node.timeout_seconds)
        budget = {
            "startup_timeout_seconds": min(2.0, timeout),
            "idle_timeout_seconds": timeout,
            "total_timeout_seconds": timeout,
            "graceful_shutdown_seconds": min(1.0, timeout),
            "force_shutdown_seconds": min(2.0, max(timeout, 0.1)),
            "stdout_limit_bytes": 65536,
            "stderr_limit_bytes": 65536,
        }
        task_cleanup = None
        task_error: Exception | None = None
        try:
            write_json_atomic(request_path, request)
            result = self.supervisor.run(
                [
                    sys.executable,
                    "-m",
                    "runtime.workflow_worker",
                    "--project-root",
                    str(self.project_root),
                    "--task",
                    str(request_path),
                ],
                cwd=self.project_root,
                action={
                    "action_id": f"workflow-{run_id}-{node.node_id}-{attempt}",
                    "effects": ["process"],
                    "allowed_effects": ["process"],
                    "target_paths": [str(request_path)],
                    "owned_paths": [str(self.project_root)],
                    "budget": budget,
                    "limits": budget,
                    "approval": True,
                    "policy_override_requested": False,
                },
                project_id=definition.workflow_id,
                run_id=run_id,
                lane_id=node.node_id,
                creator=definition.owner,
                environment={
                    "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                    "PYTHONUTF8": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    **studio_authority_locator_environment(),
                    **(
                        {"SYSTEMROOT": os.environ["SYSTEMROOT"]}
                        if "SYSTEMROOT" in os.environ
                        else {}
                    ),
                },
                cancel_event=control_signal,
            )
        except Exception as error:
            task_error = error
        finally:
            task_cleanup = self.manager.reclaim_ephemeral_path(
                request_resource.resource_id,
                reason="workflow_node_task_consumed",
            )
        if task_cleanup.errors:
            raise RuntimeError(
                json.dumps(
                    {
                        "status": "failed",
                        "failure_type": "TaskCleanupError",
                        "failure_message": (
                            "workflow node task cleanup did not close: "
                            + "; ".join(task_cleanup.errors)
                        )[:500],
                        "task_content_retained": True,
                        "task_cleanup_receipt": task_cleanup.cleanup_id,
                    },
                    sort_keys=True,
                )
            ) from task_error
        if task_error is not None:
            raise RuntimeError(
                json.dumps(
                    {
                        "status": "failed",
                        "failure_type": type(task_error).__name__,
                        "failure_message": str(task_error)[:500],
                        "task_content_retained": False,
                        "task_cleanup_receipt": task_cleanup.cleanup_id,
                    },
                    sort_keys=True,
                )
            ) from task_error
        response: dict[str, object] = {}
        if result.stdout.text.strip():
            try:
                response = json.loads(result.stdout.text.strip().splitlines()[-1])
            except json.JSONDecodeError:
                response = {"status": "invalid_response"}
        correlation_id = hashlib.sha256(
            f"{run_id}\0{node.node_id}\0{attempt}".encode("utf-8")
        ).hexdigest()[:24]
        failure_message = " ".join(
            result.stderr.text.replace(str(self.project_root), "<project-root>").split()
        )[-500:]
        observed_failure_type = result.failure_type
        if not observed_failure_type and failure_message:
            final_line = result.stderr.text.strip().splitlines()[-1]
            candidate = final_line.split(":", 1)[0].strip()
            if candidate.endswith(("Error", "Exception")):
                observed_failure_type = candidate
        attempt_receipt = {
            "attempt": attempt,
            "status": result.status,
            "exit_code": result.exit_code,
            "failure_type": observed_failure_type,
            "failure_message": failure_message or None,
            "correlation_id": correlation_id,
            "tree_closed": result.tree_closed,
            "process_receipt": result.receipt_path,
            "task_content_retained": False,
            "task_cleanup_receipt": task_cleanup.cleanup_id,
            "response_sha256": digest(response) if response else None,
            "adapter_id": executor["adapter_id"],
            "adapter_admitted": response.get("adapter_admitted") is True,
            "node_kind": node.kind,
            "node_config_sha256": digest(dict(node.config)),
            "validation": response.get("validation"),
            "approval_execution": response.get("approval_execution"),
        }
        if control_signal.requested_state in {
            "pause_requested",
            "cancel_requested",
        }:
            raise _WorkflowLifecycleSignal(control_signal.requested_state)
        if (
            result.status != "exited"
            or result.exit_code != 0
            or not result.tree_closed
            or response.get("status") != "completed"
        ):
            raise RuntimeError(json.dumps(attempt_receipt, sort_keys=True))
        outputs = response.get("outputs")
        if not isinstance(outputs, dict):
            raise RuntimeError("workflow worker returned an invalid output contract")
        return outputs, attempt_receipt

    def _execute_node(
        self,
        definition: WorkflowDefinition,
        node,
        node_inputs: Mapping[str, object],
        run_id: str,
        approval_execution: Mapping[str, object] | None,
    ) -> tuple[dict[str, object] | None, dict[str, object]]:
        attempts: list[dict[str, object]] = []
        output: dict[str, object] | None = None
        for attempt in range(node.retry_limit + 1):
            try:
                output, attempt_receipt = self._run_node(
                    definition,
                    node,
                    node_inputs,
                    run_id,
                    attempt + 1,
                    DurableControlSignal(self.run_control, run_id),
                    approval_execution,
                )
                attempts.append(attempt_receipt)
                break
            except _WorkflowLifecycleSignal:
                raise
            except Exception as error:
                try:
                    failure = json.loads(str(error))
                except json.JSONDecodeError:
                    failure = {
                        "status": "failed",
                        "failure_type": type(error).__name__,
                        "failure_message": " ".join(str(error).split())[:500],
                        "correlation_id": hashlib.sha256(
                            f"{run_id}\0{node.node_id}\0{attempt + 1}".encode(
                                "utf-8"
                            )
                        ).hexdigest()[:24],
                    }
                attempts.append({"attempt": attempt + 1, **failure})
        if output is None:
            return None, {
                "node_id": node.node_id,
                "kind": node.kind,
                "state": "failed",
                "attempts": attempts,
                "approval_execution": dict(approval_execution or {}),
            }
        declared_outputs = {port.name: port for port in node.outputs}
        extras = set(output) - set(declared_outputs)
        if extras:
            raise ValueError(
                f"workflow returned undeclared outputs: {sorted(extras)}"
            )
        for port in node.outputs:
            if port.required and port.name not in output:
                raise ValueError(
                    f"workflow output missing: {node.node_id}.{port.name}"
                )
            if port.name in output and not _matches(
                output[port.name], port.data_type
            ):
                raise TypeError(
                    f"workflow output type mismatch: {node.node_id}.{port.name}"
                )
        return output, {
            "node_id": node.node_id,
            "kind": node.kind,
            "state": "succeeded",
            "attempts": attempts,
            "output_sha256": digest(output),
            "approval_execution": dict(approval_execution or {}),
        }

    def execute(
        self,
        definition: WorkflowDefinition,
        inputs: Mapping[str, object],
        approvals: Mapping[str, str] | None = None,
        *,
        approval: bool,
        run_id: str | None = None,
        defer_terminal_publication: bool = False,
    ) -> dict[str, object]:
        if not approval:
            raise PermissionError("workflow launch requires explicit host approval")
        plan = self.dry_run(definition)
        nodes = {node.node_id: node for node in definition.nodes}
        request_sha256 = digest({"inputs": dict(inputs)})
        approvals = dict(approvals or {})
        if run_id is None:
            state = self.run_control.create(
                kind="workflow",
                subject_id=definition.workflow_id,
                version=definition.version,
                owner=definition.owner,
                revision_sha256=str(plan["revision_sha256"]),
                request_sha256=request_sha256,
                checkpoint=self._checkpoint_value(
                    set(),
                    {},
                    (),
                    self._ready_node_ids(definition, set()),
                ),
            )
            run_id = str(state["run_id"])
        else:
            state = self.run_control.read(run_id)
            if (
                state["kind"] != "workflow"
                or state["subject_id"] != definition.workflow_id
                or state["version"] != definition.version
                or state["revision_sha256"] != plan["revision_sha256"]
                or state["request_sha256"] != request_sha256
            ):
                raise PermissionError(
                    "workflow resume identity does not match durable state"
                )
        if state["state"] not in {"queued", "paused", "interrupted"}:
            raise ValueError(f"workflow cannot start from {state['state']}")
        if state["state"] == "paused":
            state = wait_for_paused_worker_closure(
                state_root=self.state_root,
                manager=self.manager,
                authority=self.authority,
                run_control=self.run_control,
                run_id=run_id,
                kind="workflow",
            )
        checkpoint = dict(state["checkpoint"])
        raw_results = checkpoint.get("results", {})
        if not isinstance(raw_results, Mapping):
            raise PermissionError("workflow checkpoint results are invalid")
        results: dict[str, Mapping[str, object]] = {
            str(key): dict(value)
            for key, value in raw_results.items()
            if isinstance(value, Mapping)
        }
        node_receipts = checkpoint.get("node_receipts", [])
        if not isinstance(node_receipts, list) or not all(
            isinstance(row, Mapping) for row in node_receipts
        ):
            raise PermissionError("workflow checkpoint receipts are invalid")
        receipt_nodes = [dict(row) for row in node_receipts]
        completed_nodes = set(map(str, checkpoint.get("completed_nodes", [])))
        if (
            not completed_nodes <= set(nodes)
            or not set(results) <= completed_nodes
            or any(str(row.get("node_id", "")) not in completed_nodes for row in receipt_nodes)
            or len({str(row.get("node_id", "")) for row in receipt_nodes})
            != len(receipt_nodes)
        ):
            raise PermissionError("workflow checkpoint identity is invalid")
        self.run_control.transition(
            run_id,
            "running",
            actor=definition.owner,
            approved=True,
            checkpoint=checkpoint,
            operation="workflow.start"
            if state["state"] == "queued"
            else "workflow.resume",
        )
        run_path = self.state_root / "runs" / f"{run_id}.json"
        receipt: dict[str, object] = {
            "schema_version": "px.workflow-run-receipt/1.3",
            "run_id": run_id,
            "workflow_id": definition.workflow_id,
            "version": definition.version,
            "revision_sha256": plan["revision_sha256"],
            "run_state": "running",
            "status": "running",
            "started_utc": _now(),
            "completed_utc": None,
            "node_receipts": receipt_nodes,
            "declared_effect_grants": sorted(
                {grant for node in definition.nodes for grant in node.effect_grant_ids}
            ),
            "attempted_effects": [],
            "completed_effects": [],
            "denied_effects": [],
            "effects_executed": False,
            "outputs_retained": True,
            "output_retention": "durable checkpoint results retained for downstream dataflow and resumable execution",
            "node_task_content_retained": False,
            "node_task_cleanup_policy": "registered ephemeral task envelopes are reclaimed after every node attempt",
            "execution_policy": {
                "scheduler": "dependency-ready-batches",
                "max_parallel_nodes": self.MAX_PARALLEL_NODES,
                "shared_effects_serialized": True,
                "approval_nodes_serialized": True,
                "checkpoint_order": "node-id",
            },
        }
        write_json_atomic(run_path, self.authority.sign_receipt(receipt))
        try:
            authority_claims = {
                node_id: self._node_authority(definition, node)[1]
                for node_id, node in nodes.items()
            }
            while len(completed_nodes) < len(nodes):
                control = self.run_control.read(run_id)
                if control["state"] in {"pause_requested", "cancel_requested"}:
                    raise _WorkflowLifecycleSignal(str(control["state"]))
                ready = self._ready_node_ids(definition, completed_nodes)
                if not ready:
                    raise RuntimeError("workflow has no resumable ready node")
                batch = self._select_ready_batch(ready, nodes, authority_claims)
                prepared: dict[
                    str, tuple[dict[str, object], dict[str, object] | None]
                ] = {}
                outcomes: dict[
                    str, tuple[dict[str, object] | None, dict[str, object]]
                ] = {}
                for node_id in batch:
                    node = nodes[node_id]
                    try:
                        node_inputs = self._node_inputs(
                            definition, node, inputs, results
                        )
                    except _WorkflowBranchSkipped as skipped:
                        outcomes[node_id] = (
                            {},
                            {
                                "node_id": node.node_id,
                                "kind": node.kind,
                                "state": "skipped",
                                "skip_reason": "incoming_condition_disabled",
                                "disabled_required_ports": list(skipped.ports),
                                "attempts": [],
                                "approval_execution": {},
                            },
                        )
                        continue
                    approval_execution: dict[str, object] | None = None
                    if node.approval_required or node.kind == "approval":
                        approval_id = approvals.get(node.node_id)
                        if not approval_id:
                            raise PermissionError(
                                f"workflow node approval missing: {node.node_id}"
                            )
                        approval_record, approval_sha256 = (
                            self.authority.consume_approval(
                                approval_id,
                                subject_id=definition.workflow_id,
                                revision_sha256=str(plan["revision_sha256"]),
                                node_id=node.node_id,
                                effects=node.effect_grant_ids,
                                run_id=run_id,
                            )
                        )
                        approval_execution = {
                            "required": True,
                            "host_consumed": True,
                            "approved_by": approval_record.get("approved_by"),
                            "approval_sha256": approval_sha256,
                            "approval_id_sha256": hashlib.sha256(
                                approval_id.encode("utf-8")
                            ).hexdigest(),
                        }
                    prepared[node_id] = (node_inputs, approval_execution)
                lifecycle_signals: list[_WorkflowLifecycleSignal] = []
                worker_errors: list[tuple[str, Exception]] = []
                execution_ids = sorted(prepared)
                if len(execution_ids) == 1:
                    node_id = execution_ids[0]
                    try:
                        outcomes[node_id] = self._execute_node(
                            definition,
                            nodes[node_id],
                            prepared[node_id][0],
                            run_id,
                            prepared[node_id][1],
                        )
                    except _WorkflowLifecycleSignal as signal:
                        lifecycle_signals.append(signal)
                    except Exception as error:
                        worker_errors.append((node_id, error))
                elif execution_ids:
                    with ThreadPoolExecutor(
                        max_workers=min(self.MAX_PARALLEL_NODES, len(execution_ids)),
                        thread_name_prefix=f"px-workflow-{run_id[:8]}",
                    ) as pool:
                        futures = {
                            node_id: pool.submit(
                                self._execute_node,
                                definition,
                                nodes[node_id],
                                prepared[node_id][0],
                                run_id,
                                prepared[node_id][1],
                            )
                            for node_id in execution_ids
                        }
                        for node_id in sorted(futures):
                            try:
                                outcomes[node_id] = futures[node_id].result()
                            except _WorkflowLifecycleSignal as signal:
                                lifecycle_signals.append(signal)
                            except Exception as error:
                                worker_errors.append((node_id, error))
                failed_closed: list[str] = []
                for node_id in sorted(outcomes):
                    output, node_receipt = outcomes[node_id]
                    node = nodes[node_id]
                    if output is None:
                        if node.failure_policy == "continue":
                            results[node_id] = {}
                            node_receipt["state"] = "failed-continued"
                        else:
                            failed_closed.append(node_id)
                    else:
                        results[node_id] = output
                    receipt_nodes[:] = [
                        row
                        for row in receipt_nodes
                        if str(row.get("node_id", "")) != node_id
                    ]
                    receipt_nodes.append(node_receipt)
                    completed_nodes.add(node_id)
                next_ready = self._ready_node_ids(definition, completed_nodes)
                self.run_control.heartbeat(
                    run_id,
                    actor=definition.owner,
                    checkpoint=self._checkpoint_value(
                        completed_nodes, results, receipt_nodes, next_ready
                    ),
                )
                # A lifecycle request can arrive after the last node process
                # returns but before its batch checkpoint is published.  Re-read
                # the authoritative head so pause/cancel cannot be skipped by
                # the success transition at the bottom of the loop.
                control = self.run_control.read(run_id)
                if control["state"] in {"pause_requested", "cancel_requested"}:
                    raise _WorkflowLifecycleSignal(str(control["state"]))
                if failed_closed:
                    raise RuntimeError(
                        "workflow node failed: " + ", ".join(failed_closed)
                    )
                if lifecycle_signals:
                    requested = (
                        "cancel_requested"
                        if any(
                            signal.requested_state == "cancel_requested"
                            for signal in lifecycle_signals
                        )
                        else "pause_requested"
                    )
                    raise _WorkflowLifecycleSignal(requested)
                if worker_errors:
                    node_id, error = sorted(worker_errors, key=lambda row: row[0])[0]
                    raise RuntimeError(
                        f"workflow worker failed before receipt: {node_id}: {error}"
                    ) from error
            control = self.run_control.read(run_id)
            if control["state"] in {"pause_requested", "cancel_requested"}:
                raise _WorkflowLifecycleSignal(str(control["state"]))
            target = "succeeded"
            published_state = "finalizing" if defer_terminal_publication else target
            receipt.update(
                {
                    "run_state": published_state,
                    "status": published_state,
                    "terminal_target": target if defer_terminal_publication else None,
                    "completed_utc": None if defer_terminal_publication else _now(),
                    "node_count": len(results),
                    "output_sha256": digest(results),
                    "node_task_cleanup_receipts": sorted(
                        {
                            str(attempt.get("task_cleanup_receipt"))
                            for row in receipt_nodes
                            for attempt in row.get("attempts", [])
                            if isinstance(attempt, Mapping)
                            and attempt.get("task_cleanup_receipt")
                        }
                    ),
                }
            )
            final = self.run_control.transition(
                run_id,
                published_state,
                actor=definition.owner,
                approved=True,
                checkpoint={
                    **self._checkpoint_value(
                        completed_nodes, results, receipt_nodes, ()
                    ),
                    **(
                        {"terminal_target": target}
                        if defer_terminal_publication
                        else {}
                    ),
                },
                operation=f"workflow.{published_state}",
            )
            receipt["control_sequence"] = final["sequence"]
        except _WorkflowLifecycleSignal as signal:
            target = (
                "paused" if signal.requested_state == "pause_requested" else "cancelled"
            )
            current = self.run_control.read(run_id)
            published_state = (
                "finalizing" if defer_terminal_publication and target == "cancelled" else target
            )
            resumable_ready = self._ready_node_ids(definition, completed_nodes)
            final = self.run_control.transition(
                run_id,
                published_state,
                actor=definition.owner,
                approved=True,
                checkpoint={
                    **self._checkpoint_value(
                        completed_nodes,
                        results,
                        receipt_nodes,
                        resumable_ready,
                    ),
                    "recovery": "resume from the last completed node with fresh node approvals",
                    **({"terminal_target": target} if published_state == "finalizing" else {}),
                },
                operation=f"workflow.{published_state}",
            )
            receipt.update(
                {
                    "run_state": published_state,
                    "status": published_state,
                    "terminal_target": target if published_state == "finalizing" else None,
                    "completed_utc": None if published_state == "finalizing" else (_now() if target == "cancelled" else None),
                    "node_count": len(results),
                    "control_sequence": final["sequence"],
                    "resumable": target == "paused",
                }
            )
        except Exception as error:
            failure_correlation_id = hashlib.sha256(
                f"{run_id}\0workflow.failure".encode("utf-8")
            ).hexdigest()[:24]
            receipt.update(
                {
                    "run_state": "failed",
                    "status": "failed",
                    "completed_utc": _now(),
                    "failure_type": type(error).__name__,
                    "failure_message": str(error)[:500],
                    "failure_correlation_id": failure_correlation_id,
                    "node_count": len(results),
                }
            )
            current = self.run_control.read(run_id)
            if current["state"] in {"running", "pause_requested", "cancel_requested"}:
                target = (
                    "cancelled"
                    if current["state"] == "cancel_requested"
                    else "paused"
                    if current["state"] == "pause_requested"
                    else "failed"
                )
                published_state = (
                    "finalizing"
                    if defer_terminal_publication and target in TERMINAL_STATES
                    else target
                )
                resumable_ready = self._ready_node_ids(
                    definition, completed_nodes
                )
                self.run_control.transition(
                    run_id,
                    published_state,
                    actor=definition.owner,
                    approved=True,
                    checkpoint={
                        **self._checkpoint_value(
                            completed_nodes,
                            results,
                            receipt_nodes,
                            resumable_ready,
                        ),
                        **({"terminal_target": target} if published_state == "finalizing" else {}),
                    },
                    failure=None
                    if target in {"paused", "cancelled"}
                    else {
                        "code": type(error).__name__,
                        "message": str(error)[:500],
                        "correlation_id": failure_correlation_id,
                    },
                    operation=f"workflow.{published_state}",
                )
                receipt["run_state"] = published_state
                receipt["status"] = published_state
                receipt["terminal_target"] = target if published_state == "finalizing" else None
                if published_state == "finalizing":
                    receipt["completed_utc"] = None
            write_json_atomic(run_path, self.authority.sign_receipt(receipt))
            raise
        write_json_atomic(run_path, self.authority.sign_receipt(receipt))
        return self.authority.sign_receipt(receipt)

    def start(
        self,
        definition: WorkflowDefinition,
        inputs: Mapping[str, object],
        approvals: Mapping[str, str] | None = None,
        *,
        approval: bool,
    ) -> dict[str, object]:
        """Start asynchronously; callers control it by the returned durable ID."""
        if not approval:
            raise PermissionError("workflow launch requires explicit host approval")
        # Create a queued run without starting a second effect.  execute() will
        # adopt this exact identity in the background worker.
        plan = self.dry_run(definition)
        state = self.run_control.create(
            kind="workflow",
            subject_id=definition.workflow_id,
            version=definition.version,
            owner=definition.owner,
            revision_sha256=str(plan["revision_sha256"]),
            request_sha256=digest({"inputs": dict(inputs)}),
            checkpoint=self._checkpoint_value(
                set(),
                {},
                (),
                self._ready_node_ids(definition, set()),
            ),
        )
        run_id = str(state["run_id"])

        return launch_studio_worker(
            project_root=self.project_root,
            state_root=self.state_root,
            manager=self.manager,
            authority=self.authority,
            run_control=self.run_control,
            kind="workflow",
            run_id=run_id,
            payload={
                "definition": asdict(definition),
                "inputs": dict(inputs),
                "approvals": dict(approvals or {}),
            },
        )

    def request_lifecycle(
        self,
        run_id: str,
        action: str,
        *,
        approved: bool,
        approved_by: str,
    ) -> dict[str, object]:
        target = {"pause": "pause_requested", "cancel": "cancel_requested", "stop": "cancel_requested"}.get(action)
        if target is None:
            raise ValueError("workflow lifecycle action must be pause, cancel, or stop")
        state = self.run_control.read(run_id)
        if state["kind"] != "workflow":
            raise PermissionError("durable run is not a workflow")
        return self.run_control.transition(
            run_id,
            target,
            actor=approved_by,
            approved=approved,
            checkpoint=state["checkpoint"],
            operation=f"workflow.request.{action}",
        )

    def resume(
        self,
        definition: WorkflowDefinition,
        inputs: Mapping[str, object],
        approvals: Mapping[str, str] | None,
        *,
        run_id: str,
        approval: bool,
    ) -> dict[str, object]:
        return self.execute(
            definition,
            inputs,
            approvals,
            approval=approval,
            run_id=run_id,
        )

    def status(self, run_id: str) -> dict[str, object]:
        """Read the durable head without reconciling or publishing state."""
        return self.run_control.read(run_id)

    def list_runs(self, *, limit: int = 100) -> dict[str, object]:
        return self.run_control.list_runs(kind="workflow", limit=limit)

    def reconcile(
        self, *, approved: bool, approved_by: str, stale_after_seconds: float = 60.0
    ) -> dict[str, object]:
        return self.run_control.reconcile(
            actor=approved_by,
            approved=approved,
            stale_after_seconds=stale_after_seconds,
        )
