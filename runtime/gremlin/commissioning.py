"""Explicit local Gremlin runtime identity commissioning."""

from __future__ import annotations

from pathlib import Path

from .audit import GremlinAuditLedger
from .runtime_identity import (
    GremlinRuntimeIdentityStore,
    ProtectedCredentialBackend,
    RuntimeIdentityMetadata,
    WindowsCredentialManagerBackend,
)


def create_local_runtime_identity(
    project_root: Path,
    authority_id: str,
    *,
    backend: ProtectedCredentialBackend | None = None,
) -> tuple[GremlinRuntimeIdentityStore, RuntimeIdentityMetadata]:
    """Explicitly create an identity; importing or constructing this module does not.

    The returned store and metadata can be supplied to ``GremlinNanny``. The
    default backend is Windows Credential Manager and lifecycle records go to
    the canonical secret-free Gremlin audit ledger.
    """
    credential_backend = (
        backend if backend is not None else WindowsCredentialManagerBackend()
    )
    audit_sink = GremlinAuditLedger(project_root)
    store = GremlinRuntimeIdentityStore(
        credential_backend,
        audit_sink=audit_sink,
    )
    return store, store.create(authority_id)
