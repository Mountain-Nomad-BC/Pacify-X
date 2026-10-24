from __future__ import annotations

import argparse
from contextlib import contextmanager

import pytest

from runtime.gremlin.composition import compose_gremlin_runtime
from runtime.gremlin.recovery_authority import RecoveryChallenge, RecoveryApproval
from runtime.gremlin.runtime_identity import (
    GremlinRuntimeIdentityStore,
    RuntimeIdentityMetadata,
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


class FakeRecoveryVerifier:
    def verify(self, challenge: RecoveryChallenge, approval: RecoveryApproval) -> bool:
        return True


def _identity_store() -> tuple[GremlinRuntimeIdentityStore, RuntimeIdentityMetadata]:
    store = GremlinRuntimeIdentityStore(MemoryCredentialBackend(), audit_sink=lambda _event: None)
    return store, store.create("nanny")


def _verify_receipt(root, signed):
    from runtime.studio_authority import StudioAuthorityStore
    return StudioAuthorityStore(root).verify_receipt(signed)


def test_host_composition_binds_existing_identity_and_independent_recovery_owners(tmp_path) -> None:
    store, identity = _identity_store()
    composed = compose_gremlin_runtime(
        project_root=tmp_path,
        nanny_authority_id="nanny",
        recovery_authority_id="independent-recovery",
        identity_store=store,
        runtime_identity=identity,
        recovery_verifier=FakeRecoveryVerifier(),
    )

    assert composed.nanny.authority.authority_id == "nanny"
    assert composed.recovery_authority.authority_id == "independent-recovery"
    assert composed.replay_ledger.path.name == "recovery-replay"
    assert composed.audit_ledger.path.name == "lifecycle-audit"


def test_host_composition_rejects_recovery_authority_aliasing_nanny(tmp_path) -> None:
    store, identity = _identity_store()
    with pytest.raises(ValueError, match="must be independent"):
        compose_gremlin_runtime(
            project_root=tmp_path,
            nanny_authority_id="nanny",
            recovery_authority_id="nanny",
            identity_store=store,
            runtime_identity=identity,
            recovery_verifier=FakeRecoveryVerifier(),
        )


def test_cli_commission_writes_signed_host_configuration(tmp_path, monkeypatch) -> None:
    """The explicit commissioning CLI is the selected host commissioning entry.

    It creates the local identity through the canonical commissioning owner,
    writes the signed host configuration the host loader verifies, and never
    fabricates a recovery verifier.
    """
    import json as _json
    from contextlib import contextmanager

    from runtime.cli import _gremlin_command
    from runtime.gremlin.host_configuration import CONFIGURATION_RELATIVE

    class MemoryBackend:
        backend_id = "test-only-protected-store"

        def __init__(self) -> None:
            self.values = {}

        @contextmanager
        def transaction(self, target):
            yield

        def read(self, target):
            return self.values.get(target)

        def write(self, target, value):
            self.values[target] = value

        def delete(self, target):
            return self.values.pop(target, None) is not None

    backend = MemoryBackend()
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    root = tmp_path / "project"
    root.mkdir()
    result = _gremlin_command(
        argparse.Namespace(
            gremlin_action="commission",
            project=root,
            nanny_authority_id="local-nanny",
            recovery_authority_id="local-recovery",
        ),
        backend=backend,
    )
    assert result["schema_version"] == "px.gremlin-commissioning-result/1.0"
    assert result["recovery_verifier"] == "external-host-adapter-required"
    signed = _json.loads((root / CONFIGURATION_RELATIVE).read_text(encoding="utf-8"))
    verified = _verify_receipt(root, signed)
    assert verified["nanny_authority_id"] == "local-nanny"
    assert verified["recovery_authority_id"] == "local-recovery"
    assert verified["identity_id"] == result["identity_id"]
    # A second commission must refuse to overwrite the commissioned identity.
    try:
        _gremlin_command(
            argparse.Namespace(
                gremlin_action="commission",
                project=root,
                nanny_authority_id="local-nanny",
                recovery_authority_id="local-recovery",
            ),
            backend=MemoryBackend(),
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("recommissioning overwrote a commissioned identity")
