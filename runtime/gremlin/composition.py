"""Explicit host composition for Gremlin identity, audit, and recovery owners."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .audit import GremlinAuditLedger
from .containment import ContainmentError, GremlinNanny
from .observers import ObserverSet
from .recovery_authority import (
    FileRecoveryReplayLedger,
    RecoveryApproval,
    RecoveryApprovalVerifier,
    RecoveryAuthority,
    RecoveryAuthorizationError,
    RecoveryChallenge,
    RecoveryDecision,
)
from .supervisor import DeterministicSupervisor
from .runtime_identity import (
    GremlinRuntimeIdentityStore,
    RuntimeIdentityMetadata,
)


@dataclass(frozen=True, slots=True)
class GremlinRuntimeComposition:
    """A host-owned pair of containment and independent recovery authorities."""

    nanny: GremlinNanny
    recovery_authority: RecoveryAuthority
    replay_ledger: FileRecoveryReplayLedger
    audit_ledger: GremlinAuditLedger

    def supervise_child(
        self, supervisor, command, *, parent_execution_id: str, parent_resource_id: str,
        child_execution_id: str, agent_id: str, policy_profile: str,
        model_id: str | None = None, runtime_id: str | None = None,
        orchestration_id: str | None = None, **supervision,
    ):
        """Host child launch: native suspended creation ? enrollment ? resume.

        Retains both native Jobs in the canonical supervisor. Unsupported nested
        membership fails before resume. Commissioning and admission remain the
        caller's obligations; this operation creates neither authority nor grants.
        """
        from ..process_supervisor import ProcessSupervisor
        from .enrollment import enroll_suspended_supervised_child
        if type(supervisor) is not ProcessSupervisor:
            raise TypeError("canonical ProcessSupervisor required")
        if "before_release" in supervision:
            raise ValueError("child pre-release enrollment is owned by Gremlin composition")
        enrollment = None
        resource_id = None

        def before_release(custody):
            nonlocal enrollment, resource_id
            resource_id = custody.parent_resource_id
            enrollment = enroll_suspended_supervised_child(
                self.nanny, supervisor.manager, custody,
                parent_execution_id=parent_execution_id, parent_resource_id=parent_resource_id,
                child_execution_id=child_execution_id, agent_id=agent_id,
                policy_profile=policy_profile, model_id=model_id, runtime_id=runtime_id,
                orchestration_id=orchestration_id)
            return enrollment

        try:
            return supervisor.run(command, before_release=before_release, **supervision)
        finally:
            if enrollment is not None and resource_id is not None:
                import sys
                original = sys.exception()
                try:
                    self.nanny.close_supervised_execution(child_execution_id,
                        supervisor.manager, resource_id)
                except Exception as error:
                    if original is None:
                        raise
                    original.add_note("protected child settlement failed: " + str(error))

    def issue_recovery_challenge(
        self,
        *,
        execution_id: str,
        operation: str,
        reason_code: str,
        ttl_seconds: int = 120,
        now: datetime | None = None,
    ) -> RecoveryChallenge:
        execution = self.nanny.registry.get(execution_id)
        if execution is None:
            raise ContainmentError(
                "recovery challenge requires a registered protected execution"
            )
        return self.recovery_authority.issue_challenge(
            requesting_authority_id=self.nanny.authority.authority_id,
            protected_execution_id=execution.identity.agent_execution_id,
            operation=operation,
            reason_code=reason_code,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    def authorize_recovery(
        self,
        challenge: RecoveryChallenge,
        approval: RecoveryApproval,
        *,
        now: datetime | None = None,
    ) -> RecoveryDecision:
        execution = self.nanny.registry.get(challenge.protected_execution_id)
        if execution is None:
            raise ContainmentError(
                "recovery authorization requires a registered protected execution"
            )
        return self.recovery_authority.authorize(
            challenge,
            approval,
            expected_nanny_authority_id=self.nanny.authority.authority_id,
            supervised_identity_id=execution.identity.agent_execution_id,
            now=now,
        )


def compose_gremlin_runtime(
    *,
    project_root: Path,
    nanny_authority_id: str,
    recovery_authority_id: str,
    identity_store: GremlinRuntimeIdentityStore,
    runtime_identity: RuntimeIdentityMetadata,
    recovery_verifier: RecoveryApprovalVerifier,
    observers: ObserverSet | None = None,
    supervisor_backend=None,
) -> GremlinRuntimeComposition:
    """Compose existing owners without silently commissioning identity or auth.

    The caller must supply an already commissioned local identity and a real,
    independent recovery verifier. No identity is created and no authenticator
    is substituted by this function.
    """
    if not isinstance(nanny_authority_id, str) or not nanny_authority_id.strip():
        raise ValueError("Nanny authority identity is required")
    if not isinstance(recovery_authority_id, str) or not recovery_authority_id.strip():
        raise ValueError("independent recovery authority identity is required")
    if nanny_authority_id == recovery_authority_id:
        raise ValueError("recovery authority must be independent from the Nanny")
    if not callable(getattr(recovery_verifier, "verify", None)):
        raise ValueError("a concrete independent recovery verifier is required")

    audit_ledger = GremlinAuditLedger(project_root)
    replay_ledger = FileRecoveryReplayLedger(project_root)
    nanny = GremlinNanny(
        authority_id=nanny_authority_id,
        runtime_identity_store=identity_store,
        runtime_identity=runtime_identity,
        observers=observers,
        supervisor=(DeterministicSupervisor(supervisor_backend) if supervisor_backend is not None else None),
    )
    recovery_authority = RecoveryAuthority(
        authority_id=recovery_authority_id,
        verifier=recovery_verifier,
        replay_ledger=replay_ledger,
        audit_sink=audit_ledger,
    )
    return GremlinRuntimeComposition(
        nanny=nanny,
        recovery_authority=recovery_authority,
        replay_ledger=replay_ledger,
        audit_ledger=audit_ledger,
    )
