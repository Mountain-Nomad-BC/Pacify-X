from __future__ import annotations

from contextlib import contextmanager

import pytest

from runtime.gremlin.receipts import ContainmentAuthority, ContainmentReceipt
from runtime.gremlin.audit import GremlinAuditLedger
from runtime.gremlin.commissioning import create_local_runtime_identity
from runtime.gremlin.runtime_identity import (
    GremlinRuntimeIdentityStore,
    RuntimeIdentityError,
    RuntimeIdentityRevoked,
)


class MemoryCredentialBackend:
    backend_id = "test-only-protected-store"

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    @contextmanager
    def transaction(self, target: str):
        yield

    def read(self, target: str) -> bytes | None:
        return self.values.get(target)

    def write(self, target: str, value: bytes) -> None:
        self.values[target] = value

    def delete(self, target: str) -> bool:
        return self.values.pop(target, None) is not None


def _receipt(authority_id: str) -> ContainmentReceipt:
    return ContainmentReceipt(
        receipt_id="receipt-1",
        agent_execution_id="execution-1",
        agent_id="agent-1",
        pid=1234,
        process_start_identity="start-1",
        sandbox_id="sandbox-1",
        policy_profile="strict",
        gremlin_revision="revision-1",
        identity_sha256="a" * 64,
        issued_at_utc="2026-10-06T00:00:00Z",
        issued_by=authority_id,
    )


def test_local_identity_creation_rotation_and_revocation_invalidate_old_receipts() -> None:
    backend = MemoryCredentialBackend()
    events: list[dict[str, object]] = []
    store = GremlinRuntimeIdentityStore(backend, audit_sink=events.append)

    identity = store.create("local-gremlin", now_utc="2026-10-06T00:00:00Z")
    authority = ContainmentAuthority.from_runtime_identity(
        authority_id="local-gremlin",
        identity_store=store,
        identity=identity,
    )
    first_receipt = authority.issue(_receipt("local-gremlin"))
    assert authority.verify(first_receipt)

    rotated = store.rotate(identity, now_utc="2026-10-06T00:01:00Z")
    assert rotated.generation == identity.generation + 1
    assert not authority.verify(first_receipt)
    with pytest.raises(RuntimeIdentityRevoked):
        store.signing_key_provider(identity)()

    store.revoke(rotated, now_utc="2026-10-06T00:02:00Z")
    assert not authority.verify(first_receipt)
    assert [event["event_type"] for event in events] == [
        "runtime_identity_created",
        "runtime_identity_rotated",
        "runtime_identity_revoked",
    ]


def test_identity_requires_explicit_rotation_and_audit_sink() -> None:
    backend = MemoryCredentialBackend()
    events: list[dict[str, object]] = []
    store = GremlinRuntimeIdentityStore(backend, audit_sink=events.append)
    identity = store.create("local-gremlin")

    with pytest.raises(RuntimeIdentityError, match="already exists"):
        store.create("local-gremlin")
    with pytest.raises(ValueError, match="canonical audit sink"):
        GremlinRuntimeIdentityStore(backend, audit_sink=None)  # type: ignore[arg-type]
    assert store.inspect("local-gremlin") == identity


def test_identity_audit_failure_rolls_back_creation() -> None:
    backend = MemoryCredentialBackend()

    def fail_audit(_event: object) -> None:
        raise OSError("audit unavailable")

    store = GremlinRuntimeIdentityStore(backend, audit_sink=fail_audit)
    with pytest.raises(RuntimeIdentityError, match="creation audit failed"):
        store.create("local-gremlin")
    assert backend.read("Pacify-X/Gremlin/runtime/local-gremlin") is None


def test_explicit_commissioning_uses_the_canonical_audit_sink(tmp_path) -> None:
    backend = MemoryCredentialBackend()

    store, identity = create_local_runtime_identity(
        tmp_path,
        "local-gremlin",
        backend=backend,
    )

    assert store.inspect("local-gremlin") == identity
    assert GremlinAuditLedger(tmp_path).path.is_dir()
