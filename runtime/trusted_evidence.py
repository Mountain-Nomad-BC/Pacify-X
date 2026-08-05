"""Shared fail-closed resolution for signed, scoped evidence and policy records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping

from .release_signing import canonical_bytes, public_key_fingerprint
from .external_toolchain import require_openssh_authority

NAMESPACE = "pacify-x-trusted-evidence"
REFERENCE = re.compile(r"^evidence:([A-Za-z0-9._-]+)$")


@dataclass(frozen=True)
class EvidenceScope:
    project_id: str
    subject_id: str
    task_id: str = ""
    execution_id: str = ""
    actor_id: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class ResolvedEvidence:
    reference: str
    record: Mapping[str, Any] | None
    resolved: bool
    integrity_valid: bool
    signature_valid: bool
    fresh: bool
    scope_valid: bool
    producer_accepted: bool
    reasons: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return all(
            (
                self.resolved,
                self.integrity_valid,
                self.signature_valid,
                self.fresh,
                self.scope_valid,
                self.producer_accepted,
            )
        )


def _digest(record: Mapping[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop("content_sha256", None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def sign_evidence_record(
    record: Mapping[str, Any],
    *,
    private_key: Path,
    signature_path: Path,
    identity: str,
    publisher: str,
) -> dict[str, Any]:
    require_openssh_authority()
    public_key = Path(str(private_key.resolve(strict=True)) + ".pub")
    signed = {
        **record,
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
        payload = Path(directory) / "record.json"
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


def _verify_signature(
    record: Mapping[str, Any], signature_path: Path, trust_policy_path: Path
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        policy = json.loads(trust_policy_path.read_text(encoding="utf-8"))
        signature = record.get("signature")
        if not isinstance(signature, dict):
            return False, ["evidence_record_unsigned"]
        trusted = {
            str(item.get("fingerprint")): item
            for item in policy.get("trusted_signers", ())
            if isinstance(item, dict)
        }
        fingerprint = str(signature.get("key_fingerprint", ""))
        signer = trusted.get(fingerprint)
        if signer is None or fingerprint in set(
            map(str, policy.get("revoked_fingerprints", ()))
        ):
            return False, ["evidence_signer_untrusted"]
        if any(
            (
                signature.get("namespace") != NAMESPACE,
                signature.get("algorithm") != "ssh-ed25519",
                signature.get("identity") != signer.get("identity"),
                signature.get("publisher") != signer.get("publisher"),
            )
        ):
            return False, ["evidence_signer_metadata_mismatch"]
        if not signature_path.is_file():
            return False, ["evidence_signature_missing"]
        with tempfile.TemporaryDirectory() as directory:
            allowed = Path(directory) / "allowed_signers"
            allowed.write_text(
                f'{signer["identity"]} namespaces="{NAMESPACE}" {signer["public_key"]}\n',
                encoding="utf-8",
                newline="\n",
            )
            process = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed),
                    "-I",
                    str(signer["identity"]),
                    "-n",
                    NAMESPACE,
                    "-s",
                    str(signature_path),
                ],
                input=canonical_bytes(record),
                capture_output=True,
                timeout=30,
                check=False,
            )
        if process.returncode:
            errors.append("evidence_signature_invalid")
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ):
        errors.append("evidence_signature_verification_error")
    return not errors, errors


class TrustedEvidenceResolver:
    """Resolve only traversal-free IDs from one approved, signed evidence store."""

    def __init__(
        self, store: Path, trust_policy: Path, *, now: datetime | None = None
    ) -> None:
        self.store = store.resolve(strict=True)
        self.trust_policy = trust_policy.resolve(strict=True)
        self.now = now or datetime.now(timezone.utc)

    def resolve(
        self,
        reference: str,
        *,
        scope: EvidenceScope,
        accepted_producers: set[str],
        max_age_seconds: int | None = None,
        expected_sha256: str | None = None,
        required_type: str | None = None,
    ) -> ResolvedEvidence:
        reasons: list[str] = []
        match = REFERENCE.fullmatch(reference)
        if match is None:
            return ResolvedEvidence(
                reference,
                None,
                False,
                False,
                False,
                False,
                False,
                False,
                ("invalid_evidence_reference",),
            )
        record_path = (self.store / f"{match.group(1)}.json").resolve()
        if self.store not in record_path.parents or not record_path.is_file():
            return ResolvedEvidence(
                reference,
                None,
                False,
                False,
                False,
                False,
                False,
                False,
                ("evidence_missing",),
            )
        try:
            raw = record_path.read_bytes()
            record = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            return ResolvedEvidence(
                reference,
                None,
                False,
                False,
                False,
                False,
                False,
                False,
                ("evidence_unreadable",),
            )
        integrity_valid = record.get("content_sha256") == _digest(record)
        if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
            integrity_valid = False
            reasons.append("evidence_reference_hash_mismatch")
        artifact = record.get("artifact")
        if isinstance(artifact, dict):
            relative = Path(str(artifact.get("path", "")))
            artifact_path = (self.store / relative).resolve()
            if (
                relative.is_absolute()
                or self.store not in artifact_path.parents
                or not artifact_path.is_file()
            ):
                integrity_valid = False
                reasons.append("evidence_artifact_missing")
            elif hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact.get(
                "sha256"
            ):
                integrity_valid = False
                reasons.append("evidence_artifact_hash_mismatch")
        if not integrity_valid:
            reasons.append("evidence_integrity_failure")
        signature_valid, signature_errors = _verify_signature(
            record, record_path.with_suffix(".json.sig"), self.trust_policy
        )
        reasons.extend(signature_errors)
        producer_accepted = str(record.get("producer", "")) in accepted_producers
        if not producer_accepted:
            reasons.append("evidence_producer_unapproved")
        scope_valid = all(
            not expected or str(record.get(field, "")) == expected
            for field, expected in (
                ("project_id", scope.project_id),
                ("subject_id", scope.subject_id),
                ("task_id", scope.task_id),
                ("execution_id", scope.execution_id),
                ("actor_id", scope.actor_id),
                ("session_id", scope.session_id),
            )
        )
        if not scope_valid:
            reasons.append("evidence_scope_mismatch")
        if required_type and record.get("evidence_type") != required_type:
            scope_valid = False
            reasons.append("evidence_type_mismatch")
        fresh = True
        try:
            created = datetime.fromisoformat(str(record["created_at"]))
            if created.tzinfo is None:
                raise ValueError
            if (
                max_age_seconds is not None
                and (self.now - created).total_seconds() > max_age_seconds
            ):
                fresh = False
        except (KeyError, TypeError, ValueError):
            fresh = False
        if not fresh:
            reasons.append("evidence_stale")
        return ResolvedEvidence(
            reference,
            record,
            True,
            integrity_valid,
            signature_valid,
            fresh,
            scope_valid,
            producer_accepted,
            tuple(sorted(set(reasons))),
        )
