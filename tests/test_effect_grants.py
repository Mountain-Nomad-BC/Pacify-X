from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile

from runtime.effect_grants import sign_effect_grant, validate_effect_grant
from runtime.execution_contract import ExecutionRequest, PolicyDecision, enforce
from runtime.release_signing import public_key_fingerprint


def _fixture(root: Path, *, effects=("write_workspace",), expires_minutes=10, destructive=False):
    key = root / "operator_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "operator@test", "-f", str(key)], check=True, timeout=30)
    public = Path(str(key) + ".pub").read_text().split()
    fingerprint = public_key_fingerprint(Path(str(key) + ".pub"))
    policy = root / "trust.json"
    policy.write_text(json.dumps({"trusted_signers": [{"identity": "operator@test", "publisher": "test", "fingerprint": fingerprint, "public_key": " ".join(public[:2])}], "revoked_fingerprints": []}), encoding="utf-8")
    now = datetime.now(timezone.utc)
    base = {
        "schema_version": "1.0", "grant_id": "grant-1", "capability_id": "writer",
        "declared_effects": list(effects), "approved_adapter": "sandbox", "approved_environment": "test",
        "project_id": "prj_one", "session_id": "session_one", "writable_roots": [str(root / "project")],
        "network_policy": {"mode": "deny", "allow_hosts": []}, "secret_access_policy": {"mode": "deny", "allow_refs": []},
        "destructive_operation_policy": {"approved": destructive, "approval_id": "approval-delete" if destructive else None},
        "approval_identity": "operator@test", "issued_utc": now.isoformat(), "expires_utc": (now + timedelta(minutes=expires_minutes)).isoformat(),
        "nonce": "nonce-1", "idempotency_key": "effect-1", "publisher": "test",
    }
    signature = root / "grant.sig"; grant = sign_effect_grant(base, private_key=key, signature_path=signature, identity="operator@test", publisher="test")
    grant_path = root / "grant.json"; grant_path.write_text(json.dumps(grant), encoding="utf-8")
    return grant, grant_path, signature, policy


def test_restricted_admission_requires_enforced_runtime_grant() -> None:
    request = ExecutionRequest("writer", ("write_workspace",), 10, 1, "effect-1")
    decision = enforce(request, PolicyDecision(True, ("write_workspace",), "approval"), {"id": "writer", "status": "admitted", "effects": ["write_workspace"]})
    assert not decision.approved and any("runtime effect grant" in reason for reason in decision.reasons)


def test_network_effect_fails_without_network_grant() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); grant, _, signature, policy = _fixture(root, effects=("network",))
        result = validate_effect_grant(grant, signature_path=signature, trust_policy_path=policy, capability_id="writer", requested_effects=("network",), adapter="sandbox", environment="test", project_id="prj_one", session_id="session_one", network_hosts=("example.com",))
        assert not result["valid"] and "network effect exceeds grant policy" in result["errors"]


def test_destructive_effect_fails_without_approval() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); grant, _, signature, policy = _fixture(root, effects=("destructive",))
        result = validate_effect_grant(grant, signature_path=signature, trust_policy_path=policy, capability_id="writer", requested_effects=("destructive",), adapter="sandbox", environment="test", project_id="prj_one", session_id="session_one", destructive=True)
        assert not result["valid"] and "destructive effect lacks explicit approval" in result["errors"]


def test_effect_grant_is_bound_to_project_and_session() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); grant, _, signature, policy = _fixture(root)
        result = validate_effect_grant(grant, signature_path=signature, trust_policy_path=policy, capability_id="writer", requested_effects=("write_workspace",), adapter="sandbox", environment="test", project_id="prj_other", session_id="session_other")
        assert not result["valid"] and "effect grant project or session binding mismatch" in result["errors"]


def test_expired_effect_grant_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); grant, _, signature, policy = _fixture(root)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        result = validate_effect_grant(grant, signature_path=signature, trust_policy_path=policy, capability_id="writer", requested_effects=("write_workspace",), adapter="sandbox", environment="test", project_id="prj_one", session_id="session_one", now=future)
        assert not result["valid"] and "effect grant is expired or has invalid time bounds" in result["errors"]
