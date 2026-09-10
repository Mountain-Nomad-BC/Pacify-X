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


def _signature_input_image(path: Path, limit: int) -> bytes:
    from .input_files import independent_file, cooperative_deadline, read_file_image

    deadline = cooperative_deadline()
    checked, info = independent_file(path)
    return bytes(read_file_image(checked, info, limit=limit, deadline=deadline))


def _signing_snapshot(certificate: object) -> dict[str, Any]:
    from .json_io import bounded_json_text, decode_json_object, validate_json_value

    if type(certificate) is not dict:
        raise ValueError("certificate must be an actual object")
    validate_json_value(certificate, max_depth=64, max_nodes=100000)
    raw = bounded_json_text(certificate, max_bytes=8 * 1024 * 1024).encode("utf-8")
    return decode_json_object(
        raw, max_bytes=8 * 1024 * 1024, max_depth=64, max_nodes=100000
    )


def _trusted_signers(policy: dict[str, Any]) -> tuple[dict, set[str]]:
    import base64
    import re
    from .numeric_inputs import bounded_text

    records = policy.get("trusted_signers")
    revoked = policy.get("revoked_fingerprints", [])
    if type(records) is not list or not 1 <= len(records) <= 64:
        raise ValueError("trusted signers require 1..64 actual records")
    if type(revoked) is not list or len(revoked) > 512:
        raise ValueError("revoked fingerprints require a bounded actual list")
    fingerprint_pattern = r"SHA256:[A-Za-z0-9+/]{43}"
    trusted = {}
    for record in records:
        if type(record) is not dict or len(record) > 16:
            raise ValueError("trusted signer must be a bounded object")
        fingerprint = record.get("fingerprint")
        if (
            type(fingerprint) is not str
            or re.fullmatch(fingerprint_pattern, fingerprint) is None
        ):
            raise ValueError("trusted signer fingerprint is malformed")
        if fingerprint in trusted:
            raise ValueError("trusted signer fingerprints must be unique")
        identity = record.get("identity")
        if (
            type(identity) is not str
            or re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", identity) is None
        ):
            raise ValueError(
                "trusted signer identity must be a literal bounded principal"
            )
        bounded_text(
            record.get("publisher"), "trusted publisher", maximum=128, strip=False
        )
        key = bounded_text(
            record.get("public_key"), "trusted public key", maximum=1024, strip=False
        )
        if any(ord(c) < 32 or ord(c) == 127 for c in key):
            raise ValueError("trusted public key must occupy one line")
        parts = key.split(" ", 2)
        if len(parts) < 2 or parts[0] != "ssh-ed25519":
            raise ValueError("trusted public key must be Ed25519")
        blob = base64.b64decode(parts[1], validate=True)
        if len(blob) != 51 or not blob.startswith(b"\0\0\0\x0bssh-ed25519\0\0\0 "):
            raise ValueError("trusted Ed25519 public key encoding is malformed")
        actual = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode(
            "ascii"
        ).rstrip("=")
        if actual != fingerprint:
            raise ValueError("trusted fingerprint does not identify its public key")
        trusted[fingerprint] = record
    for fingerprint in revoked:
        if (
            type(fingerprint) is not str
            or re.fullmatch(fingerprint_pattern, fingerprint) is None
        ):
            raise ValueError("revoked fingerprint is malformed")
    if len(set(revoked)) != len(revoked):
        raise ValueError("revoked fingerprints must be unique")
    return trusted, set(revoked)


def verify_certificate_signature(
    certificate: dict[str, Any],
    *,
    signature_path: Path,
    trust_policy_path: Path,
) -> dict[str, Any]:
    from .archive_io import portable_member_name
    from .json_io import decode_json_object
    from .numeric_inputs import bounded_text

    errors: list[str] = []
    try:
        certificate = _signing_snapshot(certificate)
        signature = certificate.get("signature")
        if type(signature) is not dict:
            return {"valid": False, "errors": ["release certificate is unsigned"]}
        name = bounded_text(signature.get("path"), "signature filename", maximum=256, strip=False)
        if (
            type(name) is not str
            or len(name) > 256
            or "/" in portable_member_name(name, allow_directory=False)
        ):
            raise ValueError("signature path must be a portable filename")
        if type(signature_path) is not type(Path()) or signature_path.name != name:
            raise ValueError("signature input does not match its declared filename")
        policy = decode_json_object(
            _signature_input_image(trust_policy_path, 1024 * 1024),
            max_bytes=1024 * 1024,
            max_depth=64,
            max_nodes=100000,
        )
        trusted, revoked = _trusted_signers(policy)
        fingerprint = signature.get("key_fingerprint")
        if type(fingerprint) is not str or len(fingerprint) > 128:
            raise ValueError("certificate signing fingerprint is malformed")
        signer = trusted.get(fingerprint)
        if certificate.get("content_sha256") != content_digest(certificate):
            errors.append("certificate content_sha256 mismatch")
        if signer is None:
            errors.append("certificate signing identity is not trusted")
        if fingerprint in revoked:
            errors.append("certificate signing identity is revoked")
        if (
            signature.get("algorithm") != "ssh-ed25519"
            or signature.get("namespace") != SIGNING_NAMESPACE
        ):
            errors.append("certificate signature algorithm or namespace is invalid")
        if signer is not None and signature.get("publisher") != signer["publisher"]:
            errors.append(
                "certificate publisher identity does not match trusted signer"
            )
        if errors or signer is None:
            return {"valid": False, "fingerprint": fingerprint, "errors": errors}
        signature_image = _signature_input_image(signature_path, 65536)
        if not signature_image:
            raise ValueError("detached certificate signature is empty")
    except (OSError, ValueError, TypeError, RecursionError):
        return {
            "valid": False,
            "errors": ["release signature inputs are invalid or unavailable"],
        }
    identity = signer["identity"]
    allowed = f'{identity} namespaces="{SIGNING_NAMESPACE}" {signer["public_key"]}\n'
    try:
        with tempfile.TemporaryDirectory() as directory:
            allowed_path = Path(directory) / "allowed_signers"
            allowed_path.write_text(allowed, encoding="utf-8", newline="\n")
            checked_signature = Path(directory) / "certificate.sig"
            checked_signature.write_bytes(signature_image)
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
                    str(checked_signature),
                ],
                stdin=canonical_bytes(certificate),
            )
        if process.returncode:
            errors.append("detached certificate signature verification failed")
    except (OSError, ValueError, subprocess.SubprocessError):
        errors.append("detached certificate signature verification could not complete")
    return {
        "valid": not errors,
        "fingerprint": fingerprint,
        "identity": identity,
        "errors": errors,
    }
