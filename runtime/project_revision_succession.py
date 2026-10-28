# Fail-closed validation primitives for proposed project-revision succession.
# This module never grants owner authority, publishes state, or activates revisions.
from __future__ import annotations
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Mapping
from .file_lock import FileLock
from .wal_transaction import BytesArtifact, JsonArtifact, JsonWal
from . import release_signing
SCHEMA = "px.project-revision-succession-proposal/1.0"
EVENT_SCHEMA = "px.project-revision-succession-event/1.0"
STATE_SCHEMA = "px.project-revision-succession-state/1.0"
AUTH_SCHEMA = "px.project-revision-succession-authorization/1.0"
POLICY_SCHEMA = "px.project-revision-succession-policy/1.0"
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
AUTH_NAMESPACE = "pacify-x-project-revision-succession"
AUTH_TRUST_POLICY = Path("policies/effect-grant-trust.json")
OWNER_AUTH_KEYS = {
    "schema_version", "authorization_id", "decision", "successor_project_id",
    "successor_campaign_id", "predecessor_campaign_id", "predecessor_raw_sha256",
    "source_tree_sha256", "owner_policy_id", "issued_at", "expires_at", "issuer",
    "signature", "content_sha256", "validation_policy", "effect_boundary",
    "intake_findings", "revocation_status", "replay_status",
    "source_identity", "revoked", "predecessor_project_record_sha256",
    "predecessor_validation_policy_sha256",
}
OWNER_AUTH_OPTIONAL_KEYS = {"predecessor_campaign_state_sha256"}

class SuccessionProposalBlocked(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or ID_PATTERN.fullmatch(value) is None:
        raise SuccessionProposalBlocked(f"{field} must be a bounded stable identifier")
    return value

def _sha256(value: object, field: str) -> str:
    if type(value) is not str or SHA256_PATTERN.fullmatch(value) is None:
        raise SuccessionProposalBlocked(f"{field} must be a lowercase SHA-256 digest")
    return value

def _timestamp(value: object, field: str) -> datetime:
    if type(value) is not str:
        raise SuccessionProposalBlocked(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SuccessionProposalBlocked(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise SuccessionProposalBlocked(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_owner_policy(policy: object) -> dict[str, Any]:
    # Validate the narrow successor-authority policy envelope.
    required = {
        "schema_version", "policy_id", "status", "authorization_schema",
        "trusted_authorities", "revoked_authorizations", "revision_scope",
    }
    if (type(policy) is not dict or not required.issubset(policy)
            or set(policy) - required - {"revocation_registry"}):
        raise SuccessionProposalBlocked("successor owner policy fields are not exact")
    if (
        policy.get("schema_version") != POLICY_SCHEMA
        or policy.get("status") != "active"
        or policy.get("authorization_schema") != AUTH_SCHEMA
        or not isinstance(policy.get("revision_scope"), list)
        or not policy["revision_scope"]
    ):
        raise SuccessionProposalBlocked("successor owner policy is inactive or malformed")
    _identifier(policy.get("policy_id"), "policy_id")
    scope = policy.get("revision_scope")
    if type(scope) is not list or not 1 <= len(scope) <= 32 or any(type(item) is not str or not item.strip() for item in scope) or len(scope) != len(set(scope)):
        raise SuccessionProposalBlocked("owner policy revision scope is malformed")
    authorities = policy.get("trusted_authorities")
    revoked = policy.get("revoked_authorizations")
    if type(authorities) is not list or not 1 <= len(authorities) <= 32:
        raise SuccessionProposalBlocked("owner policy requires bounded trusted authorities")
    if type(revoked) is not list or len(revoked) > 10000:
        raise SuccessionProposalBlocked("owner policy revocation list is malformed")
    seen: set[str] = set()
    for row in authorities:
        if type(row) is not dict or set(row) != {"identity", "fingerprint", "public_key", "publisher", "status"}:
            raise SuccessionProposalBlocked("trusted owner authority record is malformed")
        identity = _identifier(row.get("identity"), "authority identity")
        if row.get("status") != "active" or identity in seen:
            raise SuccessionProposalBlocked("trusted owner authority is duplicate or inactive")
        seen.add(identity)
        fingerprint = row.get("fingerprint")
        public_key = row.get("public_key")
        if type(fingerprint) is not str or re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint) is None:
            raise SuccessionProposalBlocked("trusted owner fingerprint is malformed")
        if type(public_key) is not str or not public_key.startswith("ssh-ed25519 ") or "\n" in public_key:
            raise SuccessionProposalBlocked("trusted owner key must be one-line Ed25519")
        try:
            key_blob = base64.b64decode(public_key.split()[1], validate=True)
            actual_fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii").rstrip("=")
        except (IndexError, ValueError) as error:
            raise SuccessionProposalBlocked("trusted owner public key encoding is malformed") from error
        if actual_fingerprint != fingerprint:
            raise SuccessionProposalBlocked("trusted owner fingerprint does not match public key")
        if type(row.get("publisher")) is not str or not row["publisher"].strip():
            raise SuccessionProposalBlocked("trusted owner publisher is required")
    if any(type(item) is not str or not item.strip() for item in revoked):
        raise SuccessionProposalBlocked("owner authorization revocations must be identifiers")
    if "revocation_registry" in policy:
        registry = policy["revocation_registry"]
        if (type(registry) is not dict
                or set(registry) != {"schema_version", "checked_at", "revoked", "superseded"}
                or registry.get("schema_version") != "px.authorization-revocation-registry/1.0"
                or type(registry.get("revoked")) is not list
                or len(registry["revoked"]) > 10000
                or any(type(item) is not str or not item.strip() for item in registry["revoked"])
                or len(registry["revoked"]) != len(set(registry["revoked"]))
                or type(registry.get("superseded")) is not dict
                or len(registry["superseded"]) > 10000
                or any(type(k) is not str or not k.strip() or type(v) is not str or not v.strip()
                       for k, v in registry["superseded"].items())):
            raise SuccessionProposalBlocked("owner authorization revocation registry is malformed")
        _timestamp(registry["checked_at"], "revocation registry checked_at")
    return policy

def verify_owner_policy_evidence(
    policy: Mapping[str, Any], *, policy_path: Path, evidence_reference: str,
    evidence_store: Path, trust_policy_path: Path, project_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    # Resolve policy provenance through PX's signed trusted-evidence owner.
    from .trusted_evidence import EvidenceScope, TrustedEvidenceResolver
    validated = validate_owner_policy(dict(policy))
    policy_path = Path(policy_path).resolve(strict=True)
    store = Path(evidence_store).resolve(strict=True)
    try:
        relative = policy_path.relative_to(store).as_posix()
    except ValueError as error:
        raise SuccessionProposalBlocked("owner policy must be contained by its signed evidence store") from error
    expected = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    resolver = TrustedEvidenceResolver(store, Path(trust_policy_path), now=now)
    evidence = resolver.resolve(
        evidence_reference,
        scope=EvidenceScope(project_id=project_id, subject_id=validated["policy_id"]),
        accepted_producers={"project-revision-succession-policy"},
        expected_sha256=None,
        required_type="provenance",
    )
    record = evidence.record
    artifact = record.get("artifact") if isinstance(record, Mapping) else None
    if not evidence.verified or not isinstance(artifact, Mapping) or artifact.get("path") != relative or artifact.get("sha256") != expected:
        raise SuccessionProposalBlocked("owner policy is not bound to verified signed provenance evidence")
    return {"valid": True, "policy_id": validated["policy_id"], "evidence_reference": evidence_reference,
            "policy_sha256": expected, "signer": record["signature"]["identity"]}


def verify_owner_authorization(
    authorization: Mapping[str, Any], *, policy_path: Path, signature_path: Path,
    policy_evidence_reference: str,
    evidence_store: Path,
    evidence_trust_policy_path: Path,
    project_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    # Verify policy provenance first, then the bound authorization signature.
    from .release_signing import canonical_bytes
    try:
        policy = validate_owner_policy(json.loads(policy_path.read_text(encoding="utf-8")))
        policy_provenance = verify_owner_policy_evidence(
            policy, policy_path=policy_path, evidence_reference=policy_evidence_reference,
            evidence_store=evidence_store, trust_policy_path=evidence_trust_policy_path,
            project_id=project_id, now=now,
        )
        if (type(authorization) is not dict or not OWNER_AUTH_KEYS.issubset(authorization)
                or set(authorization) - OWNER_AUTH_KEYS - OWNER_AUTH_OPTIONAL_KEYS):
            raise SuccessionProposalBlocked("owner authorization fields are not exact")
        if authorization["schema_version"] != AUTH_SCHEMA or authorization["owner_policy_id"] != policy["policy_id"]:
            raise SuccessionProposalBlocked("owner authorization policy binding differs")
        if authorization.get("effect_boundary") != {"local_revision_activation": True, "production_activation": False, "package": False, "install": False, "publication": False}:
            raise SuccessionProposalBlocked("owner authorization effect boundary is missing or excessive")
        if authorization.get("revocation_status") != "not_revoked":
            raise SuccessionProposalBlocked("owner authorization revocation status is not explicitly current")
        if type(authorization.get("intake_findings")) is not list or not authorization["intake_findings"] or any(type(item) is not str or not item.strip() for item in authorization["intake_findings"]):
            raise SuccessionProposalBlocked("owner authorization must bind a non-empty intake denominator")
        validation_policy = authorization.get("validation_policy")
        if authorization.get("decision") != "approved" or not isinstance(validation_policy, dict) or validation_policy.get("campaign_id") != authorization.get("successor_campaign_id"):
            raise SuccessionProposalBlocked("owner authorization decision or successor validation policy is invalid")
        if validation_policy.get("authority") != "OWNER-FRESH-VALIDATION-001":
            raise SuccessionProposalBlocked("owner authorization lacks explicit fresh-validation policy")
        _sha256(authorization.get("predecessor_raw_sha256"), "predecessor_raw_sha256")
        _sha256(authorization.get("source_tree_sha256"), "source_tree_sha256")
        for field in ("predecessor_project_record_sha256", "predecessor_validation_policy_sha256"):
            _sha256(authorization.get(field), field)
        if "predecessor_campaign_state_sha256" in authorization:
            _sha256(authorization["predecessor_campaign_state_sha256"], "predecessor_campaign_state_sha256")
        if authorization.get("revoked") is not False:
            raise SuccessionProposalBlocked("owner authorization is revoked or lacks explicit non-revocation")
        source_identity = authorization.get("source_identity")
        if (type(source_identity) is not dict or set(source_identity) != {"kind", "source_sha256"}
                or source_identity.get("kind") not in {"git_tree", "source_tree", "release_source"}
                or source_identity.get("source_sha256") != authorization["source_tree_sha256"]):
            raise SuccessionProposalBlocked("owner authorization source identity binding is invalid")
        _identifier(authorization.get("successor_project_id"), "successor_project_id")
        _identifier(authorization.get("successor_campaign_id"), "successor_campaign_id")
        _identifier(authorization.get("predecessor_campaign_id"), "predecessor_campaign_id")
        auth_id = _identifier(authorization.get("authorization_id"), "authorization_id")
        if auth_id in policy["revoked_authorizations"]:
            raise SuccessionProposalBlocked("owner authorization is revoked")
        signer = authorization.get("issuer")
        if type(signer) is not str or signer not in {row["identity"] for row in policy["trusted_authorities"]}:
            raise SuccessionProposalBlocked("owner authorization issuer is not trusted")
        authority = next(row for row in policy["trusted_authorities"] if row["identity"] == signer)
        unsigned = {key: value for key, value in authorization.items() if key not in {"signature", "content_sha256"}}
        expected_digest = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
        if authorization.get("content_sha256") != expected_digest:
            raise SuccessionProposalBlocked("owner authorization content digest mismatch")
        signature = authorization.get("signature")
        if type(signature) is not dict or set(signature) != {"algorithm", "namespace", "identity", "fingerprint"}:
            raise SuccessionProposalBlocked("owner authorization signature metadata is malformed")
        if (signature["algorithm"] != "ssh-ed25519" or signature["namespace"] != AUTH_NAMESPACE
                or signature["identity"] != signer or signature["fingerprint"] != authority["fingerprint"]):
            raise SuccessionProposalBlocked("owner authorization signature identity mismatch")
        revocation_registry = policy.get("revocation_registry")
        if type(revocation_registry) is not dict or set(revocation_registry) != {"schema_version", "checked_at", "revoked", "superseded"}:
            raise SuccessionProposalBlocked("owner authorization revocation registry is missing or malformed")
        if revocation_registry.get("schema_version") != "px.authorization-revocation-registry/1.0":
            raise SuccessionProposalBlocked("owner authorization revocation registry schema is unsupported")
        if type(revocation_registry.get("revoked")) is not list or type(revocation_registry.get("superseded")) is not dict:
            raise SuccessionProposalBlocked("owner authorization revocation registry entries are invalid")
        if auth_id in revocation_registry["revoked"]:
            raise SuccessionProposalBlocked("owner authorization is revoked")
        if auth_id in revocation_registry["superseded"]:
            raise SuccessionProposalBlocked("owner authorization is superseded")
        if not signature_path.is_file():
            raise SuccessionProposalBlocked("owner authorization detached signature is missing")
        allowed_record = f'{authority["identity"]} namespaces="{AUTH_NAMESPACE}" {authority["public_key"]}\n'
        with tempfile.TemporaryDirectory() as directory:
            allowed = Path(directory) / "allowed_signers"
            sig = Path(directory) / "authorization.sig"
            allowed.write_text(allowed_record, encoding="utf-8")
            sig.write_bytes(signature_path.read_bytes())
            process = subprocess.run(
                ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", authority["identity"], "-n", AUTH_NAMESPACE, "-s", str(sig)],
                input=canonical_bytes(authorization), capture_output=True, timeout=30, check=False,
            )
        if process.returncode:
            raise SuccessionProposalBlocked("owner authorization signature verification failed")
        if authorization.get("revocation_status") != "not_revoked":
            raise SuccessionProposalBlocked("owner authorization revocation status is not currently verified")
        if authorization.get("effect_boundary") != {"local_revision_activation": True, "production_activation": False, "package": False, "install": False, "publication": False}:
            raise SuccessionProposalBlocked("owner authorization effect boundary is invalid")
        if type(authorization.get("intake_findings")) is not list or not authorization["intake_findings"] or any(type(item) is not str or not item.strip() for item in authorization["intake_findings"]):
            raise SuccessionProposalBlocked("owner authorization intake denominator is malformed")
        if len(authorization["intake_findings"]) != len(set(authorization["intake_findings"])):
            raise SuccessionProposalBlocked("owner authorization intake denominator contains duplicates")
        if authorization.get("authorization_id") in policy.get("revoked_authorizations", []):
            raise SuccessionProposalBlocked("owner authorization has been revoked")
        if authorization.get("superseded_by"):
            raise SuccessionProposalBlocked("owner authorization has been superseded")
        if authorization.get("replay_status") != "unused":
            raise SuccessionProposalBlocked("owner authorization replay status is not unused")
        issued = _timestamp(authorization["issued_at"], "issued_at")
        expires = _timestamp(authorization["expires_at"], "expires_at")
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None or expires <= issued or moment < issued or moment >= expires:
            raise SuccessionProposalBlocked("owner authorization is expired or outside its validity window")
        return {"valid": True, "authorization_id": auth_id, "issuer": signer, "policy_id": policy["policy_id"], "policy_provenance": policy_provenance}
    except SuccessionProposalBlocked:
        raise
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise SuccessionProposalBlocked(f"owner authorization verification failed: {type(error).__name__}") from error

def _predecessor_identity_view(campaign: Mapping[str, Any], record_raw: bytes, expected_record_sha256: str) -> dict[str, Any]:
    if hashlib.sha256(record_raw).hexdigest() != _sha256(expected_record_sha256, "predecessor project-record digest"):
        raise SuccessionProposalBlocked("predecessor project record differs from signed authorization")
    from .json_io import decode_json_object
    record = decode_json_object(record_raw, max_bytes=1024 * 1024)
    project_id = _identifier(record.get("project_id"), "predecessor project_id")
    if "project_id" in campaign and campaign["project_id"] != project_id:
        raise SuccessionProposalBlocked("predecessor campaign and project record identities differ")
    return {**campaign, "project_id": project_id}


def validate_successor_proposal(
    *,
    predecessor_campaign: Mapping[str, Any],
    predecessor_raw_sha256: str,
    proposal: Mapping[str, Any],
    owner_authorization: Mapping[str, Any] | None,
    verify_owner_authorization: Callable[[Mapping[str, Any]], bool] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(predecessor_campaign, Mapping):
        raise SuccessionProposalBlocked("predecessor campaign must be an object")
    predecessor_id = _identifier(predecessor_campaign.get("campaign_id"), "predecessor campaign_id")
    if (
        predecessor_campaign.get("schema_version") != "px.repair-campaign/1.0"
        or predecessor_campaign.get("phase") != "installed_operational"
        or predecessor_campaign.get("intake_open") is not False
        or predecessor_campaign.get("unresolved") != []
        or type(predecessor_campaign.get("unresolved")) is not list
    ):
        raise SuccessionProposalBlocked("predecessor must be a closed, zero-unresolved terminal campaign")
    if predecessor_campaign.get("project_id") is None:
        raise SuccessionProposalBlocked("predecessor project identity is required")

    predecessor_digest = _sha256(predecessor_raw_sha256, "predecessor_raw_sha256")
    project_id = _identifier(proposal.get("successor_project_id"), "successor_project_id")
    campaign_id = _identifier(proposal.get("successor_campaign_id"), "successor_campaign_id")
    predecessor_project_id = _identifier(predecessor_campaign.get("project_id"), "predecessor project_id")
    if project_id == predecessor_project_id or campaign_id == predecessor_id:
        raise SuccessionProposalBlocked("successor identity must differ from its predecessor")
    if proposal.get("predecessor_campaign_id") != predecessor_id:
        raise SuccessionProposalBlocked("proposal predecessor campaign ID does not match")
    proposal_predecessor_digest = _sha256(proposal.get("predecessor_raw_sha256"), "proposal predecessor_raw_sha256")
    if proposal_predecessor_digest != predecessor_digest:
        raise SuccessionProposalBlocked("proposal does not bind the exact predecessor bytes")
    source_digest = _sha256(proposal.get("source_tree_sha256"), "source_tree_sha256")
    policy_id = _identifier(proposal.get("owner_policy_id"), "owner_policy_id")

    authorization = owner_authorization
    verifier = verify_owner_authorization
    if not isinstance(authorization, Mapping) or not callable(verifier):
        raise SuccessionProposalBlocked("canonical owner authorization verifier and record are required")
    if verifier(authorization) is not True:
        raise SuccessionProposalBlocked("owner authorization was not verified by its canonical trust owner")

    if authorization.get("decision") != "approved":
        raise SuccessionProposalBlocked("owner authorization is not an approval")
    if authorization.get("verified") is False:
        raise SuccessionProposalBlocked("owner authorization is revoked or unverified")
    authorization_id = _identifier(authorization.get("authorization_id"), "authorization_id")
    authority_ref = _identifier(authorization.get("issuer") or authorization.get("authority_ref"), "authority_ref")
    if (
        authorization.get("successor_project_id") != project_id
        or authorization.get("successor_campaign_id") != campaign_id
        or authorization.get("predecessor_campaign_id") != predecessor_id
        or (proposal.get("predecessor_campaign_state_sha256") is not None
            and authorization.get("predecessor_campaign_state_sha256") != proposal.get("predecessor_campaign_state_sha256"))
        or (proposal.get("predecessor_project_record_sha256") is not None
            and (authorization.get("predecessor_project_record_sha256") != proposal.get("predecessor_project_record_sha256")
                 or authorization.get("predecessor_validation_policy_sha256") != proposal.get("predecessor_validation_policy_sha256")))
        or authorization.get("predecessor_raw_sha256") != proposal_predecessor_digest
        or authorization.get("source_tree_sha256") != source_digest
        or authorization.get("owner_policy_id") != policy_id
    ):
        raise SuccessionProposalBlocked("owner authorization is not bound to this exact succession proposal")
    issued = _timestamp(authorization.get("issued_at"), "issued_at")
    expires = _timestamp(authorization.get("expires_at"), "expires_at")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise SuccessionProposalBlocked("validation time must include a timezone")
    moment = moment.astimezone(timezone.utc)
    if expires <= issued or moment < issued or moment >= expires:
        raise SuccessionProposalBlocked("owner authorization is not currently valid")
    if authorization.get("revocation_status") != "not_revoked":
        raise SuccessionProposalBlocked("owner authorization is revoked or lacks an explicit non-revocation result")
    effect_boundary = authorization.get("effect_boundary")
    if effect_boundary != {"local_revision_activation": True, "production_activation": False, "package": False, "install": False, "publication": False}:
        raise SuccessionProposalBlocked("owner authorization does not have exact local-development effect boundaries")
    if type(authorization.get("intake_findings")) is not list or not authorization["intake_findings"]:
        raise SuccessionProposalBlocked("owner authorization must bind a non-empty intake denominator")
    if any(type(item) is not str or not item.strip() for item in authorization["intake_findings"]):
        raise SuccessionProposalBlocked("owner authorization intake denominator is malformed")
    if len(authorization["intake_findings"]) != len(set(authorization["intake_findings"])):
        raise SuccessionProposalBlocked("owner authorization intake denominator contains duplicates")
    if type(authorization.get("source_identity")) is not dict or set(authorization["source_identity"]) != {"kind", "source_sha256"}:
        raise SuccessionProposalBlocked("owner authorization source identity binding is malformed")
    if authorization["source_identity"].get("source_sha256") != source_digest:
        raise SuccessionProposalBlocked("owner authorization source identity hash differs")
    _identifier(authorization["source_identity"].get("kind"), "source identity kind")
    if authorization["source_identity"].get("kind") not in {"git_tree", "source_tree", "release_source"}:
        raise SuccessionProposalBlocked("owner authorization source identity kind is unsupported")
    for field in ("successor_project_id", "successor_campaign_id", "predecessor_campaign_id"):
        if not authorization.get(field):
            raise SuccessionProposalBlocked(f"owner authorization {field} is required")
    if authorization.get("successor_campaign_id") == authorization.get("predecessor_campaign_id"):
        raise SuccessionProposalBlocked("owner authorization successor campaign must be unique")
    if not isinstance(authorization.get("successor_project_id"), str):
        raise SuccessionProposalBlocked("owner authorization successor project identity is malformed")
    if authorization.get("revocation_status") != "not_revoked":
        raise SuccessionProposalBlocked("owner authorization has been revoked")
    if authorization.get("superseded_by"):
        raise SuccessionProposalBlocked("owner authorization has been superseded")
    if authorization.get("revoked") is not False:
        raise SuccessionProposalBlocked("owner authorization is revoked or lacks an explicit non-revocation result")

    authorization_digest = _digest(dict(authorization))
    binding = {
        "schema_version": SCHEMA,
        "successor_project_id": project_id,
        "successor_campaign_id": campaign_id,
        "predecessor_campaign_id": predecessor_id,
        "predecessor_raw_sha256": proposal_predecessor_digest,
        **({"predecessor_campaign_state_sha256": _sha256(proposal.get("predecessor_campaign_state_sha256"), "predecessor_campaign_state_sha256")} if proposal.get("predecessor_campaign_state_sha256") is not None else {}),
        **({"predecessor_project_record_sha256": _sha256(proposal.get("predecessor_project_record_sha256"), "predecessor_project_record_sha256"),
            "predecessor_validation_policy_sha256": _sha256(proposal.get("predecessor_validation_policy_sha256"), "predecessor_validation_policy_sha256")} if proposal.get("predecessor_project_record_sha256") is not None else {}),
        "source_tree_sha256": source_digest,
        "owner_policy_id": policy_id,
        "authorization_id": authorization_id,
        "authority_ref": authority_ref,
        "authorization_sha256": authorization_digest,
    }
    return {
        "valid": True,
        "activated": False,
        "binding": binding,
        "binding_sha256": _digest(binding),
        "notice": "Proposal validated only; persistence and campaign activation require the canonical succession owner.",
    }


def prepare_successor_event(
    *,
    history: list[Mapping[str, Any]],
    predecessor_campaign: Mapping[str, Any],
    predecessor_raw_sha256: str,
    proposal: Mapping[str, Any],
    owner_authorization: Mapping[str, Any] | None,
    verify_owner_authorization: Callable[[Mapping[str, Any]], bool] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    # Pure planner only; it never persists, serializes competing writers, or activates.

    if type(history) is not list or len(history) > 100_000:
        raise SuccessionProposalBlocked("succession history must be a bounded list")
    previous = "0" * 64
    seen_projects: set[str] = set()
    seen_campaigns: set[str] = set()
    seen_predecessors: set[str] = set()
    seen_authorizations: set[str] = set()
    latest_activated: Mapping[str, Any] | None = None
    seen_event_ids: set[str] = set()
    for sequence, event in enumerate(history, start=1):
        if not isinstance(event, Mapping):
            raise SuccessionProposalBlocked("succession history contains a malformed event")
        body = {key: value for key, value in event.items() if key != "event_sha256"}
        expected = _digest(body)
        if (
            event.get("schema_version") != SCHEMA
            or event.get("sequence") != sequence
            or event.get("previous_event_sha256") != previous
            or event.get("event_sha256") != expected
            or type(event.get("authorization")) is not dict
            or event.get("event_status") not in {"proposed", "activated"}
            or set(event) != {"schema_version", "sequence", "previous_event_sha256", "binding", "binding_sha256", "authorization", "event_status", "event_sha256"}
        ):
            raise SuccessionProposalBlocked("succession history hash chain is corrupt")
        binding = event.get("binding")
        if not isinstance(binding, Mapping):
            raise SuccessionProposalBlocked("succession history binding is malformed")
        if event.get("binding_sha256") != _digest(binding):
            raise SuccessionProposalBlocked("succession history binding digest is corrupt")
        allowed_binding_fields = {
            "schema_version", "successor_project_id", "successor_campaign_id",
            "predecessor_campaign_id", "predecessor_raw_sha256", "source_tree_sha256",
            "owner_policy_id", "authorization_id", "authority_ref", "authorization_sha256",
        }
        expanded_binding_fields = allowed_binding_fields | {"predecessor_campaign_state_sha256", "predecessor_project_record_sha256", "predecessor_validation_policy_sha256"}
        revision_binding_fields = allowed_binding_fields | {"predecessor_campaign_state_sha256"}
        legacy_snapshot_fields = allowed_binding_fields | {"predecessor_project_record_sha256", "predecessor_validation_policy_sha256"}
        if set(binding) not in (allowed_binding_fields, revision_binding_fields, expanded_binding_fields, legacy_snapshot_fields):
            raise SuccessionProposalBlocked("succession event binding fields are not exact")
        if "predecessor_campaign_state_sha256" in binding:
            _sha256(binding["predecessor_campaign_state_sha256"], "history predecessor campaign state hash")
        if "predecessor_project_record_sha256" in binding:
            _sha256(binding["predecessor_project_record_sha256"], "history predecessor project-record hash")
            _sha256(binding["predecessor_validation_policy_sha256"], "history predecessor validation-policy hash")
        project_id = _identifier(binding.get("successor_project_id"), "history successor_project_id")
        campaign_id = _identifier(binding.get("successor_campaign_id"), "history successor_campaign_id")
        predecessor_id = _identifier(binding.get("predecessor_campaign_id"), "history predecessor_campaign_id")
        authorization_id = _identifier(binding.get("authorization_id"), "history authorization_id")
        event_identity = _sha256(event.get("event_sha256"), "history event identity")
        _sha256(binding.get("predecessor_raw_sha256"), "history predecessor_raw_sha256")
        _sha256(binding.get("source_tree_sha256"), "history source_tree_sha256")
        _identifier(binding.get("owner_policy_id"), "history owner_policy_id")
        _identifier(binding.get("authority_ref"), "history authority_ref")
        _sha256(binding.get("authorization_sha256"), "history authorization_sha256")
        authorization = event["authorization"]
        if (authorization.get("authorization_id") != authorization_id
                or authorization.get("successor_project_id") != project_id
                or authorization.get("successor_campaign_id") != campaign_id
                or authorization.get("predecessor_campaign_id") != predecessor_id
                or authorization.get("predecessor_raw_sha256") != binding["predecessor_raw_sha256"]
                or authorization.get("source_tree_sha256") != binding["source_tree_sha256"]
                or authorization.get("owner_policy_id") != binding["owner_policy_id"]
                or _digest(authorization) != binding["authorization_sha256"]
                or ("predecessor_campaign_state_sha256" in binding
                    and authorization.get("predecessor_campaign_state_sha256") != binding["predecessor_campaign_state_sha256"])):
            raise SuccessionProposalBlocked("succession authorization evidence does not match event binding")
        if (
            event_identity in seen_event_ids
            or project_id in seen_projects
            or campaign_id in seen_campaigns
            or authorization_id in seen_authorizations
            or (event["event_status"] == "activated" and predecessor_id in seen_predecessors)
            or (
                event["event_status"] == "activated"
                and latest_activated is not None
                and predecessor_id != latest_activated["binding"]["successor_campaign_id"]
            )
            or (
                event["event_status"] == "activated"
                and latest_activated is None
                and predecessor_id in seen_campaigns
            )
        ):
            raise SuccessionProposalBlocked("succession history contains a replay or activated predecessor fork")
        seen_event_ids.add(event_identity)
        seen_projects.add(project_id)
        seen_campaigns.add(campaign_id)
        seen_authorizations.add(authorization_id)
        if event["event_status"] == "activated":
            seen_predecessors.add(predecessor_id)
            latest_activated = event
        previous = expected
    if latest_activated is not None:
        active_binding = latest_activated["binding"]
        if predecessor_campaign.get("campaign_id") != active_binding["successor_campaign_id"]:
            raise SuccessionProposalBlocked("proposal predecessor is not the latest activated campaign")
        if proposal.get("predecessor_campaign_id") != active_binding["successor_campaign_id"]:
            raise SuccessionProposalBlocked("proposal predecessor is not the latest activated campaign")
        expected_state_digest = active_binding.get("predecessor_campaign_state_sha256")
        if expected_state_digest is not None:
            supplied_state = dict(predecessor_campaign)
            supplied_state.pop("succession_event_sha256", None)
            if _digest(supplied_state) != expected_state_digest:
                raise SuccessionProposalBlocked("supplied predecessor campaign state differs from latest activated successor")
            if proposal.get("predecessor_campaign_state_sha256") != expected_state_digest:
                raise SuccessionProposalBlocked("proposal predecessor campaign state hash differs from latest activated successor")
        # Proposal and owner authorization bind the successor's predecessor raw
        # hash separately from source-tree and historical event identities.
        _sha256(predecessor_raw_sha256, "predecessor raw SHA-256")
        if proposal.get("predecessor_raw_sha256") != predecessor_raw_sha256:
            raise SuccessionProposalBlocked("proposal predecessor raw hash differs from supplied campaign bytes")
        if owner_authorization.get("predecessor_raw_sha256") != predecessor_raw_sha256:
            raise SuccessionProposalBlocked("authorization predecessor raw hash differs from supplied campaign bytes")
    validated = validate_successor_proposal(
        predecessor_campaign=predecessor_campaign,
        predecessor_raw_sha256=predecessor_raw_sha256,
        proposal=proposal,
        owner_authorization=owner_authorization,
        verify_owner_authorization=verify_owner_authorization,
        now=now,
    )
    binding = validated["binding"]
    if (
        binding["successor_project_id"] in seen_projects
        or binding["successor_campaign_id"] in seen_campaigns
        or binding["authorization_id"] in seen_authorizations
        or binding["predecessor_campaign_id"] in seen_predecessors
    ):
        raise SuccessionProposalBlocked("successor proposal replays or forks existing history")
    body = {
        "schema_version": SCHEMA,
        "sequence": len(history) + 1,
        "previous_event_sha256": previous,
        "binding": binding,
        "binding_sha256": validated["binding_sha256"],
        "authorization": dict(owner_authorization),
        "event_status": "proposed",
    }
    event = {**body, "event_sha256": _digest(body)}
    return {
        "valid": True,
        "activated": False,
        "event": event,
        "notice": "Append candidate only; it remains inactive until a separately authorized activation transaction succeeds.",
    }


SUCCESSION_STATE_PATH = Path(".agentic_engineering_os_px/project-revision-succession/state.json")
SUCCESSION_WAL_PATH = Path(".agentic_engineering_os_px/project-revision-succession/wal")
SUCCESSION_LOCK_PATH = Path(".agentic_engineering_os_px/project-revision-succession/activation.lock")
ACTIVE_REVISION_PATH = Path(".agentic_engineering_os_px/processing-order/active-revision.json")
PROJECT_RECORD_PATH = Path(".agentic_engineering_os_px/project-record.json")
PROJECT_CAMPAIGN_PATH = Path(".agentic_engineering_os_px/processing-order/repair-campaign.json")


def current_revision_root(root: Path) -> Path | None:
    # Resolve a hash-verified active revision; legacy projects return None.
    root = Path(root).resolve(strict=True)
    pointer_path = root / ACTIVE_REVISION_PATH
    if not pointer_path.exists():
        return None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if type(pointer) is not dict or set(pointer) != {
            "schema_version", "project_id", "revision_root", "event_sha256",
            "campaign_sha256", "policy_sha256", "project_record_sha256",
        } or pointer.get("schema_version") != "px.active-project-revision/1.0":
            raise ValueError("active revision pointer schema mismatch")
        relative = Path(pointer["revision_root"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("active revision path escapes project root")
        revision = (root / relative).resolve(strict=True)
        if root not in revision.parents:
            raise ValueError("active revision is outside project root")
        expected_relative = Path(".agentic_engineering_os_px/project-revisions") / str(pointer.get("project_id") or "")
        if relative != expected_relative:
            raise ValueError("active revision pointer uses a non-canonical namespace")
        state = json.loads((root / SUCCESSION_STATE_PATH).read_text(encoding="utf-8"))
        if type(state) is not dict or set(state) != {"schema_version", "events"} or state.get("schema_version") != STATE_SCHEMA:
            raise ValueError("succession state schema mismatch")
        validate_history(state["events"])
        events = [event for event in state["events"] if event["event_sha256"] == pointer["event_sha256"]]
        if len(events) != 1 or events[0]["binding"]["successor_project_id"] != pointer["project_id"]:
            raise ValueError("active pointer is not bound to exactly one succession event")
        if state["events"][-1]["event_sha256"] != pointer["event_sha256"]:
            raise ValueError("active revision pointer does not select the latest appended successor")
        bound_event = events[0]
        binding = bound_event["binding"]
        campaign = json.loads((revision / "repair-campaign.json").read_text(encoding="utf-8"))
        predecessor_raw = (root / "evidence/project-revision-succession" / binding["predecessor_campaign_id"] / binding["predecessor_raw_sha256"] / "repair-campaign.json").read_bytes()
        if hashlib.sha256(predecessor_raw).hexdigest() != binding["predecessor_raw_sha256"] or json.loads(predecessor_raw).get("campaign_id") != binding["predecessor_campaign_id"]:
            raise ValueError("active revision does not retain its exact predecessor campaign image")
        predecessor_campaign = json.loads(predecessor_raw)
        if binding.get("predecessor_raw_sha256") != campaign.get("revision_parent_sha256"):
            raise ValueError("active revision predecessor hash differs from archived source")
        predecessor_state_digest = binding.get("predecessor_campaign_state_sha256")
        if predecessor_state_digest is not None:
            state_campaign = dict(predecessor_campaign)
            state_campaign.pop("succession_event_sha256", None)
            if _digest(state_campaign) != predecessor_state_digest:
                raise ValueError("active revision predecessor campaign state differs from its signed binding")
        if binding.get("predecessor_project_record_sha256") is None or binding.get("predecessor_validation_policy_sha256") is None:
            raise ValueError("active revision lacks immutable predecessor record and policy digests")
        if campaign.get("revision_parent_campaign_id") != binding.get("predecessor_campaign_id") or campaign.get("succession_event_sha256") != bound_event.get("event_sha256"):
            raise ValueError("active revision campaign does not bind exact parent/event")
        if _digest(bound_event["authorization"]) != binding.get("authorization_sha256"):
            raise ValueError("active revision owner authorization digest is invalid")
        predecessor_root = root / "evidence/project-revision-succession" / binding["predecessor_campaign_id"] / binding["predecessor_raw_sha256"]
        predecessor_archive = predecessor_root / "repair-campaign.json"
        if not predecessor_archive.is_file() or hashlib.sha256(predecessor_archive.read_bytes()).hexdigest() != binding["predecessor_raw_sha256"]:
            raise ValueError("active revision predecessor archive is missing or invalid")
        for name, field in (("repair-campaign.json", "campaign_sha256"),
                            ("validation-policy.json", "policy_sha256"),
                            ("project-record.json", "project_record_sha256")):
            if hashlib.sha256((revision / name).read_bytes()).hexdigest() != pointer[field]:
                raise ValueError(f"active revision {name} digest mismatch")
        predecessor_record_raw = (predecessor_root / "project-record.json").read_bytes()
        predecessor_policy_raw = (predecessor_root / "validation-policy.json").read_bytes()
        if (binding.get("predecessor_project_record_sha256") is not None
                and hashlib.sha256(predecessor_record_raw).hexdigest() != binding["predecessor_project_record_sha256"]):
            raise ValueError("active revision predecessor project-record snapshot differs")
        if (binding.get("predecessor_validation_policy_sha256") is not None
                and hashlib.sha256(predecessor_policy_raw).hexdigest() != binding["predecessor_validation_policy_sha256"]):
            raise ValueError("active revision predecessor validation-policy snapshot differs")
        campaign = json.loads((revision / "repair-campaign.json").read_text(encoding="utf-8"))
        record = json.loads((revision / "project-record.json").read_text(encoding="utf-8"))
        if campaign.get("campaign_id") != events[0]["binding"]["successor_campaign_id"] or record.get("project_id") != pointer["project_id"]:
            raise ValueError("active revision project/campaign identity mismatch")
        policy = json.loads((revision / "validation-policy.json").read_text(encoding="utf-8"))
        if policy.get("campaign_id") != binding.get("successor_campaign_id") or policy.get("authority") != "OWNER-FRESH-VALIDATION-001" or policy.get("basis") != "current_implementation":
            raise ValueError("active revision validation policy is not bound to its successor campaign")
        expected_succession = {
            "event_sha256": bound_event["event_sha256"],
            "predecessor_campaign_id": binding["predecessor_campaign_id"],
            "predecessor_raw_sha256": binding["predecessor_raw_sha256"],
            **({"predecessor_project_record_sha256": hashlib.sha256(predecessor_record_raw).hexdigest(),
                "predecessor_validation_policy_sha256": hashlib.sha256(predecessor_policy_raw).hexdigest()}
               if "predecessor_project_record_sha256" in binding and "predecessor_validation_policy_sha256" in binding else {}),
        }
        policy_succession = policy.get("revision_succession")
        if not isinstance(policy_succession, dict) or any(policy_succession.get(key) != value for key, value in expected_succession.items()):
            raise ValueError("active revision validation policy lacks its exact succession parent binding")
        if policy_succession.get("campaign_state_sha256") != hashlib.sha256((revision / "repair-campaign.json").read_bytes()).hexdigest():
            raise ValueError("active revision campaign state digest differs from validation policy")
        if policy_succession.get("campaign_state_sha256") != pointer["campaign_sha256"]:
            raise ValueError("active revision campaign state differs from validation policy binding")
        if binding.get("predecessor_project_record_sha256") is None and binding.get("predecessor_validation_policy_sha256") is None:
            parent_record = json.loads(predecessor_record_raw)
            parent_policy = json.loads(predecessor_policy_raw)
            if (type(parent_record.get("project_id")) is not str
                    or parent_record.get("project_id") == pointer["project_id"]
                    or parent_policy.get("campaign_id") != binding.get("predecessor_campaign_id")):
                raise ValueError("legacy predecessor project or policy snapshot is inconsistent")
        return revision
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SuccessionProposalBlocked(f"active revision state is corrupt: {error}") from error

def _authorization_policy(policy: object) -> dict[str, Any]:
    return validate_owner_policy(policy)


def revision_campaign_status(root: Path) -> dict[str, Any]:
    from .revision_campaign_lifecycle import status
    return status(root)


def register_revision_findings(root: Path, *, finding_ids: list[str], admission_event_id: str) -> dict[str, Any]:
    from .revision_campaign_lifecycle import register_findings
    return register_findings(root, finding_ids=finding_ids, admission_event_id=admission_event_id)


def resolve_revision_findings(root: Path, *, evidence_by_finding: Mapping[str, str], admission_event_id: str) -> dict[str, Any]:
    from .revision_campaign_lifecycle import resolve_findings
    return resolve_findings(root, evidence_by_finding=evidence_by_finding, admission_event_id=admission_event_id)


def current_campaign_path(root: Path) -> Path:
    revision = current_revision_root(root)
    return revision / "repair-campaign.json" if revision is not None else Path(root) / PROJECT_CAMPAIGN_PATH

def current_validation_policy_path(root: Path) -> Path:
    revision = current_revision_root(root)
    return revision / "validation-policy.json" if revision is not None else Path(root) / "policies/rev1xx-validation.json"

def project_root_for_validation_policy(policy_path: Path) -> Path:
    path = Path(policy_path).resolve(strict=False)
    parent = path.parent
    if path.name == "validation-policy.json" and parent.name.startswith("prj_"):
        project_root = parent.parents[1]
        return project_root
    if path.name == "rev1xx-validation.json":
        return parent.parent
    raise SuccessionProposalBlocked("validation policy path does not identify a supported project root")

def current_source_digest(root: Path) -> str:
    from .release_artifacts import classify_tree
    result = classify_tree(Path(root))
    if result.get("valid") is not True or result.get("product_valid") is not True:
        raise SuccessionProposalBlocked("current source tree is not classifiable")
    return _digest({"product_digest": result["product_digest"], "harness_digest": result["harness_digest"]})

def missing_owner_policy_authority(_policy: Mapping[str, Any]) -> bool:
    raise SuccessionProposalBlocked(
        "no canonical verified project-revision-succession policy issuer is configured; "
        "a signed owner policy trust artifact and verifier are required"
    )

class SuccessionLedger:
    # Append-only, crash-recoverable event persistence; never activates a revision.

    def __init__(self, root: Path):
        self.root = Path(root).resolve(strict=True)
        self.state_path = self.root / SUCCESSION_STATE_PATH
        self.lock_path = self.root / SUCCESSION_LOCK_PATH
        self.wal = JsonWal(SUCCESSION_WAL_PATH, self.root)

    def _read(self, *, allow_pending: bool = False) -> dict[str, Any]:
        if self.wal._pending_transactions() and not allow_pending:
            raise SuccessionProposalBlocked("succession state requires explicit WAL recovery")
        if not self.state_path.exists():
            return {"schema_version": STATE_SCHEMA, "events": []}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SuccessionProposalBlocked("succession state is unreadable") from error
        if type(value) is not dict or set(value) != {"schema_version", "events"} or value.get("schema_version") != STATE_SCHEMA:
            raise SuccessionProposalBlocked("succession state schema is invalid")
        validate_history(value["events"])
        return value
    def status(self) -> dict[str, Any]:
        from .archive_io import reject_path_links
        reject_path_links(self.state_path)
        reject_path_links(self.lock_path)
        if self.wal._pending_transactions():
            return {"valid": False, "requires_recovery": True, "recovery": self.wal.inspect()}
        state = self._read()
        return {"valid": True, "requires_recovery": False, **validate_history(state["events"])}

    def recover(self, *, admission_event_id: str) -> dict[str, Any]:
        _guard_succession_effect(self.root, admission_event_id, "write")
        from .archive_io import reject_path_links
        reject_path_links(self.root)
        reject_path_links(self.lock_path)
        reject_path_links(self.state_path)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path, timeout_seconds=10.0):
            result = self.wal.recover()
            self._read()
            return result
    def _append_candidate(self, event: Mapping[str, Any], *, fault_injector: Callable[[str], None] | None = None) -> dict[str, Any]:
        from .archive_io import reject_path_links
        reject_path_links(self.root)
        reject_path_links(self.lock_path)
        reject_path_links(self.state_path)
        if type(event) is not dict:
            raise SuccessionProposalBlocked("succession append candidate must be a concrete event object")
        candidate = json.loads(json.dumps(event, sort_keys=True, separators=(',', ':')))
        with FileLock(self.lock_path, timeout_seconds=10.0):
            if self.wal._pending_transactions():
                self.wal.recover()
            current = self._read()
            if candidate in current["events"]:
                raise SuccessionProposalBlocked("succession event replay is rejected")
            # Validate candidate independently, then enforce exact next sequence and parent.
            if current["events"] and (candidate.get("sequence") != len(current["events"]) + 1 or candidate.get("previous_event_sha256") != current["events"][-1].get("event_sha256")):
                raise SuccessionProposalBlocked("succession candidate is not the next hash-chained event")
            validate_history([*current["events"], candidate])
            active_events = [row for row in current["events"] if row["event_status"] == "activated"]
            if active_events:
                active_campaign = active_events[-1]["binding"]["successor_campaign_id"]
                if candidate["binding"]["predecessor_campaign_id"] != active_campaign:
                    raise SuccessionProposalBlocked("successor chain predecessor is not the current active campaign")
            after = {"schema_version": STATE_SCHEMA, "events": [*current["events"], candidate]}
            before = hashlib.sha256(self.state_path.read_bytes()).hexdigest() if self.state_path.exists() else None
            transaction = self.wal.commit(
                [JsonArtifact("event", self.state_path, after)],
                transaction_id="succession-" + candidate["event_sha256"][:32],
                expected_before={self.state_path.relative_to(self.root).as_posix(): before},
                fault_injector=fault_injector,
            )
            if self._read() != after:
                raise SuccessionProposalBlocked("published succession state differs from committed after-image")
            return {"valid": True, "activated": False, "event": candidate, "transaction": transaction}

    def append_authorized(
        self, *, predecessor_campaign: Mapping[str, Any], predecessor_raw_sha256: str,
        proposal: Mapping[str, Any], owner_authorization: Mapping[str, Any],
        policy_path: Path, signature_path: Path, policy_evidence_reference: str,
        evidence_store: Path, evidence_trust_policy_path: Path, project_id: str,
        admission_event_id: str,
        fault_injector: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        # Verify authority and atomically append exactly one immutable succession event.
        _guard_succession_effect(self.root, admission_event_id, "write")
        from .archive_io import reject_path_links
        reject_path_links(self.root)
        reject_path_links(self.lock_path)
        reject_path_links(self.state_path)
        reject_path_links(Path(policy_path))
        reject_path_links(Path(signature_path))
        policy_path = Path(policy_path).resolve(strict=True)
        signature_path = Path(signature_path).resolve(strict=True)
        verification = verify_owner_authorization(
            owner_authorization, policy_path=policy_path, signature_path=signature_path,
            policy_evidence_reference=policy_evidence_reference,
            evidence_store=evidence_store,
            evidence_trust_policy_path=evidence_trust_policy_path,
            project_id=project_id,
        )
        policy = validate_owner_policy(json.loads(policy_path.read_text(encoding="utf-8")))
        if current_source_digest(self.root) != _sha256(proposal.get("source_tree_sha256"), "source_tree_sha256"):
            raise SuccessionProposalBlocked("successor source identity is stale or unverified")
        if proposal.get("owner_policy_id") != policy["policy_id"]:
            raise SuccessionProposalBlocked("proposal is not bound to the installed succession owner policy")
        if owner_authorization.get("source_tree_sha256") != proposal.get("source_tree_sha256"):
            raise SuccessionProposalBlocked("signed source identity differs from the proposal")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path, timeout_seconds=10.0):
            if self.wal._pending_transactions():
                self.wal.recover()
            current = self._read()
            prepared = prepare_successor_event(
                history=current["events"],
                predecessor_campaign=predecessor_campaign,
                predecessor_raw_sha256=predecessor_raw_sha256,
                proposal=proposal,
                owner_authorization=owner_authorization,
                verify_owner_authorization=lambda row: (
                    row.get("authorization_id") == verification["authorization_id"]
                    and row.get("issuer") == verification["issuer"]
                ),
            )
            return self._append_candidate(prepared["event"], fault_injector=fault_injector)

    def activate_revision(
        self, *, predecessor_campaign: Mapping[str, Any], predecessor_raw_sha256: str,
        proposal: Mapping[str, Any], owner_authorization: Mapping[str, Any],
        policy_path: Path, signature_path: Path, policy_evidence_reference: str,
        evidence_store: Path, evidence_trust_policy_path: Path, project_id: str,
        admission_event_id: str,
        fault_injector: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        # Publish a new revision namespace; the predecessor campaign is never edited.
        _guard_succession_effect(self.root, admission_event_id, "write")
        from .archive_io import reject_path_links
        reject_path_links(self.root)
        reject_path_links(self.lock_path)
        reject_path_links(self.state_path)
        reject_path_links(Path(policy_path))
        reject_path_links(Path(signature_path))
        policy_path = Path(policy_path).resolve(strict=True)
        signature_path = Path(signature_path).resolve(strict=True)
        verification = verify_owner_authorization(
            owner_authorization, policy_path=policy_path, signature_path=signature_path,
            policy_evidence_reference=policy_evidence_reference,
            evidence_store=evidence_store,
            evidence_trust_policy_path=evidence_trust_policy_path,
            project_id=project_id,
        )
        policy = validate_owner_policy(json.loads(policy_path.read_text(encoding="utf-8")))
        parent_campaign_path = current_campaign_path(self.root)
        actual_predecessor = json.loads(parent_campaign_path.read_text(encoding="utf-8"))
        active_revision = current_revision_root(self.root)
        if active_revision is None:
            predecessor_record_path = self.root / PROJECT_RECORD_PATH
        else:
            predecessor_record_path = active_revision / "project-record.json"
        reject_path_links(predecessor_record_path)
        predecessor_view = _predecessor_identity_view(actual_predecessor,
            predecessor_record_path.read_bytes(), owner_authorization["predecessor_project_record_sha256"])
        predecessor_project_id = predecessor_view["project_id"]
        if project_id != predecessor_project_id:
            raise SuccessionProposalBlocked("owner policy verification scope must name the current predecessor project")
        source_digest = _sha256(proposal.get("source_tree_sha256"), "source_tree_sha256")
        if current_source_digest(self.root) != source_digest:
            raise SuccessionProposalBlocked("current source identity is stale or unverified")
        if proposal.get("owner_policy_id") != policy["policy_id"]:
            raise SuccessionProposalBlocked("proposal policy identity differs from verified owner policy")
        validation_policy = dict(owner_authorization.get("validation_policy") or {})
        campaign_id = _identifier(proposal.get("successor_campaign_id"), "successor_campaign_id")
        project_id = _identifier(proposal.get("successor_project_id"), "successor_project_id")
        if (type(validation_policy) is not dict
                or validation_policy.get("schema_version") != "px.validation-basis/1.0"
                or validation_policy.get("authority") != "OWNER-FRESH-VALIDATION-001"
                or validation_policy.get("campaign_id") != campaign_id):
            raise SuccessionProposalBlocked("signed authorization lacks fresh successor validation policy")
        intake_findings = owner_authorization.get("intake_findings")
        if (type(intake_findings) is not list or not intake_findings
                or any(type(item) is not str or not item.strip() for item in intake_findings)
                or len(intake_findings) != len(set(intake_findings))):
            raise SuccessionProposalBlocked("owner authorization must bind a truthful non-empty successor intake denominator")
        if policy["revision_scope"] and project_id not in policy["revision_scope"] and "*" not in policy["revision_scope"]:
            raise SuccessionProposalBlocked("successor project is outside owner policy revision scope")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path, timeout_seconds=10.0):
            if self.wal._pending_transactions():
                self.wal.recover()
            state = self._read()
            parent_campaign_path = current_campaign_path(self.root)
            parent_raw = parent_campaign_path.read_bytes()
            parent_digest = hashlib.sha256(parent_raw).hexdigest()
            if parent_digest != predecessor_raw_sha256:
                raise SuccessionProposalBlocked("predecessor campaign bytes changed")
            parent = json.loads(parent_raw)
            if dict(predecessor_campaign) != parent:
                raise SuccessionProposalBlocked("predecessor campaign differs from current immutable source")
            root_record_path = self.root / PROJECT_RECORD_PATH
            root_record_raw = root_record_path.read_bytes()
            marker = json.loads(root_record_raw)
            parent_revision = current_revision_root(self.root)
            parent_record_path = (parent_revision / "project-record.json") if parent_revision else root_record_path
            parent_record_raw = parent_record_path.read_bytes()
            parent_record = json.loads(parent_record_raw)
            proposal_with_parent_state = dict(proposal)
            predecessor_policy_path = (parent_revision / "validation-policy.json") if parent_revision else self.root / "policies/rev1xx-validation.json"
            if parent_revision is not None:
                parent_campaign_state = dict(parent)
                parent_campaign_state.pop("succession_event_sha256", None)
                parent_state_digest = _digest(parent_campaign_state)
                proposal_with_parent_state["predecessor_campaign_state_sha256"] = parent_state_digest
                proposal_with_parent_state["predecessor_project_record_sha256"] = hashlib.sha256(parent_record_raw).hexdigest()
                proposal_with_parent_state["predecessor_validation_policy_sha256"] = hashlib.sha256(predecessor_policy_path.read_bytes()).hexdigest()
                if (owner_authorization.get("predecessor_campaign_state_sha256") != parent_state_digest
                        or owner_authorization.get("predecessor_project_record_sha256") != proposal_with_parent_state["predecessor_project_record_sha256"]
                        or owner_authorization.get("predecessor_validation_policy_sha256") != proposal_with_parent_state["predecessor_validation_policy_sha256"]):
                    raise SuccessionProposalBlocked("owner authorization does not bind the active predecessor campaign, record, and policy snapshots")
            if ("predecessor_project_record_sha256" in proposal_with_parent_state
                    and (owner_authorization.get("predecessor_project_record_sha256") != proposal_with_parent_state["predecessor_project_record_sha256"]
                         or owner_authorization.get("predecessor_validation_policy_sha256") != proposal_with_parent_state["predecessor_validation_policy_sha256"])):
                raise SuccessionProposalBlocked("owner authorization does not bind predecessor project and policy snapshots")
            if parent_revision is None and "predecessor_campaign_state_sha256" in proposal_with_parent_state:
                raise SuccessionProposalBlocked("legacy predecessor cannot be assigned a fabricated campaign state digest")
            if parent_revision is None:
                proposal_with_parent_state["predecessor_project_record_sha256"] = hashlib.sha256(parent_record_raw).hexdigest()
                proposal_with_parent_state["predecessor_validation_policy_sha256"] = hashlib.sha256(predecessor_policy_path.read_bytes()).hexdigest()
                if (owner_authorization.get("predecessor_project_record_sha256") != proposal_with_parent_state["predecessor_project_record_sha256"]
                        or owner_authorization.get("predecessor_validation_policy_sha256") != proposal_with_parent_state["predecessor_validation_policy_sha256"]):
                    raise SuccessionProposalBlocked("owner authorization does not bind the predecessor record and policy snapshots")
            parent_view = _predecessor_identity_view(parent, parent_record_raw,
                owner_authorization["predecessor_project_record_sha256"])
            planned = prepare_successor_event(
                history=state["events"], predecessor_campaign=parent_view,
                predecessor_raw_sha256=parent_digest, proposal=proposal_with_parent_state,
                owner_authorization=owner_authorization,
                verify_owner_authorization=lambda row: (
                    row.get("authorization_id") == verification["authorization_id"]
                    and row.get("issuer") == verification["issuer"]
                ),
            )["event"]
            revision_root = Path(".agentic_engineering_os_px/project-revisions") / project_id
            predecessor_root = Path("evidence/project-revision-succession") / parent["campaign_id"] / parent_digest
            predecessor_campaign_archive = self.root / predecessor_root / "repair-campaign.json"
            predecessor_record_archive = self.root / predecessor_root / "project-record.json"
            if predecessor_campaign_archive.exists() and predecessor_campaign_archive.read_bytes() != parent_raw:
                raise SuccessionProposalBlocked("immutable predecessor campaign archive conflicts")
            if predecessor_record_archive.exists() and predecessor_record_archive.read_bytes() != parent_record_raw:
                raise SuccessionProposalBlocked("immutable predecessor record archive conflicts")
            predecessor_policy_path = (parent_revision / "validation-policy.json") if parent_revision else self.root / "policies/rev1xx-validation.json"
            predecessor_policy_archive = self.root / predecessor_root / "validation-policy.json"
            if predecessor_policy_archive.exists() and predecessor_policy_archive.read_bytes() != predecessor_policy_path.read_bytes():
               raise SuccessionProposalBlocked("immutable predecessor validation policy archive conflicts")
            predecessor_policy_raw = predecessor_policy_path.read_bytes()
            predecessor_policy_sha = hashlib.sha256(predecessor_policy_raw).hexdigest()
            predecessor_record_sha = hashlib.sha256(parent_record_raw).hexdigest()
            revision_record = {**parent_record, "project_id": project_id}
            validation_policy["revision_succession"] = {
                "event_sha256": "0" * 64,
                "predecessor_campaign_id": parent["campaign_id"],
                "predecessor_raw_sha256": parent_digest,
                "predecessor_campaign_state_sha256": proposal_with_parent_state.get("predecessor_campaign_state_sha256"),
                "predecessor_project_record_sha256": predecessor_record_sha,
                "predecessor_validation_policy_sha256": predecessor_policy_sha,
            }
            # The signed owner authorization is already bound to this exact candidate event hash.
            # Activation is represented by the active pointer; do not rewrite the signed event/hash.
            activated_event = planned
            campaign = {
                "schema_version": "px.repair-campaign/1.0", "project_id": project_id,
                "campaign_id": campaign_id, "phase": "intake", "intake_open": True,
                "unresolved": list(intake_findings),
                "revision_parent_campaign_id": parent["campaign_id"],
                "revision_parent_sha256": parent_digest,
                "succession_event_sha256": activated_event["event_sha256"],
            }
            validation_policy["revision_succession"]["event_sha256"] = activated_event["event_sha256"]
            validation_policy["revision_succession"]["campaign_state_sha256"] = hashlib.sha256(release_signing.canonical_bytes(campaign)).hexdigest()
            campaign_bytes = release_signing.canonical_bytes(campaign)
            policy_bytes = release_signing.canonical_bytes(validation_policy)
            record_bytes = release_signing.canonical_bytes(revision_record)
            pointer = {
                "schema_version": "px.active-project-revision/1.0", "project_id": project_id,
                "revision_root": revision_root.as_posix(), "event_sha256": activated_event["event_sha256"],
                "campaign_sha256": hashlib.sha256(campaign_bytes).hexdigest(),
                "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
                "project_record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            }
            after = {"schema_version": STATE_SCHEMA, "events": [*state["events"], activated_event]}
            planned = activated_event
            targets = [
                self.state_path,
                self.root / revision_root / "repair-campaign.json",
                self.root / revision_root / "validation-policy.json",
                self.root / revision_root / "project-record.json",
                self.root / ACTIVE_REVISION_PATH,
            ]
            if not predecessor_campaign_archive.exists():
                targets.append(predecessor_campaign_archive)
            if not predecessor_record_archive.exists():
                targets.append(predecessor_record_archive)
            if not predecessor_policy_archive.exists():
                targets.append(predecessor_policy_archive)
            if any(path.exists() for path in targets[1:5]):
                raise SuccessionProposalBlocked("successor revision namespace already exists")
            expected_before = {path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None for path in targets}
            result = self.wal.commit([
                JsonArtifact("event", targets[0], after),
                JsonArtifact("state", targets[1], campaign),
                JsonArtifact("state", targets[2], validation_policy),
                JsonArtifact("state", targets[3], revision_record),
                JsonArtifact("projection", targets[4], pointer),
                *([BytesArtifact("receipt", predecessor_campaign_archive, parent_raw)] if not predecessor_campaign_archive.exists() else []),
                *([BytesArtifact("receipt", predecessor_record_archive, parent_record_raw)] if not predecessor_record_archive.exists() else []),
                *([BytesArtifact("receipt", predecessor_policy_archive, predecessor_policy_path.read_bytes())] if not predecessor_policy_archive.exists() else []),
            ], transaction_id="succession-" + planned["event_sha256"][:32],
                expected_before=expected_before, fault_injector=fault_injector)
            selected = current_revision_root(self.root)
            if selected != (self.root / revision_root).resolve():
                raise SuccessionProposalBlocked("transaction did not publish the verified active revision")
            if (self.root / PROJECT_RECORD_PATH).read_bytes() != root_record_raw or parent_record_path.read_bytes() != parent_record_raw or parent_campaign_path.read_bytes() != parent_raw:
                raise SuccessionProposalBlocked("predecessor project or campaign bytes changed during successor publication")
            return {"valid": True, "activated": True, "event": planned,
                    "active_revision_root": revision_root.as_posix(), "transaction": result,
                    "predecessor_campaign_id": parent["campaign_id"], "root_project_record_id": marker.get("project_id")}

    def simulate(
        self, *, history: list[Mapping[str, Any]], predecessor_campaign: Mapping[str, Any],
        predecessor_raw_sha256: str, proposal: Mapping[str, Any],
        owner_authorization: Mapping[str, Any], verify_authorization: Callable[[Mapping[str, Any]], bool],
    ) -> dict[str, Any]:
        # Pure non-production simulation; deliberately performs no writes.
        event = prepare_successor_event(
            history=history, predecessor_campaign=predecessor_campaign,
            predecessor_raw_sha256=predecessor_raw_sha256, proposal=proposal,
            owner_authorization=owner_authorization,
            verify_owner_authorization=verify_authorization,
        )["event"]
        return {"valid": True, "simulated": True, "activated": False, "event_candidate": event}


def _guard_succession_effect(root: Path, admission_event_id: str, effect: str) -> None:
    from .operational_gap_ledger import guard_work_admission, read_snapshot
    snapshot = read_snapshot(root)
    checkpoints = snapshot.get("work_checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise SuccessionProposalBlocked("current operational checkpoint is missing")
    admission = next((item for item in snapshot.get("work_admissions", [])
                      if isinstance(item, Mapping) and item.get("event_id") == admission_event_id), None)
    if admission is None:
        raise SuccessionProposalBlocked("succession work admission is absent")
    effect_scope = next((item.get("scope") for item in admission.get("effect_scopes", [])
                         if isinstance(item, Mapping) and item.get("effect") == effect), None)
    try:
        guard_work_admission(snapshot, gap_id=checkpoints[-1].get("active_gap_id"),
                             effect=effect, scope=effect_scope,
                             admission_event_id=admission_event_id)
    except (ValueError, TypeError, KeyError) as error:
        raise SuccessionProposalBlocked(f"succession {effect} admission denied") from error

def validate_history(events: object) -> dict[str, Any]:
    if type(events) is not list or len(events) > 100_000:
        raise SuccessionProposalBlocked("succession event history is malformed or over budget")
    previous = "0" * 64
    seen_event_hashes: set[str] = set()
    seen_ids: set[str] = set()
    seen_projects: set[str] = set()
    seen_campaigns: set[str] = set()
    seen_predecessors: set[str] = set()
    latest_activated: Mapping[str, Any] | None = None
    for sequence, event in enumerate(events, start=1):
        if type(event) is not dict:
            raise SuccessionProposalBlocked("succession event must be an object")
        body = {key: value for key, value in event.items() if key != "event_sha256"}
        digest = _digest(body)
        binding = event.get("binding")
        if (
            event.get("schema_version") != SCHEMA
            or event.get("sequence") != sequence
            or event.get("previous_event_sha256") != previous
            or event.get("event_sha256") != digest
            or type(binding) is not dict
            or type(event.get("authorization")) is not dict
            or event.get("event_status") not in {"proposed", "activated"}
            or set(event) != {"schema_version", "sequence", "previous_event_sha256", "binding", "binding_sha256", "authorization", "event_status", "event_sha256"}
            or event.get("binding_sha256") != _digest(binding)
        ):
            raise SuccessionProposalBlocked("succession event chain or binding is corrupt")
        allowed_binding_fields = {
            "schema_version", "successor_project_id", "successor_campaign_id",
            "predecessor_campaign_id", "predecessor_raw_sha256", "source_tree_sha256",
            "owner_policy_id", "authorization_id", "authority_ref", "authorization_sha256",
        }
        expanded_binding_fields = allowed_binding_fields | {"predecessor_campaign_state_sha256", "predecessor_project_record_sha256", "predecessor_validation_policy_sha256"}
        revision_binding_fields = allowed_binding_fields | {"predecessor_campaign_state_sha256"}
        legacy_snapshot_fields = allowed_binding_fields | {"predecessor_project_record_sha256", "predecessor_validation_policy_sha256"}
        if set(binding) not in (allowed_binding_fields, revision_binding_fields, expanded_binding_fields, legacy_snapshot_fields):
            raise SuccessionProposalBlocked("succession event binding fields are not exact")
        if "predecessor_campaign_state_sha256" in binding:
            _sha256(binding["predecessor_campaign_state_sha256"], "history predecessor campaign state hash")
        if "predecessor_project_record_sha256" in binding:
            _sha256(binding["predecessor_project_record_sha256"], "history predecessor project-record hash")
            _sha256(binding["predecessor_validation_policy_sha256"], "history predecessor validation-policy hash")
        authorization_id = _identifier(binding.get("authorization_id"), "authorization_id")
        project_id = _identifier(binding.get("successor_project_id"), "successor_project_id")
        campaign_id = _identifier(binding.get("successor_campaign_id"), "successor_campaign_id")
        predecessor_id = _identifier(binding.get("predecessor_campaign_id"), "predecessor_campaign_id")
        event_identity = _sha256(event.get("event_sha256"), "history event identity")
        _sha256(binding.get("predecessor_raw_sha256"), "history predecessor hash")
        _sha256(binding.get("source_tree_sha256"), "history source hash")
        _sha256(binding.get("authorization_sha256"), "history authorization hash")
        _identifier(binding.get("owner_policy_id"), "history policy ID")
        _identifier(binding.get("authority_ref"), "history authority ref")
        authorization = event["authorization"]
        if authorization.get("decision") != "approved" or authorization.get("revoked") is not False or authorization.get("revocation_status") != "not_revoked":
            raise SuccessionProposalBlocked("historical authorization is not an unrevoked approval")
        if (authorization.get("authorization_id") != authorization_id
                or authorization.get("successor_project_id") != project_id
                or authorization.get("successor_campaign_id") != campaign_id
                or authorization.get("predecessor_campaign_id") != predecessor_id
                or authorization.get("predecessor_raw_sha256") != binding["predecessor_raw_sha256"]
                or authorization.get("source_tree_sha256") != binding["source_tree_sha256"]
                or authorization.get("owner_policy_id") != binding["owner_policy_id"]
                or _digest(authorization) != binding["authorization_sha256"]
                or ("predecessor_campaign_state_sha256" in binding
                    and authorization.get("predecessor_campaign_state_sha256") != binding["predecessor_campaign_state_sha256"])):
            raise SuccessionProposalBlocked("authorization does not match immutable event binding")
        if (event_identity in seen_event_hashes or authorization_id in seen_ids
                or project_id in seen_projects or campaign_id in seen_campaigns
                or event["event_status"] == "activated" and predecessor_id in seen_predecessors
                or event["event_status"] == "activated" and predecessor_id in seen_campaigns
                or event["event_status"] == "activated" and latest_activated is not None
                and predecessor_id != latest_activated["binding"]["successor_campaign_id"]):
            raise SuccessionProposalBlocked("succession event history contains replay or activated predecessor fork")
        seen_event_hashes.add(event_identity)
        seen_ids.add(authorization_id)
        seen_projects.add(project_id)
        seen_campaigns.add(campaign_id)
        if event["event_status"] == "activated":
            seen_predecessors.add(predecessor_id)
            latest_activated = event
        previous = digest
    return {"event_count": len(events), "tail_sha256": previous}

