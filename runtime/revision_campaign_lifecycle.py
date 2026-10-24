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

def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')

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
    root = Path(root).resolve(strict=True)
    _, campaign, pointer = _load_revision(root)
    unresolved = campaign.get("unresolved")
    if (campaign.get("schema_version") != "px.repair-campaign/1.0"
            or not isinstance(unresolved, list)
            or any(type(item) is not str or not item.strip() for item in unresolved)
            or len(unresolved) != len(set(unresolved))):
        raise RevisionCampaignBlocked("active revision campaign is malformed")
    return {
        "valid": True,
        "project_id": campaign["project_id"],
        "campaign_id": campaign["campaign_id"],
        "phase": campaign.get("phase"),
        "intake_open": campaign.get("intake_open"),
        "unresolved": list(unresolved),
        "revision_event_sha256": pointer["event_sha256"],
        "blocked_stages": [] if campaign.get("phase") == "repair" and campaign.get("intake_open") else ["repair"],
    }


def begin_repair(root: Path, *, admission_event_id: str) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    try:
        _guard_succession_effect(root, admission_event_id, "write")
    except (SuccessionProposalBlocked, OSError, ValueError) as error:
        raise RevisionCampaignBlocked("repair transition lacks a current scoped admission") from error
    lock = root / ".agentic_engineering_os_px/project-revision-succession/activation.lock"
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
    wal = JsonWal(Path(".agentic_engineering_os_px/project-revision-succession/wal"), root)
    policy_path = campaign_path.parent / "validation-policy.json"
    policy_before = policy_path.read_bytes()
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
    campaign_bytes = _canonical(state)
    policy_binding["campaign_state_sha256"] = hashlib.sha256(campaign_bytes).hexdigest()
    policy_bytes = _canonical(policy)
    pointer["campaign_sha256"] = hashlib.sha256(campaign_bytes).hexdigest()
    pointer["policy_sha256"] = hashlib.sha256(policy_bytes).hexdigest()
    pointer_path = root / ACTIVE_REVISION_PATH
    expected = {
        campaign_path.relative_to(root).as_posix(): hashlib.sha256(before).hexdigest(),
        policy_path.relative_to(root).as_posix(): hashlib.sha256(policy_before).hexdigest(),
        pointer_path.relative_to(root).as_posix(): hashlib.sha256(pointer_path.read_bytes()).hexdigest(),
    }
    wal.commit(
        [JsonArtifact("state", campaign_path, state), JsonArtifact("state", policy_path, policy), JsonArtifact("projection", pointer_path, pointer)],
        transaction_id="campaign-transition-" + hashlib.sha256((admission_event_id + expected[campaign_path.relative_to(root).as_posix()]).encode()).hexdigest()[:24],
        expected_before=expected,
    )
    current_revision_root(root)


def _mutate(root: Path, *, admission_event_id: str, mutation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    try:
        _guard_succession_effect(root, admission_event_id, "write")
    except (SuccessionProposalBlocked, OSError, ValueError) as error:
        raise RevisionCampaignBlocked("revision campaign mutation lacks a current scoped write admission") from error
    lock = root / ".agentic_engineering_os_px/project-revision-succession/activation.lock"
    with FileLock(lock, timeout_seconds=10.0):
        campaign_path, _, pointer = _load_revision(root)
        wal = JsonWal(Path(".agentic_engineering_os_px/project-revision-succession/wal"), root)
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
        artifacts = [JsonArtifact("state", campaign_path, state)]
        policy_path = campaign_path.parent / "validation-policy.json"
        policy_before = policy_path.read_bytes()
        policy = json.loads(policy_before)
        policy_binding = policy.get("revision_succession")
        if not isinstance(policy_binding, dict):
            raise RevisionCampaignBlocked("revision validation policy lacks succession binding")
        policy_binding["campaign_state_sha256"] = hashlib.sha256(_canonical(state)).hexdigest()
        policy_bytes = _canonical(policy)
        artifacts.append(JsonArtifact("state", policy_path, policy))
        pointer["campaign_sha256"] = hashlib.sha256(_canonical(state)).hexdigest()
        pointer["policy_sha256"] = hashlib.sha256(policy_bytes).hexdigest()
        artifacts.append(JsonArtifact("projection", root / ACTIVE_REVISION_PATH, pointer))
        before_images = {
            campaign_path.relative_to(root).as_posix(): before_sha,
            policy_path.relative_to(root).as_posix(): hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            (root / ACTIVE_REVISION_PATH).relative_to(root).as_posix(): hashlib.sha256((root / ACTIVE_REVISION_PATH).read_bytes()).hexdigest(),
        }
        wal.commit(artifacts, transaction_id=f"campaign-{mutation}-{hashlib.sha256((admission_event_id+before_sha).encode()).hexdigest()[:24]}", expected_before=before_images)
        current_revision_root(root)
    return status(root)


def register_findings(root: Path, *, finding_ids: list[str], admission_event_id: str) -> dict[str, Any]:
    return _mutate(root, admission_event_id=admission_event_id, mutation="register", payload={"finding_ids": finding_ids})


def resolve_findings(root: Path, *, evidence_by_finding: Mapping[str, str], admission_event_id: str) -> dict[str, Any]:
    return _mutate(root, admission_event_id=admission_event_id, mutation="resolve", payload={"evidence_by_finding": dict(evidence_by_finding)})
