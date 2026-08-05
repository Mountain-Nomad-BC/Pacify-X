"""Detached Ed25519/OpenSSH authentication for release certificates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .external_toolchain import require_openssh_authority


SIGNING_NAMESPACE = "pacify-x-release"


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def content_digest(certificate: dict[str, Any]) -> str:
    unsigned = dict(certificate)
    unsigned.pop("content_sha256", None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def bind_content_digest(certificate: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(certificate)
    unsigned.pop("content_sha256", None)
    return {
        **unsigned,
        "content_sha256": hashlib.sha256(canonical_bytes(unsigned)).hexdigest(),
    }


def _run(
    command: list[str], *, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command, input=stdin, capture_output=True, timeout=30, check=False
    )


def public_key_fingerprint(public_key: Path) -> str:
    process = _run(["ssh-keygen", "-lf", str(public_key), "-E", "sha256"])
    if process.returncode:
        raise ValueError(process.stderr.decode(errors="replace").strip())
    fields = process.stdout.decode().split()
    if len(fields) < 2:
        raise ValueError("ssh-keygen returned no public-key fingerprint")
    return fields[1]


def sign_certificate(
    certificate: dict[str, Any],
    *,
    private_key: Path,
    signature_path: Path,
) -> dict[str, Any]:
    require_openssh_authority()
    private_key = private_key.resolve(strict=True)
    public_key = Path(str(private_key) + ".pub")
    fingerprint = public_key_fingerprint(public_key)
    value = bind_content_digest(
        {
            **certificate,
            "signature": {
                "algorithm": "ssh-ed25519",
                "namespace": SIGNING_NAMESPACE,
                "publisher": "Mountain-Nomad-BC",
                "key_fingerprint": fingerprint,
                "path": signature_path.name,
            },
        }
    )
    signature_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        payload = Path(directory) / "certificate.canonical.json"
        payload.write_bytes(canonical_bytes(value))
        process = _run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(private_key),
                "-n",
                SIGNING_NAMESPACE,
                str(payload),
            ]
        )
        if process.returncode:
            raise ValueError(process.stderr.decode(errors="replace").strip())
        produced = Path(str(payload) + ".sig")
        signature_path.write_bytes(produced.read_bytes())
    return value


def verify_certificate_signature(
    certificate: dict[str, Any],
    *,
    signature_path: Path,
    trust_policy_path: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        policy = json.loads(trust_policy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "valid": False,
            "errors": [f"cannot load release trust policy: {error}"],
        }
    signature = certificate.get("signature")
    if not isinstance(signature, dict):
        return {"valid": False, "errors": ["release certificate is unsigned"]}
    expected_content = content_digest(certificate)
    if certificate.get("content_sha256") != expected_content:
        errors.append("certificate content_sha256 mismatch")
    trusted = {
        str(item.get("fingerprint")): item
        for item in policy.get("trusted_signers", ())
        if isinstance(item, dict)
    }
    fingerprint = str(signature.get("key_fingerprint", ""))
    signer = trusted.get(fingerprint)
    if signer is None:
        errors.append("certificate signing identity is not trusted")
    if fingerprint in set(map(str, policy.get("revoked_fingerprints", ()))):
        errors.append("certificate signing identity is revoked")
    if (
        signature.get("algorithm") != "ssh-ed25519"
        or signature.get("namespace") != SIGNING_NAMESPACE
    ):
        errors.append("certificate signature algorithm or namespace is invalid")
    if not signature_path.is_file():
        errors.append("detached certificate signature is missing")
    if errors or signer is None:
        return {"valid": False, "fingerprint": fingerprint, "errors": errors}
    public_key = str(signer.get("public_key", "")).strip()
    identity = str(signer.get("identity", ""))
    publisher = str(signer.get("publisher", ""))
    if not public_key or not identity:
        return {
            "valid": False,
            "fingerprint": fingerprint,
            "errors": ["trusted signer record is incomplete"],
        }
    if signature.get("publisher") != publisher:
        return {
            "valid": False,
            "fingerprint": fingerprint,
            "errors": ["certificate publisher identity does not match trusted signer"],
        }
    allowed = f'{identity} namespaces="{SIGNING_NAMESPACE}" {public_key}\n'
    with tempfile.TemporaryDirectory() as directory:
        allowed_path = Path(directory) / "allowed_signers"
        allowed_path.write_text(allowed, encoding="utf-8", newline="\n")
        process = _run(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(allowed_path),
                "-I",
                identity,
                "-n",
                SIGNING_NAMESPACE,
                "-s",
                str(signature_path),
            ],
            stdin=canonical_bytes(certificate),
        )
    if process.returncode:
        errors.append("detached certificate signature verification failed")
    return {
        "valid": not errors,
        "fingerprint": fingerprint,
        "identity": identity,
        "errors": errors,
    }
