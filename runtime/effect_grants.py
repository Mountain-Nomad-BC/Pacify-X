"""Cryptographically validate runtime effect grants before adapter execution."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Iterable

from .release_signing import canonical_bytes, public_key_fingerprint
from .external_toolchain import require_openssh_authority


NAMESPACE = "pacify-x-effect-grant"
REQUIRED = {
    "schema_version",
    "grant_id",
    "capability_id",
    "declared_effects",
    "approved_adapter",
    "approved_environment",
    "project_id",
    "session_id",
    "writable_roots",
    "network_policy",
    "secret_access_policy",
    "destructive_operation_policy",
    "approval_identity",
    "issued_utc",
    "expires_utc",
    "nonce",
    "idempotency_key",
    "publisher",
    "signature",
    "content_sha256",
}


def _digest(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("content_sha256", None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def sign_effect_grant(
    grant: dict[str, Any],
    *,
    private_key: Path,
    signature_path: Path,
    identity: str,
    publisher: str,
) -> dict[str, Any]:
    require_openssh_authority()
    private_key = private_key.resolve(strict=True)
    public_key = Path(str(private_key) + ".pub")
    signed = {
        **grant,
        "signature": {
            "algorithm": "ssh-ed25519",
            "namespace": NAMESPACE,
            "identity": identity,
            "publisher": publisher,
            "key_fingerprint": public_key_fingerprint(public_key),
        },
    }
    signed["content_sha256"] = _digest(signed)
    signature_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        payload = Path(directory) / "grant.json"
        payload.write_bytes(canonical_bytes(signed))
        process = subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(private_key),
                "-n",
                NAMESPACE,
                str(payload),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if process.returncode:
            raise ValueError(process.stderr.decode(errors="replace"))
        signature_path.write_bytes(Path(str(payload) + ".sig").read_bytes())
    return signed


def validate_effect_grant(
    grant: dict[str, Any],
    *,
    signature_path: Path,
    trust_policy_path: Path,
    capability_id: str,
    requested_effects: Iterable[str],
    adapter: str,
    environment: str,
    project_id: str,
    session_id: str,
    writable_targets: Iterable[Path] = (),
    network_hosts: Iterable[str] = (),
    secret_refs: Iterable[str] = (),
    destructive: bool = False,
    now: datetime | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if set(grant) != REQUIRED:
        errors.append("effect grant fields are not exact")
    if grant.get("schema_version") != "1.0" or grant.get("content_sha256") != _digest(
        grant
    ):
        errors.append("effect grant content digest mismatch")
    try:
        policy = json.loads(trust_policy_path.read_text(encoding="utf-8"))
        signature = grant["signature"]
        trusted = {
            item["fingerprint"]: item for item in policy.get("trusted_signers", [])
        }
        signer = trusted.get(signature.get("key_fingerprint"))
        if signer is None or signature.get("key_fingerprint") in policy.get(
            "revoked_fingerprints", []
        ):
            errors.append("effect grant signer is not trusted")
        elif (
            signature.get("namespace") != NAMESPACE
            or signature.get("algorithm") != "ssh-ed25519"
            or signature.get("identity") != signer.get("identity")
            or signature.get("publisher") != signer.get("publisher")
        ):
            errors.append("effect grant signer metadata mismatch")
        elif not signature_path.is_file():
            errors.append("effect grant detached signature is missing")
        else:
            with tempfile.TemporaryDirectory() as directory:
                allowed = Path(directory) / "allowed_signers"
                allowed.write_text(
                    f'{signer["identity"]} namespaces="{NAMESPACE}" {signer["public_key"]}\n',
                    encoding="utf-8",
                )
                verification = subprocess.run(
                    [
                        "ssh-keygen",
                        "-Y",
                        "verify",
                        "-f",
                        str(allowed),
                        "-I",
                        signer["identity"],
                        "-n",
                        NAMESPACE,
                        "-s",
                        str(signature_path),
                    ],
                    input=canonical_bytes(grant),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if verification.returncode:
                    errors.append("effect grant signature verification failed")
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        errors.append(
            f"effect grant trust validation failed: {type(error).__name__}: {error}"
        )
    requested = set(map(str, requested_effects))
    declared = set(map(str, grant.get("declared_effects", ())))
    if grant.get("capability_id") != capability_id or not requested <= declared:
        errors.append("effect grant does not cover capability or requested effects")
    if (
        grant.get("approved_adapter") != adapter
        or grant.get("approved_environment") != environment
    ):
        errors.append("effect grant adapter or environment binding mismatch")
    if grant.get("project_id") != project_id or grant.get("session_id") != session_id:
        errors.append("effect grant project or session binding mismatch")
    try:
        issued = datetime.fromisoformat(str(grant["issued_utc"]))
        expiry = datetime.fromisoformat(str(grant["expires_utc"]))
        current = now or datetime.now(timezone.utc)
        if (
            issued.tzinfo is None
            or expiry.tzinfo is None
            or expiry <= issued
            or current >= expiry
        ):
            errors.append("effect grant is expired or has invalid time bounds")
    except (KeyError, TypeError, ValueError):
        errors.append("effect grant time bounds are invalid")
    if not all(
        str(grant.get(field, "")).strip()
        for field in ("grant_id", "approval_identity", "nonce", "idempotency_key")
    ):
        errors.append("effect grant identity, nonce, or idempotency key is missing")
    if idempotency_key is not None and grant.get("idempotency_key") != idempotency_key:
        errors.append("effect grant idempotency key mismatch")
    roots = [Path(value).resolve() for value in grant.get("writable_roots", ())]
    for target in writable_targets:
        resolved = target.resolve()
        if not any(resolved == root or root in resolved.parents for root in roots):
            errors.append(f"write target is outside effect grant roots: {target}")
    network = grant.get("network_policy", {})
    allowed_hosts = (
        set(map(str, network.get("allow_hosts", ())))
        if isinstance(network, dict)
        else set()
    )
    if network_hosts and (
        not isinstance(network, dict)
        or network.get("mode") != "allowlist"
        or not set(map(str, network_hosts)) <= allowed_hosts
    ):
        errors.append("network effect exceeds grant policy")
    secret_policy = grant.get("secret_access_policy", {})
    if secret_refs and (
        not isinstance(secret_policy, dict)
        or secret_policy.get("mode") != "allowlist"
        or not set(map(str, secret_refs))
        <= set(map(str, secret_policy.get("allow_refs", ())))
    ):
        errors.append("secret access exceeds grant policy")
    destructive_policy = grant.get("destructive_operation_policy", {})
    if destructive and (
        not isinstance(destructive_policy, dict)
        or destructive_policy.get("approved") is not True
        or not destructive_policy.get("approval_id")
    ):
        errors.append("destructive effect lacks explicit approval")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "grant_id": grant.get("grant_id"),
        "errors": errors,
    }
