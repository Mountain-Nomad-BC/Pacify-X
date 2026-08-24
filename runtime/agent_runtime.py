"""Versioned agent creation, admission, and owned harness invocation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence
from uuid import uuid4

from .file_lock import FileLock
from .agent_builder import (
    AgentBuilderGraph,
    agent_builder_artifacts,
    agent_builder_graph_from_spec,
    verify_agent_builder_artifacts,
)
from .process_supervisor import ProcessSupervisor
from .resource_lifecycle import ResourceManager, RunState
from .studio_filesystem import (
    assert_exact_tree,
    bounded_directory_entries,
    is_link_or_reparse,
    publish_directory_no_replace,
    read_bounded_regular_file,
)
from .studio_authority import (
    StudioAuthorityStore,
    studio_authority_locator_environment,
)
from .studio_run_control import DurableControlSignal, DurableRunControl, TERMINAL_STATES
from .studio_worker_launch import launch_studio_worker
from .studio_models import (
    AgentSpec,
    CapabilityBinding,
    EffectGrant,
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


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


_MAX_CREATE_CLEANUP_WARNINGS = 8
_MAX_CREATE_CLEANUP_WARNING_CHARS = 240
_MAX_AGENT_REVISION_FILE_BYTES = 4 * 1024 * 1024
_MAX_AGENT_RUN_RECEIPTS = 256
_AGENT_RUN_RECEIPT_NAME = re.compile(
    r"run-[0-9a-f]{32}(?:-prepared|-resume-[0-9]+)?\.json"
)


def _bounded_cleanup_warnings(errors: Sequence[object]) -> list[str]:
    """Return a small, serializable warning set for already-committed creates."""

    warnings: list[str] = []
    for error in errors[:_MAX_CREATE_CLEANUP_WARNINGS]:
        warning = str(error).strip()
        if warning:
            warnings.append(warning[:_MAX_CREATE_CLEANUP_WARNING_CHARS])
    return warnings


def _read_revision_bytes(path: Path) -> bytes:
    return read_bounded_regular_file(
        path,
        _MAX_AGENT_REVISION_FILE_BYTES,
        lambda: ValueError("agent revision file is invalid or oversized"),
    )


def _read_revision_json(path: Path) -> object:
    return json.loads(_read_revision_bytes(path).decode("utf-8"))


def _agent_revision_runtime_entries(
    revision: Path,
) -> tuple[set[str], set[str]]:
    """Return the one bounded mutable subtree owned by Agent execution."""

    runs = revision / "runs"
    if not os.path.lexists(runs):
        return set(), set()
    def conflict() -> StudioVersionConflict:
        return StudioVersionConflict("immutable-agent-revision-differs")

    try:
        if is_link_or_reparse(runs) or not runs.is_dir():
            raise conflict()
        entries = bounded_directory_entries(runs, _MAX_AGENT_RUN_RECEIPTS, conflict)
    except OSError as error:
        raise conflict() from error
    files: set[str] = set()
    for entry in entries:
        try:
            if (
                is_link_or_reparse(entry)
                or not entry.is_file()
                or _AGENT_RUN_RECEIPT_NAME.fullmatch(entry.name) is None
            ):
                raise conflict()
            read_bounded_regular_file(entry, _MAX_AGENT_REVISION_FILE_BYTES, conflict)
        except OSError as error:
            raise conflict() from error
        files.add(f"runs/{entry.name}")
    return files, {"runs"}


def _validate_agent_creation_receipt(
    value: object, expected_values: Mapping[str, object]
) -> dict[str, object]:
    """Validate an immutable receipt without allowing undeclared fields."""

    if (
        not isinstance(value, Mapping)
        or set(value) != {*expected_values, "created_utc"}
        or not valid_canonical_utc(value.get("created_utc"))
        or any(value.get(key) != expected for key, expected in expected_values.items())
    ):
        raise ValueError("immutable agent creation receipt does not match revision")
    return dict(value)


def _validate_legacy_agent_creation_receipt(
    value: object, spec: AgentSpec
) -> dict[str, object]:
    """Preserve the exact pre-builder receipt schema for legacy revisions."""

    expected = {
        "schema_version": "px.agent-creation-receipt/1.0",
        "agent_id": spec.agent_id,
        "version": spec.version,
        "created": True,
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise ValueError("immutable legacy agent creation receipt does not match revision")
    return dict(value)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _schema_value_matches(value: object, expected: str) -> bool:
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, Mapping),
        "array": isinstance(value, (list, tuple)),
        "null": value is None,
    }.get(expected, True)


def _validate_object_contract(
    value: Mapping[str, object], schema: Mapping[str, object], label: str
) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"agent {label} is not an object")
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise ValueError(f"agent {label} schema is malformed")
    missing = [str(key) for key in required if str(key) not in value]
    if missing:
        raise ValueError(f"agent {label} is missing required keys: {missing}")
    if schema.get("additionalProperties") is False:
        extras = sorted(set(value) - set(map(str, properties)))
        if extras:
            raise ValueError(f"agent {label} has undeclared keys: {extras}")
    for key, contract in properties.items():
        token = str(key)
        if token not in value or not isinstance(contract, Mapping):
            continue
        expected = str(contract.get("type") or "")
        if expected and not _schema_value_matches(value[token], expected):
            raise TypeError(f"agent {label} type mismatch: {token}")


class AgentRuntimeController:
    """Owns artifacts and bounded harness processes; it never grants host authority."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve(strict=True)
        if not self.project_root.is_dir() or self.project_root == Path(
            self.project_root.anchor
        ):
            raise ValueError("agent project root must be bounded")
        self.state_root = self.project_root / ".engineering-bootstrap/studios/agents"
        self.manager = ResourceManager(self.state_root / "resources.json")
        self.supervisor = ProcessSupervisor(self.manager)
        self.authority = StudioAuthorityStore(self.project_root)
        self.run_control = DurableRunControl(
            self.project_root, self.state_root / "sessions"
        )

    def register_authority(
        self, bindings: Sequence[CapabilityBinding], grants: Sequence[EffectGrant]
    ) -> dict[str, object]:
        """Admit supplied definitions into the authenticated project authority.

        Runtime admission never consumes these caller objects directly; it resolves
        the records written here and verifies them again at each launch.
        """
        return self.authority.register_authority_transaction(
            tuple(bindings), tuple(grants)
        )

    def register_revision_authority(
        self,
        spec: AgentSpec,
        bindings: Sequence[CapabilityBinding],
        grants: Sequence[EffectGrant],
    ) -> dict[str, object]:
        record_path = self._existing_record_path(spec)
        authority_path = record_path.with_name("authority-definition.json")
        if not authority_path.is_file():
            raise PermissionError("immutable agent revision has no authority definition")
        envelope = _read_revision_json(authority_path)
        record = envelope.get("record") if isinstance(envelope, Mapping) else None
        if (
            not isinstance(record, Mapping)
            or envelope.get("sha256") != digest(record)
            or record.get("kind") != "agent"
            or record.get("subject_id") != spec.agent_id
            or record.get("version") != spec.version
            or record.get("bindings")
            != json.loads(canonical_bytes([asdict(item) for item in bindings]))
            or record.get("grants")
            != json.loads(canonical_bytes([asdict(item) for item in grants]))
        ):
            raise PermissionError("agent authority does not match its immutable revision")
        return self.register_authority(bindings, grants)

    def _existing_record_path(self, spec: AgentSpec) -> Path:
        component = (
            f"{re.sub(r'[^a-z0-9._-]+', '-', spec.agent_id).strip('-')}-"
            f"{hashlib.sha256(spec.agent_id.encode()).hexdigest()[:8]}"
        )
        path = self.state_root / component / "revisions" / spec.version / "record.json"
        verify_safe_ancestors(self.project_root, path)
        if not path.is_file():
            raise FileNotFoundError("saved immutable agent revision is required")
        if _read_revision_json(path) != json.loads(
            canonical_bytes(studio_record(spec))
        ):
            raise PermissionError("supplied agent definition does not match its saved revision")
        self._verify_builder_revision(path, spec)
        return path

    def _verify_builder_revision(
        self, record_path: Path, spec: AgentSpec
    ) -> str:
        """Verify the graph/compiler triplet when the immutable revision has one.

        Pre-graph revisions remain readable as explicit legacy records.  A
        partially present or changed triplet fails closed and is never repaired
        in place.
        """

        graph_path = record_path.with_name("builder-graph.json")
        layout_path = record_path.with_name("editor-layout.json")
        compiler_path = record_path.with_name("builder-compiler-receipt.json")
        present = tuple(path.is_file() for path in (graph_path, layout_path, compiler_path))
        if not any(present):
            creation_path = record_path.with_name("creation-receipt.json")
            if creation_path.is_file():
                try:
                    creation = _read_revision_json(creation_path)
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    raise PermissionError("immutable agent creation receipt is invalid") from error
                if not isinstance(creation, Mapping):
                    raise PermissionError("immutable agent creation receipt is invalid")
                if (
                    creation.get("schema_version") == "px.agent-creation-receipt/1.1"
                    or creation.get("builder_graph_state") == "content-bound"
                ):
                    raise PermissionError("immutable agent builder artifacts are missing")
            return "legacy-unavailable"
        if not all(present):
            raise PermissionError("immutable agent builder artifact set is incomplete")
        try:
            verify_agent_builder_artifacts(
                _read_revision_json(graph_path),
                _read_revision_json(layout_path),
                _read_revision_json(compiler_path),
                spec,
            )
        except (OSError, TypeError, ValueError, PermissionError, json.JSONDecodeError) as error:
            raise PermissionError("immutable agent builder artifacts are invalid") from error
        return "content-bound"

    def create_candidate(
        self,
        spec: AgentSpec,
        instruction_body: str,
        *,
        authority_definition: Mapping[str, object] | None = None,
        builder_graph: AgentBuilderGraph | None = None,
        editor_layout: Mapping[str, object] | None = None,
        builder_graph_explicit: bool = False,
        version_allocation: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        lock_path = studio_revision_lock(self.project_root, "agent", spec.agent_id)
        component = f"{re.sub(r'[^a-z0-9._-]+', '-', spec.agent_id).strip('-')}-{hashlib.sha256(spec.agent_id.encode()).hexdigest()[:8]}"
        revision = self.state_root / component / "revisions" / spec.version
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
                    "agent",
                    spec.agent_id,
                    spec.version,
                    version_allocation,
                )
            return self._create_candidate_locked(
                spec,
                instruction_body,
                authority_definition=authority_definition,
                builder_graph=builder_graph,
                editor_layout=editor_layout,
                builder_graph_explicit=builder_graph_explicit,
            )

    def _create_candidate_locked(
        self,
        spec: AgentSpec,
        instruction_body: str,
        *,
        authority_definition: Mapping[str, object] | None = None,
        builder_graph: AgentBuilderGraph | None = None,
        editor_layout: Mapping[str, object] | None = None,
        builder_graph_explicit: bool = False,
    ) -> dict[str, object]:
        body_sha = hashlib.sha256(instruction_body.encode("utf-8")).hexdigest()
        if body_sha != spec.instruction_sha256:
            raise ValueError(
                "agent instruction body does not match specification identity"
            )
        component = f"{re.sub(r'[^a-z0-9._-]+', '-', spec.agent_id).strip('-')}-{hashlib.sha256(spec.agent_id.encode()).hexdigest()[:8]}"
        revision = self.state_root / component / "revisions" / spec.version
        record_path = revision / "record.json"
        instruction_path = revision / "instructions.md"
        authority_path = revision / "authority-definition.json"
        graph_path = revision / "builder-graph.json"
        layout_path = revision / "editor-layout.json"
        compiler_path = revision / "builder-compiler-receipt.json"
        expected_record = json.loads(json.dumps(studio_record(spec)))
        expected_authority = (
            json.loads(canonical_bytes(dict(authority_definition)))
            if authority_definition is not None
            else None
        )
        graph = builder_graph or agent_builder_graph_from_spec(spec)
        expected_graph, expected_layout, expected_compiler = agent_builder_artifacts(
            graph, spec, editor_layout
        )

        def expected_creation_receipt(record_sha256: str) -> dict[str, object]:
            return {
                "schema_version": "px.agent-creation-receipt/1.1",
                "operation": "agent.create_candidate",
                "agent_id": spec.agent_id,
                "version": spec.version,
                "record_sha256": record_sha256,
                "instruction_sha256": body_sha,
                "validation_state": "structurally_valid",
                "admission_state": "unadmitted",
                "runtime_state": "stopped",
                "authority_state": (
                    "defined" if expected_authority is not None else "none"
                ),
                "authority_definition_path": (
                    authority_path.relative_to(self.project_root).as_posix()
                    if expected_authority is not None
                    else None
                ),
                "builder_graph_state": "content-bound",
                "builder_graph_path": graph_path.relative_to(
                    self.project_root
                ).as_posix(),
                "builder_graph_sha256": expected_graph["sha256"],
                "editor_layout_path": layout_path.relative_to(
                    self.project_root
                ).as_posix(),
                "editor_layout_sha256": expected_layout["layout_sha256"],
                "builder_compiler_receipt_path": compiler_path.relative_to(
                    self.project_root
                ).as_posix(),
                "builder_compiler_receipt_sha256": expected_compiler[
                    "receipt_sha256"
                ],
                "builder_graph_explicit": bool(builder_graph_explicit),
                "authority_granted_by_builder": False,
                "host_authority_retained": True,
                "created": True,
            }

        if revision.exists():
            optional_names = {
                "authority-definition.json",
                "builder-graph.json",
                "editor-layout.json",
                "builder-compiler-receipt.json",
                "test-receipt.json",
                "admission-receipt.json",
            }
            present_optional = {
                name
                for name in optional_names
                if (revision / name).exists() or (revision / name).is_symlink()
            }
            runtime_files, runtime_directories = _agent_revision_runtime_entries(
                revision
            )
            assert_exact_tree(
                revision,
                {
                    "record.json",
                    "instructions.md",
                    "creation-receipt.json",
                    *present_optional,
                    *runtime_files,
                },
                runtime_directories,
                10 + len(runtime_files),
                lambda: StudioVersionConflict(
                    "immutable-agent-revision-differs"
                ),
            )
            builder_files = (graph_path, layout_path, compiler_path)
            builder_present = tuple(path.is_file() for path in builder_files)
            builder_state = (
                self._verify_builder_revision(record_path, spec)
                if record_path.is_file()
                else None
            )
            if (
                not record_path.is_file()
                or _read_revision_json(record_path)
                != expected_record
                or not instruction_path.is_file()
                or _read_revision_bytes(instruction_path).decode("utf-8")
                != instruction_body
                or (
                    expected_authority is None
                    and authority_path.exists()
                )
                or (
                    expected_authority is not None
                    and (
                        not authority_path.is_file()
                        or _read_revision_json(authority_path)
                        != expected_authority
                    )
                )
                or (any(builder_present) and not all(builder_present))
                or (
                    all(builder_present)
                    and (
                        _read_revision_json(graph_path)
                        != expected_graph
                        or _read_revision_json(layout_path)
                        != expected_layout
                        or _read_revision_json(compiler_path)
                        != expected_compiler
                    )
                )
                or (builder_graph_explicit and not any(builder_present))
            ):
                raise StudioVersionConflict("immutable-agent-revision-differs")
            existing_receipt = record_path.with_name("creation-receipt.json")
            if not existing_receipt.is_file():
                raise StudioVersionConflict("immutable-agent-receipt-missing")
            try:
                loaded_receipt = _read_revision_json(existing_receipt)
                existing = (
                    _validate_legacy_agent_creation_receipt(loaded_receipt, spec)
                    if builder_state == "legacy-unavailable"
                    else _validate_agent_creation_receipt(
                        loaded_receipt,
                        expected_creation_receipt(
                            hashlib.sha256(_read_revision_bytes(record_path)).hexdigest()
                        ),
                    )
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise StudioVersionConflict(
                    "immutable-agent-revision-differs"
                ) from error
            return {
                **existing,
                "builder_graph_state": builder_state,
                **(
                    {
                        "authority_state": "defined",
                        "authority_definition_path": authority_path.relative_to(
                            self.project_root
                        ).as_posix(),
                    }
                    if expected_authority is not None
                    else {}
                ),
                "created": False,
                "idempotent_replay": True,
            }
        prepared_root = self.state_root / "prepared"
        verify_safe_ancestors(self.project_root, prepared_root)
        prepared_root.mkdir(parents=True, exist_ok=True)
        run_id = f"agent-create-{uuid4().hex}"
        resource = self.manager.create_workspace(
            prepared_root,
            project_id=spec.project_id,
            run_id=run_id,
            lane_id=spec.agent_id,
            creator=spec.owner,
            prefix=f"{component}-{spec.version}-",
        )
        prepared = Path(str(resource.path))
        try:
            prepared_record = prepared / "record.json"
            write_json_atomic(prepared_record, expected_record)
            (prepared / "instructions.md").write_text(
                instruction_body, encoding="utf-8", newline="\n"
            )
            if expected_authority is not None:
                write_json_atomic(
                    prepared / "authority-definition.json", expected_authority
                )
            write_json_atomic(prepared / "builder-graph.json", expected_graph)
            write_json_atomic(prepared / "editor-layout.json", expected_layout)
            write_json_atomic(
                prepared / "builder-compiler-receipt.json", expected_compiler
            )
            expected_receipt = expected_creation_receipt(
                hashlib.sha256(prepared_record.read_bytes()).hexdigest()
            )
            receipt = _validate_agent_creation_receipt(
                {"created_utc": _now(), **expected_receipt}, expected_receipt
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
                    reason="agent_revision_publish_failed",
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
                resource.resource_id, reason="agent_revision_published", apply=True
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

    def test_candidate(self, spec: AgentSpec) -> dict[str, object]:
        record_path = write_versioned_record(
            self.project_root, "agents", spec.agent_id, spec.version, spec
        )
        instruction_path = record_path.with_name("instructions.md")
        builtin = {
            "identity": lambda: instruction_path.is_file()
            and hashlib.sha256(instruction_path.read_bytes()).hexdigest()
            == spec.instruction_sha256,
            "sandbox": lambda: _inside(
                record_path.resolve(strict=True), self.project_root
            ),
            "model-route": lambda: spec.model.get("provider")
            in {"deterministic", "vscode-lm", "pacify-local"},
            "input-contract": lambda: spec.input_schema.get("type") == "object",
            "output-contract": lambda: spec.output_schema.get("type") == "object",
            "authority-bindings": lambda: bool(spec.capability_binding_ids)
            and bool(spec.effect_grant_ids),
            "tool-bindings": lambda: all(
                binding_id in spec.capability_binding_ids
                for binding_id in spec.tool_binding_ids
            ),
            "handoff-topology": lambda: spec.agent_id
            not in spec.handoff_agent_ids,
        }
        test_results = []
        for test_id in spec.required_tests:
            operation = builtin.get(test_id)
            if operation is None:
                test_results.append(
                    {
                        "test_id": test_id,
                        "known": False,
                        "passed": False,
                        "reason": "unknown_governed_test",
                    }
                )
                continue
            try:
                passed = bool(operation())
                test_results.append(
                    {
                        "test_id": test_id,
                        "known": True,
                        "passed": passed,
                        "reason": None if passed else "assertion_failed",
                    }
                )
            except Exception as error:  # pragma: no cover - defensive receipt path
                test_results.append(
                    {
                        "test_id": test_id,
                        "known": True,
                        "passed": False,
                        "reason": type(error).__name__,
                    }
                )
        checks = {
            "record_sealed": True,
            "instruction_present": instruction_path.is_file(),
            "bindings_declared": bool(spec.capability_binding_ids),
            "effect_grants_declared": bool(spec.effect_grant_ids),
            "required_tests_executed": bool(test_results)
            and all(row["passed"] for row in test_results),
            "model_tool_route_compatible": not spec.tool_binding_ids
            or (
                spec.harness_id == "harness:vscode-lm"
                and spec.model.get("provider") == "vscode-lm"
            ),
            # This is the immutable structural half of the tool gate. Admission
            # resolves the signed binding/grant records, and the VS Code host
            # re-attests the live tool interface immediately before invocation.
            "host_tool_implementation_attested": not spec.tool_binding_ids
            or (
                spec.harness_id == "harness:vscode-lm"
                and spec.model.get("provider") == "vscode-lm"
                and all(
                    binding_id in spec.capability_binding_ids
                    for binding_id in spec.tool_binding_ids
                )
            ),
            "memory_runtime_resolved": not spec.memory_binding_ids,
            "handoff_runtime_resolved": not spec.handoff_agent_ids,
        }
        receipt = {
            "schema_version": "px.agent-preflight-receipt/1.2",
            "agent_id": spec.agent_id,
            "version": spec.version,
            "agent_revision_sha256": hashlib.sha256(
                record_path.read_bytes()
            ).hexdigest(),
            "checks": checks,
            "test_results": test_results,
            "passed": all(checks.values()),
            "status": "passed" if all(checks.values()) else "failed",
            "independently_derived": False,
            "evidence_class": "structural_preflight_not_behavioral_certification",
            "tested_utc": _now(),
        }
        signed = self.authority.sign_receipt(receipt)
        write_json_atomic(record_path.with_name("test-receipt.json"), signed)
        return signed

    def admit(self, spec: AgentSpec) -> dict[str, object]:
        record_path = write_versioned_record(
            self.project_root, "agents", spec.agent_id, spec.version, spec
        )
        test_path = record_path.with_name("test-receipt.json")
        test_raw = (
            json.loads(test_path.read_text(encoding="utf-8"))
            if test_path.is_file()
            else {}
        )
        try:
            test = self.authority.verify_receipt(test_raw) if test_raw else {}
        except PermissionError:
            test = {}
        reasons = []
        authority_hashes: dict[str, str] = {}
        binding_grant_closure: set[str] = set()
        if (
            not test.get("passed")
            or test.get("agent_revision_sha256")
            != hashlib.sha256(record_path.read_bytes()).hexdigest()
        ):
            reasons.append("current_structural_preflight_missing")
        for binding_id in spec.capability_binding_ids:
            try:
                binding, authority_hashes[f"binding:{binding_id}"] = (
                    self.authority.resolve_binding(
                        binding_id, subject_kind="agent", subject_id=spec.agent_id
                    )
                )
                binding_grant_closure.update(
                    str(item) for item in binding.get("effect_grant_ids", [])
                )
            except PermissionError as error:
                reasons.append(f"binding_not_admitted:{binding_id}:{error}")
        for grant_id in spec.effect_grant_ids:
            try:
                _, authority_hashes[f"grant:{grant_id}"] = self.authority.resolve_grant(
                    grant_id, subject_id=spec.agent_id
                )
            except PermissionError as error:
                reasons.append(f"effect_grant_not_admitted:{grant_id}:{error}")
        if binding_grant_closure != set(spec.effect_grant_ids):
            reasons.append("effect_grant_closure_does_not_match_bindings")
        for grant_id in sorted(binding_grant_closure - set(spec.effect_grant_ids)):
            try:
                _, authority_hashes[f"grant:{grant_id}"] = self.authority.resolve_grant(
                    grant_id, subject_id=spec.agent_id
                )
            except PermissionError as error:
                reasons.append(f"transitive_effect_grant_not_admitted:{grant_id}:{error}")
        receipt = self.authority.sign_receipt(
            {
                "schema_version": "px.agent-admission-receipt/1.1",
                "agent_id": spec.agent_id,
                "version": spec.version,
                "agent_revision_sha256": hashlib.sha256(
                    record_path.read_bytes()
                ).hexdigest(),
                "decision": "rejected" if reasons else "admitted",
                "status": "rejected" if reasons else "admitted",
                "reasons": reasons,
                "authority_record_hashes": authority_hashes,
                "runtime_state": "stopped",
                "authority_state": "codex-host-retained",
                "admitted_utc": _now(),
                "nonce": uuid4().hex,
            }
        )
        write_json_atomic(record_path.with_name("admission-receipt.json"), receipt)
        return receipt

    def _admitted_context(
        self, spec: AgentSpec
    ) -> tuple[Path, dict[str, object], dict[str, str]]:
        """Resolve current authority rather than trusting the caller's spec."""
        record_path = self._existing_record_path(spec)
        admission_path = record_path.with_name("admission-receipt.json")
        admission_raw = (
            json.loads(admission_path.read_text(encoding="utf-8"))
            if admission_path.is_file()
            else {}
        )
        admission = (
            self.authority.verify_receipt(admission_raw) if admission_raw else {}
        )
        if (
            admission.get("decision") != "admitted"
            or admission.get("agent_revision_sha256")
            != hashlib.sha256(record_path.read_bytes()).hexdigest()
        ):
            raise PermissionError("current agent admission is required")
        live_hashes: dict[str, str] = {}
        binding_grant_closure: set[str] = set()
        for binding_id in spec.capability_binding_ids:
            binding, live_hashes[f"binding:{binding_id}"] = self.authority.resolve_binding(
                binding_id, subject_kind="agent", subject_id=spec.agent_id
            )
            binding_grant_closure.update(
                str(item) for item in binding.get("effect_grant_ids", [])
            )
        if binding_grant_closure != set(spec.effect_grant_ids):
            raise PermissionError("agent effect grant closure differs from its bindings")
        for grant_id in sorted(binding_grant_closure):
            _, live_hashes[f"grant:{grant_id}"] = self.authority.resolve_grant(
                grant_id, subject_id=spec.agent_id
            )
        if live_hashes != admission.get("authority_record_hashes"):
            raise PermissionError("agent authority changed after admission")
        return record_path, admission, live_hashes

    def preview(self, spec: AgentSpec) -> dict[str, object]:
        """Resolve the exact saved execution contract without launching anything."""
        _record_path, admission, live_hashes = self._admitted_context(spec)
        tools: list[dict[str, object]] = []
        for binding_id in spec.tool_binding_ids:
            binding, binding_sha256 = self.authority.resolve_binding(
                binding_id, subject_kind="agent", subject_id=spec.agent_id
            )
            tools.append(
                {
                    "binding_id": binding_id,
                    "binding_sha256": binding_sha256,
                    "tool_name": binding["capability_id"],
                    "capability_version": binding["capability_version"],
                    "effect_grant_ids": list(binding.get("effect_grant_ids", [])),
                }
            )
        blockers: list[str] = []
        if tools and spec.model.get("provider") == "pacify-local":
            blockers.append("local_model_tool_calling_unavailable")
        if spec.memory_binding_ids:
            blockers.append("memory_bindings_not_runtime_resolved")
        if spec.handoff_agent_ids:
            blockers.append("handoff_agents_not_runtime_resolved")
        return {
            "schema_version": "px.agent-execution-preview/1.0",
            "agent_id": spec.agent_id,
            "version": spec.version,
            "eligible": not blockers,
            "status": "eligible" if not blockers else "blocked",
            "blockers": blockers,
            "model": dict(spec.model),
            "harness_id": spec.harness_id,
            "execution_mode": (
                "host-model" if spec.harness_id == "harness:vscode-lm" else "deterministic-local-worker"
            ),
            "tools": tools,
            "memory_binding_ids": list(spec.memory_binding_ids),
            "handoff_agent_ids": list(spec.handoff_agent_ids),
            "input_schema": dict(spec.input_schema),
            "output_schema": dict(spec.output_schema),
            "authority_record_hashes": dict(live_hashes),
            "admission_sha256": digest(admission),
            "effects_executed": False,
            "host_authority_retained": True,
        }

    def _new_session(
        self, spec: AgentSpec, task: Mapping[str, object], *, approval: bool
    ) -> tuple[str, Path, dict[str, object], dict[str, str]]:
        if not approval:
            raise PermissionError(
                "agent harness launch requires explicit host approval"
            )
        _validate_object_contract(task, spec.input_schema, "input")
        if len(canonical_bytes(task)) > 256 * 1024:
            raise ValueError("agent task exceeds the 256 KiB bounded task contract")
        record_path, admission, live_hashes = self._admitted_context(spec)
        task_sha = digest(task)
        state = self.run_control.create(
            kind="agent",
            subject_id=spec.agent_id,
            version=spec.version,
            owner=spec.owner,
            revision_sha256=str(admission["agent_revision_sha256"]),
            request_sha256=task_sha,
            checkpoint={
                "phase": "authorized",
                "worker_completed": False,
                "resume_strategy": "restart-closed-local-worker",
                "repeat_safe": True,
            },
        )
        return str(state["run_id"]), record_path, admission, live_hashes

    def prepare_host_run(
        self, spec: AgentSpec, *, task: Mapping[str, object], approval: bool
    ) -> dict[str, object]:
        """Authorize one VS Code-hosted model request without transferring host authority."""
        if spec.harness_id != "harness:vscode-lm" or spec.model.get(
            "provider"
        ) not in {"vscode-lm", "pacify-local"}:
            raise ValueError("agent revision is not bound to the VS Code LM harness")
        _validate_object_contract(task, spec.input_schema, "input")
        host_tools: list[dict[str, object]] = []
        for binding_id in spec.tool_binding_ids:
            binding, binding_sha256 = self.authority.resolve_binding(
                binding_id,
                subject_kind="agent",
                subject_id=spec.agent_id,
            )
            resolved_grants: list[dict[str, object]] = []
            for grant_id in binding.get("effect_grant_ids", []):
                grant, grant_sha256 = self.authority.resolve_grant(
                    str(grant_id), subject_id=spec.agent_id
                )
                resolved_grants.append(
                    {
                        "grant_id": str(grant_id),
                        "grant_sha256": grant_sha256,
                        "effects": list(grant.get("effects", [])),
                        "scope_roots": list(grant.get("scope_roots", [])),
                        "expires_utc": grant.get("expires_utc"),
                    }
                )
            host_tools.append(
                {
                    "binding_id": binding_id,
                    "binding_sha256": binding_sha256,
                    "name": str(binding["capability_id"]),
                    "capability_version": str(binding["capability_version"]),
                    "effect_grant_ids": list(binding.get("effect_grant_ids", [])),
                    "grants": resolved_grants,
                    "cost_policy": str(binding.get("cost_policy") or ""),
                    "egress_policy": str(binding.get("egress_policy") or ""),
                    "credential_namespace": binding.get("credential_namespace"),
                }
            )
        if host_tools and spec.model.get("provider") == "pacify-local":
            raise ValueError(
                "the local Ollama provider does not advertise tool calling; remove tool bindings or select a compatible VS Code model"
            )
        run_id, record_path, admission, live_hashes = self._new_session(
            spec, task, approval=approval
        )
        try:
            state = self.run_control.read(run_id)
            running = self.run_control.transition(
                run_id,
                "running",
                actor=spec.owner,
                approved=True,
                checkpoint={
                    **dict(state["checkpoint"]),
                    "phase": "host-model-running",
                    "host_executor": "vscode.lm",
                    "worker_completed": False,
                },
                operation="agent.host-model.start",
            )
            instruction_path = record_path.with_name("instructions.md")
            prepared = {
                "schema_version": "px.agent-host-run-prepared/1.0",
                "run_id": run_id,
                "agent_id": spec.agent_id,
                "version": spec.version,
                "agent_revision_sha256": admission["agent_revision_sha256"],
                "task": dict(task),
                "task_sha256": digest(task),
                "instructions": instruction_path.read_text(encoding="utf-8"),
                "model": dict(spec.model),
                "tool_binding_ids": list(spec.tool_binding_ids),
                "host_tools": host_tools,
                "memory_binding_ids": list(spec.memory_binding_ids),
                "handoff_agent_ids": list(spec.handoff_agent_ids),
                "input_schema": dict(spec.input_schema),
                "output_schema": dict(spec.output_schema),
                "authority_record_hashes": dict(live_hashes),
                "authority_state": "codex-host-retained",
                "host_execution_required": True,
                "status": "prepared",
                "control_sequence": running["sequence"],
            }
            signed = self.authority.sign_receipt(prepared)
            write_json_atomic(
                record_path.parent / "runs" / f"{run_id}-prepared.json", signed
            )
            return signed
        except Exception as error:
            # Once a durable run identity exists, a preparation/publication failure
            # must not strand it in queued/running forever.
            try:
                current = self.run_control.read(run_id)
                if current["state"] in {"queued", "running"}:
                    self.run_control.transition(
                        run_id,
                        "failed",
                        actor=spec.owner,
                        approved=True,
                        checkpoint={
                            **dict(current["checkpoint"]),
                            "phase": "host-model-prepare-failed",
                        },
                        failure={
                            "code": type(error).__name__,
                            "message": str(error)[:500],
                        },
                        operation="agent.host-model.prepare-failed",
                    )
            except Exception:
                # Preserve the original preparation failure. Reconciliation still
                # sees the durable non-terminal head if compensation itself fails.
                pass
            raise

    def complete_host_run(
        self,
        spec: AgentSpec,
        *,
        run_id: str,
        task: Mapping[str, object],
        host_result: Mapping[str, object],
        approval: bool,
    ) -> dict[str, object]:
        """Finalize a host-owned model request with bounded output and durable state."""
        if not approval:
            raise PermissionError("agent host-run completion requires host approval")
        state = self.run_control.read(run_id)
        _validate_object_contract(task, spec.input_schema, "input")
        if (
            state["kind"] != "agent"
            or state["subject_id"] != spec.agent_id
            or state["version"] != spec.version
            or state["request_sha256"] != digest(task)
            or state["state"] not in {"running", "pause_requested", "cancel_requested"}
        ):
            raise PermissionError("agent host-run identity or state does not match")
        try:
            record_path, admission, live_hashes = self._admitted_context(spec)
            if state["revision_sha256"] != admission["agent_revision_sha256"]:
                raise PermissionError("agent host-run revision no longer matches admission")
        except Exception as error:
            # The run identity is already proven above. Authority/admission drift is
            # a terminal completion failure, not permission to strand the run.
            try:
                current = self.run_control.read(run_id)
                if current["state"] in {"running", "pause_requested", "cancel_requested"}:
                    terminal = (
                        "paused"
                        if current["state"] == "pause_requested"
                        else "cancelled"
                        if current["state"] == "cancel_requested"
                        else "failed"
                    )
                    self.run_control.transition(
                        run_id,
                        terminal,
                        actor=spec.owner,
                        approved=True,
                        checkpoint={
                            **dict(current["checkpoint"]),
                            "phase": "host-model-completion-revalidation-failed",
                            "worker_completed": False,
                        },
                        failure=None if terminal != "failed" else {
                            "code": type(error).__name__,
                            "message": str(error)[:500],
                        },
                        operation=f"agent.host-model.completion-revalidation-{terminal}",
                    )
            except Exception:
                pass
            raise
        dispatched: list[object] = []
        output: Mapping[str, object] | object = {}
        completion_validation_failed = False
        try:
            if len(canonical_bytes(host_result)) > 192 * 1024:
                raise ValueError(
                    "agent host result exceeds the 192 KiB approval-envelope budget"
                )
            status = str(host_result.get("status") or "failed")
            output = host_result.get("output", {})
            resolved_model = host_result.get("model", {})
            raw_dispatched = host_result.get("tools_dispatched", [])
            if not isinstance(raw_dispatched, list) or len(raw_dispatched) > 8:
                raise ValueError(
                    "agent host tool receipt exceeds the bounded call contract"
                )
            dispatched = list(raw_dispatched)
            call_ids: set[str] = set()
            allowed_tools: dict[str, dict[str, object]] = {}
            for binding_id in spec.tool_binding_ids:
                binding, binding_sha256 = self.authority.resolve_binding(
                    binding_id, subject_kind="agent", subject_id=spec.agent_id
                )
                grant_ids = [str(item) for item in binding.get("effect_grant_ids", [])]
                effects: set[str] = set()
                scopes: set[str] = set()
                for grant_id in grant_ids:
                    grant, _ = self.authority.resolve_grant(
                        grant_id, subject_id=spec.agent_id
                    )
                    effects.update(str(item) for item in grant.get("effects", []))
                    scopes.update(str(item) for item in grant.get("scope_roots", []))
                allowed_tools[str(binding["capability_id"])] = {
                    "binding_id": binding_id,
                    "binding_sha256": binding_sha256,
                    "effect_grant_ids": sorted(grant_ids),
                    "effects": sorted(effects),
                    "scope_roots": sorted(scopes),
                }
            for item in dispatched:
                if not isinstance(item, Mapping):
                    raise ValueError("agent host tool receipt is malformed")
                expected = allowed_tools.get(str(item.get("name") or ""))
                call_id = str(item.get("call_id") or "")
                if not call_id or call_id in call_ids:
                    raise PermissionError("agent host tool call identity is missing or repeated")
                call_ids.add(call_id)
                if (
                    expected is None
                    or str(item.get("binding_id") or "") != expected["binding_id"]
                    or str(item.get("binding_sha256") or "")
                    != expected["binding_sha256"]
                    or sorted(str(value) for value in item.get("effect_grant_ids", []))
                    != expected["effect_grant_ids"]
                    or sorted(str(value) for value in item.get("effects", []))
                    != expected["effects"]
                    or sorted(str(value) for value in item.get("scope_roots", []))
                    != expected["scope_roots"]
                    or not re.fullmatch(
                        r"[0-9a-f]{64}", str(item.get("input_sha256") or "")
                    )
                    or not re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(item.get("host_tool_interface_sha256") or ""),
                    )
                    or not isinstance(item.get("validated_targets"), list)
                    or len(item.get("validated_targets", [])) > 64
                    or any(
                        not isinstance(target, str) or not target or len(target) > 128
                        for target in item.get("validated_targets", [])
                    )
                    or str(item.get("status") or "") not in {"started", "completed", "failed"}
                    or (
                        item.get("status") == "completed"
                        and not re.fullmatch(
                            r"[0-9a-f]{64}", str(item.get("result_sha256") or "")
                        )
                    )
                ):
                    raise PermissionError(
                        "agent host reported an unbound or changed tool call"
                    )
            if status == "completed" and any(
                str(item.get("status") or "") != "completed" for item in dispatched
            ):
                raise PermissionError(
                    "completed agent host result contains a non-terminal tool receipt"
                )
            if status == "completed":
                if not isinstance(resolved_model, Mapping):
                    raise ValueError("agent host result omitted resolved model identity")
                for admitted_field, resolved_field in (
                    ("model_id", "id"),
                    ("vendor", "vendor"),
                    ("family", "family"),
                    ("version", "version"),
                ):
                    if str(spec.model.get(admitted_field) or "") != str(
                        resolved_model.get(resolved_field) or ""
                    ):
                        raise PermissionError(
                            f"agent host resolved model {resolved_field} differs from admission"
                        )
                options = resolved_model.get("requested_model_options")
                if not isinstance(options, Mapping) or int(
                    options.get("maxOutputTokens", -1)
                ) != int(spec.model["max_output_tokens"]) or float(
                    options.get("temperature", -1)
                ) != float(spec.model["temperature"]):
                    raise PermissionError("agent host model options differ from admission")
                output_tokens = int(resolved_model.get("output_tokens", -1))
                output_limit = int(resolved_model.get("output_token_limit", -1))
                aggregate_tokens = int(resolved_model.get("aggregate_input_tokens", -1))
                aggregate_limit = int(
                    resolved_model.get("aggregate_input_token_limit", -1)
                )
                if (
                    output_tokens < 0
                    or output_limit != int(spec.model["max_output_tokens"])
                    or output_tokens > output_limit
                    or aggregate_tokens < 0
                    or aggregate_limit < 0
                    or aggregate_tokens > aggregate_limit
                ):
                    raise ValueError("agent host model token counters violate admission")
            fresh_state = self.run_control.read(run_id)
            if fresh_state["state"] == "pause_requested":
                target = "paused"
                failure = None
                output = {}
            elif fresh_state["state"] == "cancel_requested":
                target = "cancelled"
                failure = None
                output = {}
            elif status == "completed":
                if not isinstance(output, Mapping):
                    raise TypeError("agent host output must be an object")
                _validate_object_contract(output, spec.output_schema, "output")
                target = "succeeded"
                failure = None
            elif status == "cancelled":
                target = "cancelled"
                failure = {
                    "code": str(
                        host_result.get("error_code") or "HOST_MODEL_CANCELLED"
                    ),
                    "message": str(
                        host_result.get("error")
                        or "Host model request was cancelled"
                    )[:500],
                }
                output = {}
            else:
                target = "failed"
                failure = {
                    "code": str(host_result.get("error_code") or "HOST_MODEL_FAILED"),
                    "message": str(
                        host_result.get("error") or "Host model request failed"
                    )[:500],
                }
                output = {}
        except Exception as error:
            # A malformed/oversized/contract-invalid host result is a failed run,
            # not an exception path that may leave the durable head at running.
            completion_validation_failed = True
            target = "failed"
            failure = {
                "code": type(error).__name__,
                "message": str(error)[:500],
            }
            output = {}
        final = self.run_control.transition(
            run_id,
            target,
            actor=spec.owner,
            approved=True,
            checkpoint={
                **dict(state["checkpoint"]),
                "phase": target,
                "worker_completed": target == "succeeded",
                "host_executor": "vscode.lm",
                "output_sha256": digest(output),
            },
            failure=failure,
            operation=f"agent.host-model.{target}",
        )
        receipt = {
            "schema_version": "px.agent-runtime-receipt/1.3",
            "run_id": run_id,
            "agent_id": spec.agent_id,
            "version": spec.version,
            "runtime_state": target,
            "status": target,
            "run_outcome": target,
            "worker_invoked": False,
            "model_request_completed": target == "succeeded",
            "completion_validation_failed": completion_validation_failed,
            "host_executor": "vscode.lm",
            "execution_mode": "host-model",
            "requested_model_route": dict(spec.model),
            "resolved_model": dict(host_result.get("model", {}))
            if isinstance(host_result.get("model"), Mapping)
            else {},
            "output": dict(output),
            "output_sha256": digest(output),
            "task_sha256": digest(task),
            "authority_record_hashes": dict(live_hashes),
            "authority_state": "codex-host-retained",
            "tools_dispatched": list(dispatched),
            "control_sequence": final["sequence"],
            "control_head_sha256": digest(final),
            "error": failure,
        }
        signed = self.authority.sign_receipt(receipt)
        write_json_atomic(record_path.parent / "runs" / f"{run_id}.json", signed)
        return signed

    def _execute_session(
        self,
        spec: AgentSpec,
        *,
        task: Mapping[str, object],
        run_id: str,
        record_path: Path,
        admission: Mapping[str, object],
        live_hashes: Mapping[str, str],
        defer_terminal_publication: bool = False,
    ) -> dict[str, object]:
        _validate_object_contract(task, spec.input_schema, "input")
        task_sha = digest(task)
        state = self.run_control.read(run_id)
        if (
            state["kind"] != "agent"
            or state["subject_id"] != spec.agent_id
            or state["version"] != spec.version
            or state["revision_sha256"] != admission["agent_revision_sha256"]
            or state["request_sha256"] != task_sha
        ):
            raise PermissionError("agent resume identity does not match durable state")
        if state["state"] not in {"queued", "paused", "interrupted"}:
            raise ValueError(f"agent session cannot start from {state['state']}")
        self.run_control.transition(
            run_id,
            "running",
            actor=spec.owner,
            approved=True,
            checkpoint={
                **dict(state["checkpoint"]),
                "phase": "worker-running",
                "worker_completed": False,
            },
            operation="agent.worker.start"
            if state["state"] == "queued"
            else "agent.worker.resume",
        )
        task_root = self.state_root / "tasks"
        verify_safe_ancestors(self.project_root, task_root)
        task_root.mkdir(parents=True, exist_ok=True)
        task_run_id = f"agent-task-{run_id[4:]}-{uuid4().hex[:8]}"
        task_resource = self.manager.create_workspace(
            task_root,
            project_id=spec.project_id,
            run_id=task_run_id,
            lane_id=spec.agent_id,
            creator=spec.owner,
            prefix=f"{task_sha[:12]}-",
        )
        task_path = Path(str(task_resource.path)) / "task.json"
        task_record = self.authority.sign_receipt(
            {
                "schema_version": "px.agent-harness-task/1.2",
                "agent_id": spec.agent_id,
                "agent_revision_sha256": admission["agent_revision_sha256"],
                "task_sha256": task_sha,
                "task": dict(task),
                "harness_id": spec.harness_id,
                "binding_ids": list(spec.capability_binding_ids),
                "effect_grant_ids": list(spec.effect_grant_ids),
                "authority_record_hashes": live_hashes,
                "created_utc": _now(),
                "nonce": uuid4().hex,
            }
        )
        budget = {
            "startup_timeout_seconds": 2.0,
            "idle_timeout_seconds": 2.0,
            "total_timeout_seconds": 10.0,
            "graceful_shutdown_seconds": 2.0,
            "force_shutdown_seconds": 5.0,
            "stdout_limit_bytes": 8192,
            "stderr_limit_bytes": 8192,
        }
        limits = {
            **budget,
            "total_timeout_seconds": 30.0,
            "stdout_limit_bytes": 65536,
            "stderr_limit_bytes": 65536,
        }
        try:
            write_json_atomic(task_path, task_record)
            result = self.supervisor.run(
                [
                    sys.executable,
                    "-m",
                    "runtime.agent_harness_worker",
                    "--project-root",
                    str(self.project_root),
                    "--task",
                    str(task_path),
                ],
                cwd=self.project_root,
                action={
                    "action_id": f"agent-harness-{uuid4().hex}",
                    "effects": ["process"],
                    "allowed_effects": ["process"],
                    "target_paths": [str(task_path)],
                    "owned_paths": [str(self.project_root)],
                    "budget": budget,
                    "limits": limits,
                    "approval": True,
                    "policy_override_requested": False,
                },
                project_id=spec.project_id,
                run_id=run_id,
                lane_id="agent-harness",
                creator=spec.agent_id,
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
                cancel_event=DurableControlSignal(self.run_control, run_id),
            )
        except Exception as error:
            self.manager.mark_run_ended(task_run_id, RunState.FAILED)
            cleanup = self.manager.reclaim(
                task_resource.resource_id,
                reason="agent_task_launch_failed",
                apply=True,
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
                self.run_control.transition(
                    run_id,
                    published_state,
                    actor=spec.owner,
                    approved=True,
                    failure=None
                    if target in {"paused", "cancelled"}
                    else {"code": type(error).__name__, "message": str(error)[:500]},
                    checkpoint={
                        **dict(current["checkpoint"]),
                        "phase": target,
                        "task_cleanup_receipt": cleanup.cleanup_id,
                        **(
                            {"terminal_target": target}
                            if published_state == "finalizing"
                            else {}
                        ),
                    },
                    operation=f"agent.worker.{published_state}",
                )
            raise
        worker_result: dict[str, object] = {}
        if result.stdout.text.strip():
            try:
                worker_result = json.loads(result.stdout.text.strip().splitlines()[-1])
            except json.JSONDecodeError:
                worker_result = {"status": "invalid_worker_result"}
        succeeded = (
            result.status == "exited"
            and result.exit_code == 0
            and result.tree_closed
            and worker_result.get("status") == "completed"
        )
        control_state = self.run_control.read(run_id)
        requested = str(control_state["state"])
        ended_state = (
            RunState.CANCELLED
            if requested in {"pause_requested", "cancel_requested"}
            or result.status == "cancelled"
            else RunState.COMPLETED
            if succeeded
            else RunState.FAILED
        )
        self.manager.mark_run_ended(task_run_id, ended_state)
        task_cleanup = self.manager.reclaim(
            task_resource.resource_id,
            reason="agent_task_content_reclaimed",
            apply=True,
        )
        if task_cleanup.errors:
            raise OSError(
                "agent task content cleanup did not close: "
                + "; ".join(task_cleanup.errors)
            )
        target_state = (
            "paused"
            if requested == "pause_requested"
            else "cancelled"
            if requested == "cancel_requested"
            else "succeeded"
            if succeeded
            else "failed"
        )
        checkpoint = {
            **dict(control_state["checkpoint"]),
            "phase": target_state,
            "worker_completed": succeeded,
            "process_status": result.status,
            "process_receipt": result.receipt_path,
            "task_cleanup_receipt": task_cleanup.cleanup_id,
        }
        published_state = (
            "finalizing"
            if defer_terminal_publication and target_state in TERMINAL_STATES
            else target_state
        )
        final_state = self.run_control.transition(
            run_id,
            published_state,
            actor=spec.owner,
            approved=True,
            checkpoint={
                **checkpoint,
                **(
                    {"terminal_target": target_state}
                    if published_state == "finalizing"
                    else {}
                ),
            },
            failure=None
            if target_state in {"paused", "cancelled", "succeeded"}
            else {
                "code": result.failure_type or "WORKER_FAILED",
                "process_status": result.status,
                "exit_code": result.exit_code,
            },
            operation=f"agent.worker.{published_state}",
        )
        receipt = {
            "schema_version": "px.agent-runtime-receipt/1.2",
            "run_id": run_id,
            "agent_id": spec.agent_id,
            "version": spec.version,
            "runtime_state": published_state,
            "terminal_target": (
                target_state if published_state == "finalizing" else None
            ),
            "process_started": result.resource_id is not None,
            "process_status": result.status,
            "run_outcome": target_state,
            "exit_code": result.exit_code,
            "tree_closed": result.tree_closed,
            "worker_invoked": worker_result.get("worker_invoked") is True,
            "model_invoked": worker_result.get("model_invoked") is True,
            "worker_result_sha256": digest(worker_result) if worker_result else None,
            "requested_model_route": dict(spec.model),
            "execution_mode": "deterministic-local-worker",
            "authority_record_hashes": live_hashes,
            "authority_state": "codex-host-retained",
            "process_receipt": result.receipt_path,
            "task_sha256": task_sha,
            "task_content_retained": False,
            "task_cleanup_receipt": task_cleanup.cleanup_id,
            "tools_dispatched": worker_result.get("tools_dispatched", []),
            "control_sequence": final_state["sequence"],
            "control_head_sha256": digest(final_state),
            "resumable": target_state in {"paused", "interrupted"},
        }
        signed = self.authority.sign_receipt(receipt)
        write_json_atomic(record_path.parent / "runs" / f"{run_id}.json", signed)
        return signed

    def invoke_harness(
        self, spec: AgentSpec, *, task: Mapping[str, object], approval: bool
    ) -> dict[str, object]:
        run_id, record_path, admission, live_hashes = self._new_session(
            spec, task, approval=approval
        )
        return self._execute_session(
            spec,
            task=task,
            run_id=run_id,
            record_path=record_path,
            admission=admission,
            live_hashes=live_hashes,
        )

    def start_harness(
        self, spec: AgentSpec, *, task: Mapping[str, object], approval: bool
    ) -> dict[str, object]:
        """Start an owned session asynchronously and return its durable identity."""
        if spec.harness_id != "harness:px":
            raise ValueError(
                "asynchronous Agent start is available only for the owned deterministic harness; host model execution must use prepare-host-run"
            )
        run_id, record_path, admission, live_hashes = self._new_session(
            spec, task, approval=approval
        )

        return launch_studio_worker(
            project_root=self.project_root,
            state_root=self.state_root,
            manager=self.manager,
            authority=self.authority,
            run_control=self.run_control,
            kind="agent",
            run_id=run_id,
            payload={
                "spec": asdict(spec),
                "task": dict(task),
                "record_path": record_path.relative_to(self.project_root).as_posix(),
                "admission": dict(admission),
                "live_hashes": dict(live_hashes),
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
        """Request pause/cancel; opaque workers are boundedly terminated, not frozen."""
        target = {"pause": "pause_requested", "cancel": "cancel_requested", "stop": "cancel_requested"}.get(action)
        if target is None:
            raise ValueError("agent lifecycle action must be pause, cancel, or stop")
        state = self.run_control.read(run_id)
        if state["kind"] != "agent":
            raise PermissionError("durable run is not an agent session")
        return self.run_control.transition(
            run_id,
            target,
            actor=approved_by,
            approved=approved,
            checkpoint={
                **dict(state["checkpoint"]),
                "requested_action": action,
                "shutdown_policy": "bounded-process-tree-termination",
            },
            operation=f"agent.request.{action}",
        )

    def resume_harness(
        self,
        spec: AgentSpec,
        *,
        run_id: str,
        task: Mapping[str, object],
        approval: bool,
    ) -> dict[str, object]:
        if not approval:
            raise PermissionError("agent resume requires explicit host approval")
        record_path, admission, live_hashes = self._admitted_context(spec)
        if spec.harness_id == "harness:vscode-lm":
            _validate_object_contract(task, spec.input_schema, "input")
            state = self.run_control.read(run_id)
            if (
                state["kind"] != "agent"
                or state["subject_id"] != spec.agent_id
                or state["version"] != spec.version
                or state["revision_sha256"] != admission["agent_revision_sha256"]
                or state["request_sha256"] != digest(task)
                or state["state"] not in {"paused", "interrupted"}
            ):
                raise PermissionError("host agent resume identity or state does not match")
            host_tools: list[dict[str, object]] = []
            for binding_id in spec.tool_binding_ids:
                binding, binding_sha256 = self.authority.resolve_binding(
                    binding_id, subject_kind="agent", subject_id=spec.agent_id
                )
                resolved_grants: list[dict[str, object]] = []
                for grant_id in binding.get("effect_grant_ids", []):
                    grant, grant_sha256 = self.authority.resolve_grant(
                        str(grant_id), subject_id=spec.agent_id
                    )
                    resolved_grants.append(
                        {
                            "grant_id": str(grant_id),
                            "grant_sha256": grant_sha256,
                            "effects": list(grant.get("effects", [])),
                            "scope_roots": list(grant.get("scope_roots", [])),
                            "expires_utc": grant.get("expires_utc"),
                        }
                    )
                host_tools.append(
                    {
                        "binding_id": binding_id,
                        "binding_sha256": binding_sha256,
                        "name": str(binding["capability_id"]),
                        "capability_version": str(binding["capability_version"]),
                        "effect_grant_ids": list(binding.get("effect_grant_ids", [])),
                        "grants": resolved_grants,
                        "cost_policy": str(binding.get("cost_policy") or ""),
                        "egress_policy": str(binding.get("egress_policy") or ""),
                        "credential_namespace": binding.get("credential_namespace"),
                    }
                )
            try:
                running = self.run_control.transition(
                    run_id,
                    "running",
                    actor=spec.owner,
                    approved=True,
                    checkpoint={
                        **dict(state["checkpoint"]),
                        "phase": "host-model-running",
                        "host_executor": "vscode.lm",
                        "worker_completed": False,
                    },
                    operation="agent.host-model.resume",
                )
                prepared = {
                "schema_version": "px.agent-host-run-prepared/1.0",
                "run_id": run_id,
                "agent_id": spec.agent_id,
                "version": spec.version,
                "agent_revision_sha256": admission["agent_revision_sha256"],
                "task": dict(task),
                "task_sha256": digest(task),
                "instructions": record_path.with_name("instructions.md").read_text(encoding="utf-8"),
                "model": dict(spec.model),
                "tool_binding_ids": list(spec.tool_binding_ids),
                "host_tools": host_tools,
                "memory_binding_ids": list(spec.memory_binding_ids),
                "handoff_agent_ids": list(spec.handoff_agent_ids),
                "input_schema": dict(spec.input_schema),
                "output_schema": dict(spec.output_schema),
                "authority_record_hashes": dict(live_hashes),
                "authority_state": "codex-host-retained",
                "host_execution_required": True,
                "status": "prepared",
                "resume": True,
                "control_sequence": running["sequence"],
                }
                signed = self.authority.sign_receipt(prepared)
                write_json_atomic(
                    record_path.parent
                    / "runs"
                    / f"{run_id}-resume-{running['sequence']}.json",
                    signed,
                )
                return signed
            except Exception as error:
                try:
                    current = self.run_control.read(run_id)
                    if current["state"] == "running":
                        self.run_control.transition(
                            run_id,
                            "failed",
                            actor=spec.owner,
                            approved=True,
                            checkpoint={
                                **dict(current["checkpoint"]),
                                "phase": "host-model-resume-failed",
                            },
                            failure={
                                "code": type(error).__name__,
                                "message": str(error)[:500],
                            },
                            operation="agent.host-model.resume-failed",
                        )
                except Exception:
                    pass
                raise
        if spec.harness_id != "harness:px":
            raise ValueError("agent resume harness is not admitted")
        _validate_object_contract(task, spec.input_schema, "input")
        return self._execute_session(
            spec,
            task=task,
            run_id=run_id,
            record_path=record_path,
            admission=admission,
            live_hashes=live_hashes,
        )

    def session_status(self, run_id: str) -> dict[str, object]:
        """Read the durable head without reconciling or publishing state."""
        return self.run_control.read(run_id)

    def list_sessions(self, *, limit: int = 100) -> dict[str, object]:
        return self.run_control.list_runs(kind="agent", limit=limit)

    def reconcile_sessions(
        self, *, approved: bool, approved_by: str, stale_after_seconds: float = 60.0
    ) -> dict[str, object]:
        return self.run_control.reconcile(
            actor=approved_by,
            approved=approved,
            stale_after_seconds=stale_after_seconds,
        )
