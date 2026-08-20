"""Bounded, fail-closed orchestration over admitted capability metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .config import BootstrapConfig, load_startup_config
from .evidence_assembler import (
    Claim,
    EvidenceLink,
    EvidencePackage,
    EvidenceRecord,
    assemble_evidence,
)
from .execution_contract import ExecutionRequest, PolicyDecision, enforce
from .lifecycle import (
    Checkpoint,
    CheckpointSink,
    FailureRecord,
    MemoryCheckpointSink,
    failure_fingerprint,
    make_checkpoint,
)
from .outcome_verifier import VerificationDecision, verify
from .operation_authority import AuthorityRequest, decide as decide_authority
from .registry import load_json, navigation_index, validate_registry
from .skill_navigator import CapabilitySummary, navigate


@dataclass(frozen=True, slots=True)
class TaskRequest:
    task_id: str
    goal: str
    inputs: Mapping[str, object]
    requested_effects: tuple[str, ...] = ("read_local",)
    preferred_capability_id: str | None = None
    timeout_seconds: int = 30
    max_tool_calls: int = 0
    idempotency_key: str | None = None
    attempt: int = 1
    executor: str = "codex-host"
    px_policy_decision_id: str | None = None
    claim_id: str | None = None
    claim_status: str | None = None
    explicit_delegation: bool = False
    active_executors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskContext:
    request: TaskRequest
    capability_manifest: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    claims: tuple[Claim, ...]
    evidence: tuple[EvidenceRecord, ...]
    links: tuple[EvidenceLink, ...]
    postconditions: Mapping[str, bool]
    executor_claimed_complete: bool


class Handler(Protocol):
    def __call__(self, context: TaskContext) -> CapabilityResult: ...


HandlerResolver = Callable[[str], Handler | None]


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    task_id: str
    status: str
    capability_id: str | None
    stages: tuple[str, ...]
    errors: tuple[str, ...]
    evidence: EvidencePackage | None
    verification: VerificationDecision | None
    checkpoints: tuple[Checkpoint, ...]
    failure: FailureRecord | None
    unloaded: bool


class Orchestrator:
    """Run one admitted capability while bounding activation to one handler."""

    def __init__(
        self,
        root: Path,
        handler_resolver: HandlerResolver,
        *,
        checkpoint_sink: CheckpointSink | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.handler_resolver = handler_resolver
        self.checkpoint_sink = checkpoint_sink or MemoryCheckpointSink()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.config: BootstrapConfig = load_startup_config(
            self.root / "bootstrap" / "startup.toml"
        )

    def run(self, request: TaskRequest, policy: PolicyDecision) -> OrchestrationResult:
        stages: list[str] = []
        checkpoints: list[Checkpoint] = []
        selected: CapabilitySummary | None = None
        package: EvidencePackage | None = None
        verification: VerificationDecision | None = None
        failure: FailureRecord | None = None
        handler: Handler | None = None

        def mark(
            stage: str, status: str = "passed", evidence_ids: tuple[str, ...] = ()
        ) -> None:
            stages.append(stage)
            checkpoint = make_checkpoint(
                request.task_id,
                len(checkpoints) + 1,
                stage,
                status,
                selected.capability_id if selected else None,
                evidence_ids,
            )
            self.checkpoint_sink.append(checkpoint)
            checkpoints.append(checkpoint)

        def finish(
            status: str, errors: tuple[str, ...] = (), *, unloaded: bool = True
        ) -> OrchestrationResult:
            return OrchestrationResult(
                request.task_id,
                status,
                selected.capability_id if selected else None,
                tuple(stages),
                errors,
                package,
                verification,
                tuple(checkpoints),
                failure,
                unloaded,
            )

        if not request.task_id.strip() or not request.goal.strip():
            mark("request_rejected", "failed")
            return finish("blocked", ("task_id and goal are required",))
        registry_result = validate_registry(self.root)
        if not registry_result["valid"]:
            mark("registry_validation", "failed")
            return finish("blocked", tuple(registry_result["errors"]))
        mark("registry_validation")

        index = navigation_index(self.root)
        if request.preferred_capability_id:
            selected = next(
                (
                    item
                    for item in index
                    if item.capability_id == request.preferred_capability_id
                ),
                None,
            )
            if selected is None:
                mark("selection", "failed")
                return finish("blocked", ("preferred capability is not active",))
        else:
            navigation = navigate(
                request.goal,
                index,
                request.inputs,
                max_candidates=self.config.budget.max_active_capabilities,
            )
            selected = next(
                (
                    item
                    for item in index
                    if navigation.candidates
                    and item.capability_id == navigation.candidates[0].capability_id
                ),
                None,
            )
            if selected is None:
                mark("selection", "failed")
                return finish("blocked", (navigation.reason,))
        missing_inputs = tuple(
            sorted(set(selected.required_inputs) - set(request.inputs))
        )
        if missing_inputs:
            mark("input_validation", "failed")
            return finish("blocked", ("missing inputs: " + ", ".join(missing_inputs),))
        mark("selection")

        capability_item = next(
            item
            for item in load_json(self.root / "registry" / "capability_map.json")[
                "active_capabilities"
            ]
            if item["id"] == selected.capability_id
        )
        manifest = load_json(self.root / capability_item["contract"])
        authority = decide_authority(
            AuthorityRequest(
                executor=request.executor,
                effects=request.requested_effects,
                user_approval_id=policy.approval_id,
                px_policy_decision_id=request.px_policy_decision_id,
                claim_id=request.claim_id,
                claim_status=request.claim_status,
                idempotency_key=request.idempotency_key,
                explicit_delegation=request.explicit_delegation,
                active_executors=request.active_executors,
            )
        )
        if not authority.allowed:
            mark("authority", "failed")
            return finish("blocked", authority.reasons)
        mark("authority")
        contract = enforce(
            ExecutionRequest(
                selected.capability_id,
                request.requested_effects,
                request.timeout_seconds,
                request.max_tool_calls,
                request.idempotency_key,
            ),
            policy,
            manifest,
        )
        if not contract.approved:
            mark("authorization", "failed")
            return finish("blocked", contract.reasons)
        mark("authorization")

        # Handler lookup is intentionally after registry, input, and policy authorization.
        handler = self.handler_resolver(selected.capability_id)
        if handler is None:
            mark("activation", "failed")
            return finish("blocked", ("no runtime handler is registered",))
        mark("activation")
        try:
            outcome = handler(TaskContext(request, manifest))
            mark("execution")
            package = assemble_evidence(
                request.task_id,
                outcome.claims,
                outcome.evidence,
                outcome.links,
                as_of=self.now(),
                max_age=timedelta(days=1),
            )
            evidence_ids = tuple(
                attachment.record.evidence_id
                for claim in package.claims
                for attachment in claim.attachments
                if attachment.usable_for_support
            )
            mark("evidence_assembly", evidence_ids=evidence_ids)
            verification = verify(
                outcome.postconditions,
                [
                    {"id": evidence_id, "status": "current", "valid": True}
                    for evidence_id in evidence_ids
                ],
                policy_allowed=policy.allowed,
                executor_claimed_complete=outcome.executor_claimed_complete,
            )
            mark(
                "verification",
                "passed" if verification.status == "verified" else "failed",
                evidence_ids,
            )
            status = (
                "completed"
                if verification.status == "verified" and not package.unsupported_claims
                else "incomplete"
            )
            errors = tuple(
                list(verification.failed_checks)
                + (
                    ["unsupported claims: " + ", ".join(package.unsupported_claims)]
                    if package.unsupported_claims
                    else []
                )
            )
            return finish(status, errors)
        except Exception as error:  # capability boundary must fail closed
            fingerprint = failure_fingerprint(
                selected.capability_id, type(error).__name__, str(error)
            )
            failure = FailureRecord(
                request.task_id,
                selected.capability_id,
                fingerprint,
                request.attempt,
                (),
                f"{type(error).__name__}: {error}",
            )
            mark("execution", "failed")
            return finish("failed", (failure.message,))
        finally:
            # Drop the only runtime-held handler reference at the step boundary.
            handler = None
