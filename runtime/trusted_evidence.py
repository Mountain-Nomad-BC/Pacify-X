"""Shared fail-closed resolution for signed, scoped evidence and policy records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping

from .release_signing import canonical_bytes, public_key_fingerprint
from .external_toolchain import require_openssh_authority

from .input_files import contained_file, directory_root, cooperative_deadline, read_file_image
from .json_io import decode_json_object
from .numeric_inputs import bounded_text
from .archive_io import portable_member_name

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


MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
EVIDENCE_RESULT_FLAGS = {
    "policy_decision": ("allowed",),
    "postcondition": (),
    "provenance": ("verified",),
    "license": ("reviewed", "allowed"),
    "tests": ("passed",),
    "security": ("malicious_or_unsafe",),
    "transfer_sanitization": ("accepted",),
    "human_approval": ("accepted",),
    "destination_ownership": ("accepted",),
    "transfer_tests": ("accepted",),
}
TRANSFER_EVIDENCE_TYPES = frozenset({
    "transfer_sanitization", "human_approval", "destination_ownership", "transfer_tests"
})


def _evidence_text(value: object, name: str, *, maximum: int = 256, optional: bool = False) -> str:
    from .numeric_inputs import bounded_text

    if optional and type(value) is str and value == "":
        return value
    return bounded_text(value, name, maximum=maximum, strip=False)


def _validate_evidence_result(value: object, evidence_type: str) -> dict:
    """An authenticated document still needs an explicit typed assessment."""
    from .numeric_inputs import bounded_mapping

    result = bounded_mapping(value, "evidence result", maximum=256)
    if type(evidence_type) is not str or evidence_type not in EVIDENCE_RESULT_FLAGS:
        raise ValueError("unsupported evidence result type")
    for field in EVIDENCE_RESULT_FLAGS[evidence_type]:
        if type(result.get(field)) is not bool:
            raise ValueError("evidence assessment flag must be an explicit boolean")
    if evidence_type == "postcondition":
        checks = bounded_mapping(result.get("postconditions"), "postconditions", maximum=256)
        if not checks:
            raise ValueError("postcondition assessment must contain checks")
        for name, passed in checks.items():
            _evidence_text(name, "postcondition name", maximum=128)
            if type(passed) is not bool:
                raise ValueError("postcondition result must be an actual boolean")
    if evidence_type == "policy_decision":
        if "approved_effects" in result:
            effects = result["approved_effects"]
            if type(effects) is not list or len(effects) > 32:
                raise ValueError("policy effects must be a bounded actual array")
            seen = set()
            for effect in effects:
                effect = _evidence_text(effect, "policy effect", maximum=128)
                if effect in seen:
                    raise ValueError("policy effects must be unique")
                seen.add(effect)
        if "approval_id" in result:
            _evidence_text(result["approval_id"], "approval identity", optional=True)
    return result


def _validate_evidence_record(record: object) -> dict:
    from .contracts import _valid_datetime
    from .input_files import relative_source_path
    from .numeric_inputs import bounded_json_value, bounded_mapping

    record = bounded_mapping(record, "trusted evidence record", maximum=20)
    bounded_json_value(record)
    required = {"schema_version", "evidence_id", "evidence_type", "producer", "project_id", "subject_id", "created_at", "result", "signature", "content_sha256"}
    optional = {"task_id", "execution_id", "actor_id", "session_id", "source_project_id", "destination_project_id", "artifact", "evaluation"}
    if required - record.keys() or record.keys() - required - optional:
        raise ValueError("trusted evidence record fields mismatch")
    if type(record["schema_version"]) is not str or record["schema_version"] not in {"1.0", "2.0"}:
        raise ValueError("unsupported trusted evidence schema")
    if record["schema_version"] == "2.0":
        validate_evaluation_binding(record.get("evaluation"))
    elif "evaluation" in record:
        raise ValueError("legacy evidence cannot carry a versioned evaluation binding")
    identity = _evidence_text(record["evidence_id"], "evidence identity", maximum=128)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identity) is None:
        raise ValueError("invalid evidence identity")
    for field in ["producer", "project_id", "subject_id"]:
        _evidence_text(record[field], field)
    for field in ["task_id", "execution_id", "actor_id", "session_id"]:
        if field in record:
            _evidence_text(record[field], field, optional=True)
    for field in ["source_project_id", "destination_project_id"]:
        if field in record:
            _evidence_text(record[field], field)
    created = _evidence_text(record["created_at"], "evidence timestamp", maximum=64)
    if not _valid_datetime(created):
        raise ValueError("evidence timestamp must be an aware RFC3339 value")
    _validate_evidence_result(record["result"], record["evidence_type"])
    if record["evidence_type"] in TRANSFER_EVIDENCE_TYPES and not {"source_project_id", "destination_project_id"} <= record.keys():
        raise ValueError("transfer evidence requires both project identities")
    digest = record["content_sha256"]
    if type(digest) is not str or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        raise ValueError("invalid evidence content digest")
    signature = bounded_mapping(record["signature"], "evidence signature", maximum=5)
    if set(signature) != {"algorithm", "namespace", "identity", "publisher", "key_fingerprint"}:
        raise ValueError("evidence signature fields mismatch")
    if signature["algorithm"] != "ssh-ed25519" or signature["namespace"] != NAMESPACE:
        raise ValueError("invalid evidence signing algorithm or namespace")
    principal = _evidence_text(signature["identity"], "signing principal", maximum=128)
    if re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", principal) is None:
        raise ValueError("invalid evidence signing principal")
    _evidence_text(signature["publisher"], "signing publisher", maximum=128)
    fingerprint = signature["key_fingerprint"]
    if type(fingerprint) is not str or re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint) is None:
        raise ValueError("invalid evidence signer fingerprint")
    if "artifact" in record:
        artifact = bounded_mapping(record["artifact"], "evidence artifact", maximum=2)
        if set(artifact) != {"path", "sha256"}:
            raise ValueError("evidence artifact fields mismatch")
        relative_source_path(artifact["path"])
        if type(artifact["sha256"]) is not str or re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"]) is None:
            raise ValueError("invalid evidence artifact digest")
    return record


def _producer_authorized(signer: dict, record: dict) -> bool:
    """A caller allowlist narrows a signing principal's explicit producer roles."""
    from .numeric_inputs import bounded_mapping

    if "evidence_producers" not in signer:
        return False
    grants = bounded_mapping(signer["evidence_producers"], "signer evidence producers", maximum=64)
    for producer, types in grants.items():
        _evidence_text(producer, "authorized producer")
        if type(types) is not list or not 1 <= len(types) <= len(EVIDENCE_RESULT_FLAGS):
            raise ValueError("producer evidence types must be a bounded actual array")
        if any(type(value) is not str or value not in EVIDENCE_RESULT_FLAGS for value in types):
            raise ValueError("unknown authorized evidence type")
        if len(set(types)) != len(types):
            raise ValueError("authorized evidence types must be unique")
    return record["evidence_type"] in grants.get(record["producer"], [])


def evidence_store_path(root: Path, relative: object) -> Path:
    """Preserve original path provenance before resolving a declared evidence store."""
    from .input_files import directory_root, relative_source_path

    root = directory_root(root)
    store = directory_root(root / relative_source_path(relative))
    if store == root or not store.is_relative_to(root):
        raise ValueError("evidence store must be a contained subdirectory")
    return store


def _evidence_failure(reference: str, reason: str) -> ResolvedEvidence:
    return ResolvedEvidence(reference, None, False, False, False, False, False, False, (reason,))


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
    from .json_io import decode_json_object
    from .release_signing import _signature_input_image, _trusted_signers

    try:
        policy = decode_json_object(
            _signature_input_image(trust_policy_path, MAX_EVIDENCE_BYTES),
            max_bytes=MAX_EVIDENCE_BYTES, max_depth=32, max_nodes=100000,
        )
        trusted, revoked = _trusted_signers(policy)
        signature = record["signature"]
        fingerprint = signature["key_fingerprint"]
        signer = trusted.get(fingerprint)
        if signer is None or fingerprint in revoked:
            return False, ["evidence_signer_untrusted"]
        if any((signature["namespace"] != NAMESPACE,
                signature["algorithm"] != "ssh-ed25519",
                signature["identity"] != signer["identity"],
                signature["publisher"] != signer["publisher"])):
            return False, ["evidence_signer_metadata_mismatch"]
        if not _producer_authorized(signer, record):
            return False, ["evidence_signer_producer_unapproved"]
        try:
            signature_image = _signature_input_image(signature_path, 64 * 1024)
        except FileNotFoundError:
            return False, ["evidence_signature_missing"]
        with tempfile.TemporaryDirectory() as directory:
            allowed = Path(directory) / "allowed_signers"
            captured_signature = Path(directory) / "record.sig"
            captured_signature.write_bytes(signature_image)
            allowed.write_text(
                f'{signer["identity"]} namespaces="{NAMESPACE}" {signer["public_key"]}\n',
                encoding="utf-8", newline="\n",
            )
            process = subprocess.run(
                ["ssh-keygen", "-Y", "verify", "-f", str(allowed),
                 "-I", signer["identity"], "-n", NAMESPACE, "-s", str(captured_signature)],
                input=canonical_bytes(record), capture_output=True, timeout=30, check=False,
            )
        return (False, ["evidence_signature_invalid"]) if process.returncode else (True, [])
    except (OSError, KeyError, TypeError, ValueError, OverflowError, subprocess.SubprocessError):
        return False, ["evidence_signature_verification_error"]


class TrustedEvidenceResolver:
    """Resolve only traversal-free IDs from one approved, signed evidence store."""

    def __init__(
        self, store: Path, trust_policy: Path, *, now: datetime | None = None
    ) -> None:
        from .input_files import directory_root, independent_file

        self.store = directory_root(store)
        self.trust_policy, _ = independent_file(trust_policy)
        if now is not None and (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("evidence evaluation clock must be aware")
        self.now = now

    def resolve(
        self,
        reference: str,
        *,
        scope: EvidenceScope,
        accepted_producers: set[str],
        max_age_seconds: int | None = None,
        expected_sha256: str | None = None,
        required_type: str | None = None,
        expected_evaluation: dict | None = None,
    ) -> ResolvedEvidence:
        from time import monotonic
        from .input_files import contained_file, read_file_image
        from .json_io import decode_json_object

        if type(reference) is not str or len(reference) > 137:
            return _evidence_failure("", "invalid_evidence_reference")
        match = REFERENCE.fullmatch(reference)
        if match is None or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", match.group(1)) is None:
            return _evidence_failure(reference, "invalid_evidence_reference")
        try:
            if expected_evaluation is not None:
                expected_evaluation = validate_evaluation_binding(expected_evaluation)
            if not isinstance(scope, EvidenceScope):
                raise ValueError("invalid scope")
            for field in ("project_id", "subject_id", "task_id", "execution_id", "actor_id", "session_id"):
                _evidence_text(getattr(scope, field), field, optional=field not in {"project_id", "subject_id"})
            if type(accepted_producers) is not set or not 1 <= len(accepted_producers) <= 64:
                raise ValueError("invalid producer allowlist")
            for producer in accepted_producers:
                _evidence_text(producer, "accepted producer")
            if max_age_seconds is not None and (type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 31536000):
                raise ValueError("invalid evidence age budget")
            if expected_sha256 is not None and (type(expected_sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None):
                raise ValueError("invalid expected evidence digest")
            if required_type is not None and (type(required_type) is not str or required_type not in EVIDENCE_RESULT_FLAGS):
                raise ValueError("invalid required evidence type")
        except (TypeError, ValueError):
            return _evidence_failure(reference, "invalid_evidence_request")
        deadline = monotonic() + 60
        try:
            record_path, info = contained_file(self.store, match.group(1) + ".json")
            raw = read_file_image(record_path, info, limit=MAX_EVIDENCE_BYTES, deadline=deadline)
            record = _validate_evidence_record(decode_json_object(
                raw, max_bytes=MAX_EVIDENCE_BYTES, max_depth=32, max_nodes=100000,
            ))
        except FileNotFoundError:
            return _evidence_failure(reference, "evidence_missing")
        except (OSError, TypeError, ValueError, OverflowError):
            return _evidence_failure(reference, "evidence_record_invalid")
        if record["evidence_id"] != match.group(1):
            return _evidence_failure(reference, "evidence_identity_mismatch")
        reasons = []
        integrity_valid = record["content_sha256"] == _digest(record)
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
            integrity_valid = False
            reasons.append("evidence_reference_hash_mismatch")
        signature_valid = False
        if integrity_valid:
            signature_valid, signature_errors = _verify_signature(
                record, record_path.with_suffix(".json.sig"), self.trust_policy,
            )
            reasons.extend(signature_errors)
        producer_accepted = record["producer"] in accepted_producers
        if not producer_accepted:
            reasons.append("evidence_producer_unapproved")
        scope_valid = all(
            not expected or record.get(field, "") == expected
            for field, expected in (
                ("project_id", scope.project_id), ("subject_id", scope.subject_id),
                ("task_id", scope.task_id), ("execution_id", scope.execution_id),
                ("actor_id", scope.actor_id), ("session_id", scope.session_id),
            )
        )
        if not scope_valid:
            reasons.append("evidence_scope_mismatch")
        if required_type is not None and record["evidence_type"] != required_type:
            scope_valid = False
            reasons.append("evidence_type_mismatch")
        if expected_evaluation is not None and (record["schema_version"] != "2.0" or record.get("evaluation") != expected_evaluation):
            scope_valid = False
            reasons.append("evidence_evaluation_mismatch")
        fresh = True
        try:
            created = datetime.fromisoformat(record["created_at"])
            current = self.now if self.now is not None else datetime.now(timezone.utc)
            age = (current - created).total_seconds()
            if age < 0 or max_age_seconds is not None and age > max_age_seconds:
                fresh = False
        except (TypeError, ValueError):
            fresh = False
        if not fresh:
            reasons.append("evidence_stale")
        # Evidence-directed content is acquired only after authentication and applicability.
        if signature_valid and producer_accepted and scope_valid and fresh and "artifact" in record:
            try:
                artifact = record["artifact"]
                artifact_path, info = contained_file(self.store, artifact["path"])
                artifact_image = read_file_image(artifact_path, info, limit=MAX_ARTIFACT_BYTES, deadline=deadline)
                if hashlib.sha256(artifact_image).hexdigest() != artifact["sha256"]:
                    integrity_valid = False
                    reasons.append("evidence_artifact_hash_mismatch")
            except (OSError, TypeError, ValueError, OverflowError):
                integrity_valid = False
                reasons.append("evidence_artifact_invalid")
        if not integrity_valid:
            reasons.append("evidence_integrity_failure")
        return ResolvedEvidence(reference, record, True, integrity_valid, signature_valid,
                                fresh, scope_valid, producer_accepted, tuple(sorted(set(reasons))))




INTERPRETATIONS = {
    'outcome-postconditions/1': 'artifact-file',
    'candidate-assessments/1': 'candidate-manifest',
}


def load_evidence_request_file(path):
    """Acquire an explicitly supplied CLI input without granting subject authority."""
    from .input_files import independent_file
    source, info = independent_file(path)
    raw = read_file_image(source, info, limit=1024 * 1024, deadline=cooperative_deadline())
    return decode_json_object(raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000)


def _locator(value):
    value = bounded_text(value, 'evaluation locator', maximum=4096, strip=False)
    normalized = portable_member_name(value, allow_directory=False)
    if normalized != value:
        raise ValueError('evaluation locator must use canonical relative spelling')
    return value


def validate_evaluation_binding(value):
    if type(value) is not dict or set(value) != {'contract', 'subject'}:
        raise ValueError('evaluation binding must contain contract and subject')
    contract, subject = value['contract'], value['subject']
    if type(contract) is not dict or set(contract) != {'path', 'sha256', 'size_bytes', 'interpretation'}:
        raise ValueError('evaluation contract binding is invalid')
    if type(subject) is not dict or set(subject) != {'path', 'kind', 'sha256', 'size_bytes'}:
        raise ValueError('evaluation subject binding is invalid')
    interpretation = contract['interpretation']
    if type(interpretation) is not str or interpretation not in INTERPRETATIONS:
        raise ValueError('evaluation interpretation is unsupported')
    if type(subject['kind']) is not str or subject['kind'] != INTERPRETATIONS[interpretation]:
        raise ValueError('evaluation subject kind disagrees with interpretation')
    for record, limit in ((contract, 1024 * 1024), (subject, 64 * 1024 * 1024)):
        _locator(record['path'])
        digest = record['sha256']
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('evaluation image digest is invalid')
        size = record['size_bytes']
        if type(size) is not int or not 0 <= size <= limit:
            raise ValueError('evaluation image size is invalid')
    return {'contract': dict(contract), 'subject': dict(subject)}


def acquire_evaluation_binding(root, *, subject_source, assessment_contract, interpretation):
    if type(interpretation) is not str or interpretation not in INTERPRETATIONS:
        raise ValueError('evaluation interpretation is unsupported')
    root = directory_root(root)
    subject_name, contract_name = _locator(subject_source), _locator(assessment_contract)
    deadline = cooperative_deadline()
    subject_path, subject_info = contained_file(root, subject_name)
    contract_path, contract_info = contained_file(root, contract_name)
    subject_limit = 1024 * 1024 if interpretation == 'candidate-assessments/1' else 64 * 1024 * 1024
    if subject_info.st_size > subject_limit or contract_info.st_size > 1024 * 1024:
        raise ValueError('evaluation input image budget exhausted')
    subject_raw = read_file_image(subject_path, subject_info, limit=subject_limit, deadline=deadline)
    contract_raw = read_file_image(contract_path, contract_info, limit=1024 * 1024, deadline=deadline)
    binding = validate_evaluation_binding({
        'subject': {'path': subject_name, 'kind': INTERPRETATIONS[interpretation],
                    'sha256': hashlib.sha256(subject_raw).hexdigest(), 'size_bytes': len(subject_raw)},
        'contract': {'path': contract_name, 'interpretation': interpretation,
                     'sha256': hashlib.sha256(contract_raw).hexdigest(), 'size_bytes': len(contract_raw)},
    })
    contract = decode_json_object(contract_raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000)
    subject = None
    if interpretation == 'candidate-assessments/1':
        subject = decode_json_object(subject_raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000)
    return binding, contract, subject
