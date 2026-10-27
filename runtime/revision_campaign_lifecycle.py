"Transactional mutation owner for revision-scoped repair campaigns."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from .file_lock import FileLock
from .project_revision_succession import (
    ACTIVE_REVISION_PATH,
    SuccessionProposalBlocked,
    _guard_succession_effect,
    current_revision_root,
)
from .wal_transaction import JsonArtifact, JsonWal
from .json_io import bounded_canonical_json_bytes

def _canonical(value: object) -> bytes:
    # Hash the exact native WAL wire image, including its trailing newline.
    return bounded_canonical_json_bytes(value, max_bytes=64 * 1024 * 1024)

class RevisionCampaignBlocked(ValueError):
    pass


def _load_revision(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    revision = current_revision_root(root)
    if revision is None:
        raise RevisionCampaignBlocked("legacy project has no active successor revision")
    pointer = json.loads((root / ACTIVE_REVISION_PATH).read_text(encoding="utf-8"))
    campaign_path = revision / "repair-campaign.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign.get("project_id") != pointer.get("project_id"):
        raise RevisionCampaignBlocked("campaign does not match active revision")
    return campaign_path, campaign, pointer

def status(root: Path) -> dict[str, Any]:
    from .test_profiles import repair_campaign_status
    root = Path(root).resolve(strict=True)
    _, campaign, pointer = _load_revision(root)
    unresolved = campaign.get("unresolved")
    if (campaign.get("schema_version") != "px.repair-campaign/1.0"
            or not isinstance(unresolved, list)
            or any(type(item) is not str or not item.strip() for item in unresolved)
            or len(unresolved) != len(set(unresolved))):
        raise RevisionCampaignBlocked("active revision campaign is malformed")
    return {
        **repair_campaign_status(root),
        "project_id": campaign["project_id"],
        "campaign_id": campaign["campaign_id"],
        "phase": campaign.get("phase"),
        "intake_open": campaign.get("intake_open"),
        "unresolved": list(unresolved),
        "revision_event_sha256": pointer["event_sha256"],
    }


def begin_repair(root: Path, *, admission_event_id: str) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    try:
        _guard_succession_effect(root, admission_event_id, "write")
    except (SuccessionProposalBlocked, OSError, ValueError) as error:
        raise RevisionCampaignBlocked("repair transition lacks a current scoped admission") from error
    lock = root / ".engineering-bootstrap/project-revision-succession/activation.lock"
    with FileLock(lock, timeout_seconds=10.0):
        campaign_path, _, pointer = _load_revision(root)
        before = campaign_path.read_bytes()
        state = json.loads(before)
        if hashlib.sha256(before).hexdigest() != pointer["campaign_sha256"]:
            raise RevisionCampaignBlocked("campaign bytes differ from active revision pointer")
        if state.get("phase") != "intake" or state.get("intake_open") is not True or not state.get("unresolved"):
            raise RevisionCampaignBlocked("repair transition requires open intake and a nonempty denominator")
        state["phase"] = "repair"
        history = state.setdefault("phase_history", [])
        if not isinstance(history, list):
            raise RevisionCampaignBlocked("campaign phase history is malformed")
        history.append({"from": "intake", "to": "repair", "prior_state_sha256": hashlib.sha256(before).hexdigest(), "admission_event_id": admission_event_id, "unresolved": list(state["unresolved"])})
        _publish_campaign_update(root, campaign_path, state, pointer, admission_event_id, before)
    return status(root)


def _publish_campaign_update(root: Path, campaign_path: Path, state: dict[str, Any], pointer: dict[str, Any], admission_event_id: str, before: bytes) -> None:
    wal = JsonWal(Path(".engineering-bootstrap/project-revision-succession/wal"), root)
    policy_path = campaign_path.parent / "validation-policy.json"
    policy_before = policy_path.read_bytes()
    pointer_path = root / ACTIVE_REVISION_PATH
    pointer_before = pointer_path.read_bytes()
    if (json.loads(pointer_before) != pointer
            or hashlib.sha256(policy_before).hexdigest() != pointer["policy_sha256"]
            or hashlib.sha256(before).hexdigest() != pointer["campaign_sha256"]):
        raise RevisionCampaignBlocked("revision before-images changed before publication")
    policy = json.loads(policy_before)
    policy_binding = policy.get("revision_succession")
    if not isinstance(policy_binding, dict):
        raise RevisionCampaignBlocked("validation policy lacks revision succession binding")
    try:
        if wal._pending_transactions():
            raise RevisionCampaignBlocked("succession WAL recovery must be completed before campaign publication")
        wal.inspect()
    except RevisionCampaignBlocked:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        raise RevisionCampaignBlocked("succession WAL is corrupt or requires recovery") from error
    _guard_succession_effect(root, admission_event_id, "write")
    campaign_bytes = _canonical(state)
    policy_binding["campaign_state_sha256"] = hashlib.sha256(campaign_bytes).hexdigest()
    policy_bytes = _canonical(policy)
    pointer = dict(pointer)
    pointer["campaign_sha256"] = hashlib.sha256(campaign_bytes).hexdigest()
    pointer["policy_sha256"] = hashlib.sha256(policy_bytes).hexdigest()
    expected = {
        campaign_path.relative_to(root).as_posix(): hashlib.sha256(before).hexdigest(),
        policy_path.relative_to(root).as_posix(): hashlib.sha256(policy_before).hexdigest(),
        pointer_path.relative_to(root).as_posix(): hashlib.sha256(pointer_before).hexdigest(),
    }
    wal.commit(
        [JsonArtifact("state", campaign_path, state), JsonArtifact("state", policy_path, policy), JsonArtifact("projection", pointer_path, pointer)],
        transaction_id="campaign-transition-" + hashlib.sha256((admission_event_id + expected[campaign_path.relative_to(root).as_posix()]).encode()).hexdigest()[:24],
        expected_before=expected,
    )
    current_revision_root(root)


def _transition(root: Path, *, admission_event_id: str, transition: str,
                closure_authority: str = "", evidence_path: str = "") -> dict[str, Any]:
    """Publish phase, validation binding and active pointer as one WAL transaction."""
    from .test_profiles import prepare_intake_closure, prepare_repair_freeze
    root = Path(root).resolve(strict=True)
    _guard_succession_effect(root, admission_event_id, "write")
    lock = root / ".engineering-bootstrap/project-revision-succession/activation.lock"
    with FileLock(lock, timeout_seconds=10.0):
        campaign_path, _, pointer = _load_revision(root)
        before = campaign_path.read_bytes()
        if transition == "close_intake":
            state = prepare_intake_closure(before, admission_event_id=admission_event_id,
                                           closure_authority=closure_authority)
        elif transition == "freeze_repair":
            state = prepare_repair_freeze(root, campaign_path, before,
                                          admission_event_id=admission_event_id,
                                          evidence_path=evidence_path)
        else:
            raise RevisionCampaignBlocked("unknown revision phase transition")
        _publish_campaign_update(root, campaign_path, state, pointer, admission_event_id, before)
    return status(root)


def close_intake(root: Path, *, admission_event_id: str, closure_authority: str) -> dict[str, Any]:
    return _transition(root, admission_event_id=admission_event_id, transition="close_intake",
                       closure_authority=closure_authority)


def freeze_repair(root: Path, *, admission_event_id: str, evidence_path: str) -> dict[str, Any]:
    return _transition(root, admission_event_id=admission_event_id, transition="freeze_repair",
                       evidence_path=evidence_path)


def _mutate(root: Path, *, admission_event_id: str, mutation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    try:
        _guard_succession_effect(root, admission_event_id, "write")
    except (SuccessionProposalBlocked, OSError, ValueError) as error:
        raise RevisionCampaignBlocked("revision campaign mutation lacks a current scoped write admission") from error
    lock = root / ".engineering-bootstrap/project-revision-succession/activation.lock"
    with FileLock(lock, timeout_seconds=10.0):
        campaign_path, _, pointer = _load_revision(root)
        wal = JsonWal(Path(".engineering-bootstrap/project-revision-succession/wal"), root)
        try:
            if wal._pending_transactions():
                raise RevisionCampaignBlocked("succession WAL recovery must be completed before campaign mutation")
            wal.inspect()
        except RevisionCampaignBlocked:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            raise RevisionCampaignBlocked("succession WAL is corrupt or requires recovery") from error
        before = campaign_path.read_bytes()
        before_sha = hashlib.sha256(before).hexdigest()
        state = json.loads(before)
        if before_sha != pointer["campaign_sha256"]:
            raise RevisionCampaignBlocked("campaign bytes differ from the active pointer")
        if mutation == "register":
            findings = payload.get("finding_ids")
            if (not isinstance(findings, list) or not findings or any(type(item) is not str or not item.strip() for item in findings)
                    or len(findings) != len(set(findings)) or set(findings) & set(state.get("unresolved", []))
                    or state.get("intake_open") is not True or state.get("phase") not in {"intake", "repair"}):
                raise RevisionCampaignBlocked("registered findings must be unique and new")
            state["unresolved"] = [*state.get("unresolved", []), *findings]
        elif mutation == "resolve":
            evidence = payload.get("evidence_by_finding")
            unresolved = state.get("unresolved", [])
            if (not isinstance(evidence, Mapping) or not evidence
                    or any(type(key) is not str or not key.strip() or type(value) is not str or not value.strip() for key, value in evidence.items())
                    or not set(evidence).issubset(unresolved)
                    or state.get("intake_open") is not True or state.get("phase") != "repair"):
                raise RevisionCampaignBlocked("resolution evidence must cover currently unresolved findings")
            state["unresolved"] = [finding for finding in unresolved if finding not in evidence]
        else:
            raise RevisionCampaignBlocked("unknown revision campaign mutation")
        history = state.setdefault("finding_history", [])
        if not isinstance(history, list):
            raise RevisionCampaignBlocked("revision finding history is malformed")
        history.append({
            "mutation": mutation,
            "prior_campaign_sha256": before_sha,
            "admission_event_id": admission_event_id,
            **dict(payload),
        })
        _publish_campaign_update(root, campaign_path, state, pointer, admission_event_id, before)
    return status(root)


def register_findings(root: Path, *, finding_ids: list[str], admission_event_id: str) -> dict[str, Any]:
    return _mutate(root, admission_event_id=admission_event_id, mutation="register", payload={"finding_ids": finding_ids})


def resolve_findings(root: Path, *, evidence_by_finding: Mapping[str, str], admission_event_id: str) -> dict[str, Any]:
    return _mutate(root, admission_event_id=admission_event_id, mutation="resolve", payload={"evidence_by_finding": dict(evidence_by_finding)})
