"""One-identity, one-attempt release-campaign state.

This is the mutable control-plane pointer for a certification campaign.  Failed
historical evidence remains immutable, while this file says which single source
identity (if any) is allowed to advance now.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .release_artifacts import classify_tree
from .release_identity import authoritative_version


STATE_PATH = Path(".engineering-bootstrap/processing-order/release-identity.json")
FAILED_IDENTITY_ARCHIVE_ROOT = Path("evidence/release")
REPAIR_CAMPAIGN_PATH = Path(
    ".engineering-bootstrap/processing-order/repair-campaign.json"
)
STAGES = (
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
    "installed_operational",
    "certify",
)
STAGE_PHASES = {
    "sections": "revision_reconciled",
    "full_profile": "sections_current",
    "validate": "full_profile_passed",
    "package": "validated",
    "install": "packaged",
    "installed_operational": "installed",
    "certify": "installed_operational",
}
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
PRE_IDENTITY_FAILURE_SCHEMA = "px.pre-identity-owner-failure/1.0"


class ReleaseCampaignBlocked(ValueError):
    """Raised when a release identity or stage would be replayed or skipped."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_pre_identity_failure(value: object, campaign_id: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema_version") == PRE_IDENTITY_FAILURE_SCHEMA
        and value.get("campaign_id") == campaign_id
        and value.get("owner") in {"archive_clear", "reconcile"}
        and value.get("status") == "failed"
        and value.get("attempt_count") == 1
        and bool(str(value.get("error") or "").strip())
        and bool(str(value.get("recorded_at") or "").strip())
    )


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ReleaseCampaignBlocked("release campaign parent must not be a symlink")
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.new")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _repair_campaign(root: Path) -> dict[str, Any]:
    path = root / REPAIR_CAMPAIGN_PATH
    if not path.is_file():
        raise ReleaseCampaignBlocked("managed repair campaign is missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not str(value.get("campaign_id") or ""):
        raise ReleaseCampaignBlocked("managed repair campaign is malformed")
    return value


def _validate(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseCampaignBlocked("release campaign state must be an object")
    stages = value.get("stages")
    if (
        value.get("schema_version") != "px.release-campaign/1.0"
        or not str(value.get("campaign_id") or "")
        or not str(value.get("repair_campaign_id") or "")
        or value.get("state") not in {"cleared", "active", "failed", "certified"}
        or not isinstance(value.get("apply_count"), int)
        or value["apply_count"] not in {0, 1}
        or not isinstance(stages, dict)
        or set(stages) != set(STAGES)
        or any(
            not isinstance(stages[name], dict)
            or stages[name].get("status")
            not in {"pending", "claimed", "passed", "failed"}
            for name in STAGES
        )
    ):
        raise ReleaseCampaignBlocked("release campaign state is malformed")
    identity = value.get("identity")
    pre_identity_failure = value.get("pre_identity_failure")
    if pre_identity_failure is not None and not _valid_pre_identity_failure(
        pre_identity_failure, str(value["campaign_id"])
    ):
        raise ReleaseCampaignBlocked("pre-identity failure marker is malformed")
    if value["state"] == "cleared":
        if (
            value["apply_count"] != 0
            or identity is not None
            or value.get("active_claim") is not None
            or any(stages[name]["status"] != "pending" for name in STAGES)
        ):
            raise ReleaseCampaignBlocked("cleared release campaign retains identity state")
    elif (
        value["apply_count"] != 1
        or not isinstance(identity, dict)
        or identity.get("schema_version") != "px.release-identity-kernel/2.0"
        or identity.get("campaign_id") != value["campaign_id"]
        or identity.get("repair_campaign_id") != value["repair_campaign_id"]
        or not SHA256_PATTERN.fullmatch(
            str(identity.get("release_identity_sha256") or "")
        )
        or _sha(
            {
                key: item
                for key, item in identity.items()
                if key != "release_identity_sha256"
            }
        )
        != identity.get("release_identity_sha256")
    ):
        raise ReleaseCampaignBlocked("active release campaign identity is malformed")
    if value["state"] != "cleared":
        statuses = [stages[name]["status"] for name in STAGES]
        claimed = [index for index, status in enumerate(statuses) if status == "claimed"]
        failed = [index for index, status in enumerate(statuses) if status == "failed"]
        active_claim = value.get("active_claim")
        if value["state"] == "active":
            if failed or len(claimed) > 1:
                raise ReleaseCampaignBlocked("active release campaign stage state is malformed")
            if not claimed and "pending" not in statuses:
                raise ReleaseCampaignBlocked("active release campaign has no pending stage")
            boundary = claimed[0] if claimed else statuses.index("pending") if "pending" in statuses else len(STAGES)
            if any(status != "passed" for status in statuses[:boundary]) or any(
                status != "pending" for status in statuses[boundary + bool(claimed) :]
            ):
                raise ReleaseCampaignBlocked("active release campaign stages are out of order")
            if claimed:
                stage = STAGES[claimed[0]]
                if (
                    not isinstance(active_claim, dict)
                    or active_claim.get("stage") != stage
                    or active_claim.get("claim_id") != stages[stage].get("claim_id")
                ):
                    raise ReleaseCampaignBlocked("active release stage claim is malformed")
            elif active_claim is not None:
                raise ReleaseCampaignBlocked("release campaign has an unbound active claim")
        elif value["state"] == "failed":
            if len(failed) != 1 or claimed or active_claim is not None:
                raise ReleaseCampaignBlocked("failed release campaign stage state is malformed")
            boundary = failed[0]
            if any(status != "passed" for status in statuses[:boundary]) or any(
                status != "pending" for status in statuses[boundary + 1 :]
            ):
                raise ReleaseCampaignBlocked("failed release campaign stages are out of order")
        elif (
            value["state"] != "certified"
            or any(status != "passed" for status in statuses)
            or active_claim is not None
        ):
            raise ReleaseCampaignBlocked("certified release campaign stage state is malformed")
    return value


def cleared_campaign_can_be_superseded(value: object) -> bool:
    """Require a terminal marker before chaining a pre-identity successor."""

    try:
        campaign = _validate(value)
    except ReleaseCampaignBlocked:
        return False
    if (
        campaign.get("state") != "cleared"
        or campaign.get("apply_count") != 0
        or campaign.get("identity") is not None
        or campaign.get("active_claim") is not None
    ):
        return False
    if campaign.get("pre_identity_reconciliation_successor") is not True:
        return True
    return _valid_pre_identity_failure(
        campaign.get("pre_identity_failure"), str(campaign["campaign_id"])
    )


def mark_pre_identity_owner_failure(
    root: Path, *, campaign_id: str, owner: str, error: str
) -> dict[str, Any]:
    """Durably mark one failed pre-identity owner without replaying its campaign."""

    root = root.resolve(strict=True)
    candidate = campaign_id.strip()
    owner_name = owner.strip()
    explanation = error.strip()
    if owner_name not in {"archive_clear", "reconcile"} or not explanation:
        raise ReleaseCampaignBlocked("pre-identity failure marker is incomplete")
    path = root / STATE_PATH
    value = _validate(json.loads(path.read_text(encoding="utf-8")))
    if (
        value.get("campaign_id") != candidate
        or value.get("state") != "cleared"
        or value.get("apply_count") != 0
        or value.get("identity") is not None
        or value.get("active_claim") is not None
    ):
        raise ReleaseCampaignBlocked(
            "pre-identity failure marker requires the exact current cleared campaign"
        )
    marker = {
        "schema_version": PRE_IDENTITY_FAILURE_SCHEMA,
        "campaign_id": candidate,
        "owner": owner_name,
        "status": "failed",
        "attempt_count": 1,
        "error": explanation,
        "recorded_at": _now(),
    }
    existing = value.get("pre_identity_failure")
    if existing is not None:
        comparable = {key: existing.get(key) for key in marker if key != "recorded_at"}
        expected = {key: item for key, item in marker.items() if key != "recorded_at"}
        if comparable != expected:
            raise ReleaseCampaignBlocked("pre-identity failure marker is already bound")
        return {"valid": True, "marker": existing, "changed": False}
    value["pre_identity_failure"] = marker
    _write(path, value)
    return {"valid": True, "marker": marker, "changed": True}


def release_campaign_status(root: Path, *, verify_source: bool = False) -> dict[str, Any]:
    root = root.resolve(strict=True)
    path = root / STATE_PATH
    if not path.is_file():
        return {
            "schema_version": "px.release-campaign-status/1.0",
            "valid": False,
            "state": "missing",
            "path": STATE_PATH.as_posix(),
            "errors": ["active release identity state is missing"],
        }
    value = _validate(json.loads(path.read_text(encoding="utf-8")))
    errors: list[str] = []
    repair = _repair_campaign(root)
    if value.get("repair_campaign_id") != repair.get("campaign_id"):
        errors.append("release identity belongs to another repair campaign")
    if verify_source and value["state"] in {"active", "certified"}:
        current = classify_tree(root)
        identity = value["identity"]
        if not current["valid"]:
            errors.extend(current["errors"])
        if current["product_digest"] != identity.get("source_product_digest"):
            errors.append("source product digest changed after release identity apply")
        if current["harness_digest"] != identity.get("source_harness_digest"):
            errors.append("certification harness digest changed after release identity apply")
    return {
        **value,
        "schema_version": "px.release-campaign-status/1.0",
        "valid": not errors,
        "path": STATE_PATH.as_posix(),
        "errors": errors,
    }


def clear_release_identity(root: Path, *, campaign_id: str) -> dict[str, Any]:
    """Create one empty campaign; never erase/reuse an already-applied campaign."""

    root = root.resolve(strict=True)
    if not campaign_id.strip():
        raise ReleaseCampaignBlocked("release campaign ID is required")
    repair = _repair_campaign(root)
    if repair.get("phase") not in {"repair", "repair_frozen"}:
        raise ReleaseCampaignBlocked(
            "release identity may be cleared only during repair or repair freeze"
        )
    path = root / STATE_PATH
    if path.is_file():
        previous = _validate(json.loads(path.read_text(encoding="utf-8")))
        same_repair = previous.get("repair_campaign_id") == repair["campaign_id"]
        if same_repair and previous.get("campaign_id") != campaign_id:
            raise ReleaseCampaignBlocked(
                "the current repair campaign already owns a release campaign"
            )
        if previous.get("campaign_id") == campaign_id:
            if previous["state"] == "cleared":
                return release_campaign_status(root)
            raise ReleaseCampaignBlocked(
                "an applied release campaign cannot be cleared and reused"
            )
    value = {
        "schema_version": "px.release-campaign/1.0",
        "campaign_id": campaign_id,
        "repair_campaign_id": repair["campaign_id"],
        "state": "cleared",
        "cleared_at": _now(),
        "applied_at": None,
        "apply_count": 0,
        "identity": None,
        "active_claim": None,
        "stages": {name: {"status": "pending", "claim_id": None} for name in STAGES},
    }
    _write(path, value)
    return release_campaign_status(root)


def apply_release_identity(root: Path) -> dict[str, Any]:
    """Apply exactly one source identity to the already-cleared campaign."""

    root = root.resolve(strict=True)
    repair = _repair_campaign(root)
    if (
        repair.get("phase") != "revision_reconciled"
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            "release identity apply requires one reconciled, zero-unresolved revision"
        )
    path = root / STATE_PATH
    value = _validate(json.loads(path.read_text(encoding="utf-8")))
    if value.get("repair_campaign_id") != repair["campaign_id"]:
        raise ReleaseCampaignBlocked("cleared identity belongs to another repair campaign")
    if value["state"] != "cleared" or value["apply_count"] != 0:
        raise ReleaseCampaignBlocked("release identity was already applied")
    classification = classify_tree(root)
    if not classification["valid"] or not classification["product_valid"]:
        raise ReleaseCampaignBlocked(
            "release source classification failed: "
            + "; ".join(classification["errors"][:8])
        )
    extension = json.loads(
        (root / "extension/package.json").read_text(encoding="utf-8")
    )
    source_manifest = classification["product_records"]
    kernel = {
        "schema_version": "px.release-identity-kernel/2.0",
        "campaign_id": value["campaign_id"],
        "repair_campaign_id": repair["campaign_id"],
        "release_version": authoritative_version(root),
        "extension_version": str(extension.get("version") or ""),
        "source_product_digest": classification["product_digest"],
        "source_harness_digest": classification["harness_digest"],
        "source_manifest_sha256": _sha(source_manifest),
        "source_file_count": len(source_manifest),
        "release_policy_sha256": classification["policy_sha256"],
    }
    value.update(
        {
            "state": "active",
            "applied_at": _now(),
            "apply_count": 1,
            "identity": {
                **kernel,
                "release_identity_sha256": _sha(kernel),
            },
        }
    )
    _write(path, value)
    return release_campaign_status(root, verify_source=True)


def supersede_invalid_release_identity(
    root: Path, *, campaign_id: str, reason: str
) -> dict[str, Any]:
    """Archive one unused invalid identity and replace it with one cleared campaign.

    This is deliberately narrower than ``clear_release_identity``: it is an
    exceptional recovery boundary for an identity that failed its own source
    coherence check before any release stage was claimed. The invalid attempt
    remains immutable evidence and neither its campaign ID nor its apply count
    is reused.
    """

    root = root.resolve(strict=True)
    replacement_id = campaign_id.strip()
    explanation = reason.strip()
    if not replacement_id or not explanation:
        raise ReleaseCampaignBlocked(
            "identity supersession requires a replacement campaign ID and reason"
        )
    repair = _repair_campaign(root)
    if (
        repair.get("phase") != "repair_frozen"
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            "identity supersession requires one frozen, zero-unresolved repair"
        )
    state_path = root / STATE_PATH
    previous = _validate(json.loads(state_path.read_text(encoding="utf-8")))
    if replacement_id == previous["campaign_id"]:
        raise ReleaseCampaignBlocked("replacement campaign ID must be new")
    if (
        previous["state"] != "active"
        or previous["apply_count"] != 1
        or previous.get("active_claim") is not None
        or any(previous["stages"][stage]["status"] != "pending" for stage in STAGES)
    ):
        raise ReleaseCampaignBlocked(
            "only an unused invalid active identity may be superseded"
        )
    verification = release_campaign_status(root, verify_source=True)
    if verification["valid"] or not verification["errors"]:
        raise ReleaseCampaignBlocked("a coherent release identity cannot be superseded")
    archive_path = root / FAILED_IDENTITY_ARCHIVE_ROOT / (
        f"failed-release-identity-{previous['campaign_id']}.json"
    )
    if archive_path.exists():
        raise ReleaseCampaignBlocked("failed identity archive already exists")
    archive = {
        "schema_version": "px.failed-release-identity/1.0",
        "superseded_at": _now(),
        "reason": explanation,
        "replacement_campaign_id": replacement_id,
        "source_verification_errors": list(verification["errors"]),
        "campaign_state": previous,
    }
    archive["archive_sha256"] = _sha(archive)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(archive, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    cleared = {
        "schema_version": "px.release-campaign/1.0",
        "campaign_id": replacement_id,
        "repair_campaign_id": repair["campaign_id"],
        "state": "cleared",
        "cleared_at": _now(),
        "applied_at": None,
        "apply_count": 0,
        "identity": None,
        "active_claim": None,
        "supersedes": {
            "campaign_id": previous["campaign_id"],
            "archive": archive_path.relative_to(root).as_posix(),
            "archive_sha256": archive["archive_sha256"],
        },
        "stages": {name: {"status": "pending", "claim_id": None} for name in STAGES},
    }
    _write(state_path, cleared)
    status = release_campaign_status(root)
    return {**status, "superseded_archive": archive_path.relative_to(root).as_posix()}


def rewind_invalid_release_identity_reconciliation(root: Path) -> dict[str, Any]:
    """Return one unused invalid identity to the frozen-repair boundary.

    A source defect can be discovered after identity apply but before the first
    release-stage claim.  Reconciliation for that identity is then stale.  This
    narrow transition reopens only that reconciliation boundary so the existing
    immutable invalid-identity supersession can establish one fresh successor.
    """

    root = root.resolve(strict=True)
    repair = _repair_campaign(root)
    value = _validate(
        json.loads((root / STATE_PATH).read_text(encoding="utf-8"))
    )
    if (
        repair.get("phase") != "revision_reconciled"
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            "invalid identity rewind requires a zero-unresolved reconciled repair"
        )
    if (
        value.get("state") != "active"
        or value.get("apply_count") != 1
        or value.get("active_claim") is not None
        or any(value["stages"][stage]["status"] != "pending" for stage in STAGES)
    ):
        raise ReleaseCampaignBlocked(
            "invalid identity rewind requires one unused active identity"
        )
    verification = release_campaign_status(root, verify_source=True)
    if verification["valid"] or not verification["errors"]:
        raise ReleaseCampaignBlocked("a coherent release identity cannot be rewound")
    repair["phase"] = "repair_frozen"
    _write(root / REPAIR_CAMPAIGN_PATH, repair)
    return {
        "schema_version": "px.release-identity-reconciliation-rewind/1.0",
        "campaign_id": value["campaign_id"],
        "phase": "repair_frozen",
        "source_verification_errors": list(verification["errors"]),
        "valid": True,
    }


def rewind_failed_release_campaign_repair(root: Path) -> dict[str, Any]:
    """Return one terminal failed stage from its exact phase to repair freeze."""

    root = root.resolve(strict=True)
    repair = _repair_campaign(root)
    value = _validate(
        json.loads((root / STATE_PATH).read_text(encoding="utf-8"))
    )
    failed = [
        stage for stage in STAGES if value["stages"][stage]["status"] == "failed"
    ]
    if (
        value.get("state") != "failed"
        or value.get("active_claim") is not None
        or len(failed) != 1
    ):
        raise ReleaseCampaignBlocked(
            "failed campaign rewind requires one terminal failed stage"
        )
    failed_stage = failed[0]
    expected_phase = STAGE_PHASES[failed_stage]
    if (
        repair.get("phase") != expected_phase
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            "failed campaign rewind requires the failed stage's exact repair phase"
        )
    repair["phase"] = "repair_frozen"
    _write(root / REPAIR_CAMPAIGN_PATH, repair)
    return {
        "schema_version": "px.failed-release-campaign-repair-rewind/1.0",
        "campaign_id": value["campaign_id"],
        "failed_stage": failed_stage,
        "prior_phase": expected_phase,
        "phase": "repair_frozen",
        "valid": True,
    }


def supersede_failed_release_campaign(
    root: Path, *, campaign_id: str, reason: str
) -> dict[str, Any]:
    """Archive one terminal failed campaign and establish one cleared successor.

    A failed stage permanently consumes its campaign identity. Repairs must not
    erase or replay that attempt, but they also must not force callers to edit
    the mutable release pointer by hand. This transition retains the complete
    failed campaign as immutable evidence and creates exactly one new cleared
    campaign under the same frozen, zero-unresolved repair campaign.
    """

    root = root.resolve(strict=True)
    replacement_id = campaign_id.strip()
    explanation = reason.strip()
    if not replacement_id or not explanation:
        raise ReleaseCampaignBlocked(
            "failed campaign supersession requires a replacement campaign ID and reason"
        )
    repair = _repair_campaign(root)
    if (
        repair.get("phase") != "repair_frozen"
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            "failed campaign supersession requires one frozen, zero-unresolved repair"
        )
    state_path = root / STATE_PATH
    previous = _validate(json.loads(state_path.read_text(encoding="utf-8")))
    if replacement_id == previous["campaign_id"]:
        raise ReleaseCampaignBlocked("replacement campaign ID must be new")
    if previous["state"] != "failed" or previous.get("active_claim") is not None:
        raise ReleaseCampaignBlocked("only a terminal failed campaign may be superseded")
    verification = release_campaign_status(root, verify_source=True)
    archive_path = root / FAILED_IDENTITY_ARCHIVE_ROOT / (
        f"failed-release-campaign-{previous['campaign_id']}.json"
    )
    if archive_path.exists():
        raise ReleaseCampaignBlocked("failed campaign archive already exists")
    archive = {
        "schema_version": "px.failed-release-campaign/1.0",
        "superseded_at": _now(),
        "reason": explanation,
        "replacement_campaign_id": replacement_id,
        "source_verification_errors": list(verification["errors"]),
        "campaign_state": previous,
    }
    archive["archive_sha256"] = _sha(archive)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(archive, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    cleared = {
        "schema_version": "px.release-campaign/1.0",
        "campaign_id": replacement_id,
        "repair_campaign_id": repair["campaign_id"],
        "state": "cleared",
        "cleared_at": _now(),
        "applied_at": None,
        "apply_count": 0,
        "identity": None,
        "active_claim": None,
        "supersedes": {
            "campaign_id": previous["campaign_id"],
            "archive": archive_path.relative_to(root).as_posix(),
            "archive_sha256": archive["archive_sha256"],
        },
        "stages": {name: {"status": "pending", "claim_id": None} for name in STAGES},
    }
    _write(state_path, cleared)
    status = release_campaign_status(root)
    return {**status, "superseded_archive": archive_path.relative_to(root).as_posix()}


def supersede_consumed_cleared_release_campaign(
    root: Path, *, campaign_id: str, reason: str
) -> dict[str, Any]:
    """Archive one unused cleared campaign after its reconciliation was consumed.

    No identity or stage history exists to mark failed in this state. This
    transition preserves that empty attempt instead of reusing it, and permits
    only one pre-identity successor within the frozen repair generation.
    """

    root = root.resolve(strict=True)
    replacement_id = campaign_id.strip()
    explanation = reason.strip()
    if not replacement_id or not explanation:
        raise ReleaseCampaignBlocked(
            "cleared campaign supersession requires a replacement ID and reason"
        )
    repair = _repair_campaign(root)
    if (
        repair.get("phase") != "repair_frozen"
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            "cleared campaign supersession requires one frozen, zero-unresolved repair"
        )
    state_path = root / STATE_PATH
    previous = _validate(json.loads(state_path.read_text(encoding="utf-8")))
    if replacement_id == previous["campaign_id"]:
        raise ReleaseCampaignBlocked("replacement campaign ID must be new")
    if not cleared_campaign_can_be_superseded(previous):
        raise ReleaseCampaignBlocked(
            "a chained cleared campaign requires one exact terminal pre-identity marker"
        )
    archive_path = root / FAILED_IDENTITY_ARCHIVE_ROOT / (
        f"consumed-cleared-release-campaign-{previous['campaign_id']}.json"
    )
    if archive_path.exists():
        raise ReleaseCampaignBlocked("consumed cleared campaign archive already exists")
    archive = {
        "schema_version": "px.consumed-cleared-release-campaign/1.0",
        "superseded_at": _now(),
        "reason": explanation,
        "replacement_campaign_id": replacement_id,
        "campaign_state": previous,
    }
    archive["archive_sha256"] = _sha(archive)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(archive, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    cleared = {
        "schema_version": "px.release-campaign/1.0",
        "campaign_id": replacement_id,
        "repair_campaign_id": repair["campaign_id"],
        "state": "cleared",
        "cleared_at": _now(),
        "applied_at": None,
        "apply_count": 0,
        "identity": None,
        "active_claim": None,
        "pre_identity_reconciliation_successor": True,
        "pre_identity_reconciliation_attempt": int(
            previous.get("pre_identity_reconciliation_attempt") or 0
        )
        + 1,
        "supersedes": {
            "campaign_id": previous["campaign_id"],
            "archive": archive_path.relative_to(root).as_posix(),
            "archive_sha256": archive["archive_sha256"],
        },
        "stages": {name: {"status": "pending", "claim_id": None} for name in STAGES},
    }
    _write(state_path, cleared)
    status = release_campaign_status(root)
    return {**status, "superseded_archive": archive_path.relative_to(root).as_posix()}


def supersede_invalid_active_release_campaign(
    root: Path, *, campaign_id: str, reason: str
) -> dict[str, Any]:
    """Archive an invalid active campaign without rewriting passed stage history.

    This boundary is for a source defect discovered after one or more stages
    passed but before another stage was claimed.  The original campaign stays
    immutable, including every passed stage, while one new cleared successor
    is established under the same frozen repair campaign.
    """

    root = root.resolve(strict=True)
    replacement_id = campaign_id.strip()
    explanation = reason.strip()
    if not replacement_id or not explanation:
        raise ReleaseCampaignBlocked(
            "active campaign supersession requires a replacement campaign ID and reason"
        )
    repair = _repair_campaign(root)
    if (
        repair.get("phase") != "repair_frozen"
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            "active campaign supersession requires one frozen, zero-unresolved repair"
        )
    state_path = root / STATE_PATH
    previous = _validate(json.loads(state_path.read_text(encoding="utf-8")))
    if replacement_id == previous["campaign_id"]:
        raise ReleaseCampaignBlocked("replacement campaign ID must be new")
    statuses = [previous["stages"][stage]["status"] for stage in STAGES]
    if (
        previous["state"] != "active"
        or previous["apply_count"] != 1
        or previous.get("active_claim") is not None
        or "passed" not in statuses
        or any(status not in {"passed", "pending"} for status in statuses)
    ):
        raise ReleaseCampaignBlocked(
            "only an idle invalid active campaign with retained passed stages may be superseded"
        )
    verification = release_campaign_status(root, verify_source=True)
    if verification["valid"] or not verification["errors"]:
        raise ReleaseCampaignBlocked("a coherent active campaign cannot be superseded")
    archive_path = root / FAILED_IDENTITY_ARCHIVE_ROOT / (
        f"superseded-active-release-campaign-{previous['campaign_id']}.json"
    )
    if archive_path.exists():
        raise ReleaseCampaignBlocked("active campaign archive already exists")
    archive = {
        "schema_version": "px.superseded-active-release-campaign/1.0",
        "superseded_at": _now(),
        "reason": explanation,
        "replacement_campaign_id": replacement_id,
        "source_verification_errors": list(verification["errors"]),
        "campaign_state": previous,
    }
    archive["archive_sha256"] = _sha(archive)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(archive, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    cleared = {
        "schema_version": "px.release-campaign/1.0",
        "campaign_id": replacement_id,
        "repair_campaign_id": repair["campaign_id"],
        "state": "cleared",
        "cleared_at": _now(),
        "applied_at": None,
        "apply_count": 0,
        "identity": None,
        "active_claim": None,
        "supersedes": {
            "campaign_id": previous["campaign_id"],
            "archive": archive_path.relative_to(root).as_posix(),
            "archive_sha256": archive["archive_sha256"],
        },
        "stages": {name: {"status": "pending", "claim_id": None} for name in STAGES},
    }
    _write(state_path, cleared)
    status = release_campaign_status(root)
    return {**status, "superseded_archive": archive_path.relative_to(root).as_posix()}


def claim_release_stage(root: Path, stage: str) -> dict[str, Any]:
    root = root.resolve(strict=True)
    if stage not in STAGES:
        raise ReleaseCampaignBlocked(f"unknown release stage: {stage}")
    path = root / STATE_PATH
    value = _validate(json.loads(path.read_text(encoding="utf-8")))
    repair = _repair_campaign(root)
    if (
        value.get("repair_campaign_id") != repair.get("campaign_id")
        or repair.get("phase") != STAGE_PHASES[stage]
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise ReleaseCampaignBlocked(
            f"release stage {stage} requires zero unresolved work at phase "
            f"{STAGE_PHASES[stage]}"
        )
    if value["state"] != "active" or value.get("active_claim") is not None:
        raise ReleaseCampaignBlocked("release campaign is not available for a stage claim")
    status = release_campaign_status(root, verify_source=True)
    if not status["valid"]:
        raise ReleaseCampaignBlocked("release source changed after identity apply")
    index = STAGES.index(stage)
    predecessors = STAGES[:index]
    if any(value["stages"][name]["status"] != "passed" for name in predecessors):
        raise ReleaseCampaignBlocked(
            f"release stage {stage} has an incomplete predecessor"
        )
    if value["stages"][stage]["status"] != "pending":
        raise ReleaseCampaignBlocked(f"release stage {stage} cannot be replayed")
    claim_id = f"release-stage:{value['campaign_id']}:{stage}:{uuid4().hex}"
    claim = {"stage": stage, "claim_id": claim_id, "claimed_at": _now()}
    value["active_claim"] = claim
    value["stages"][stage] = {
        "status": "claimed",
        "claim_id": claim_id,
        "claimed_at": claim["claimed_at"],
    }
    _write(path, value)
    return {**claim, "release_identity_sha256": value["identity"]["release_identity_sha256"]}


def finish_release_stage(
    root: Path, *, stage: str, claim_id: str, passed: bool
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    path = root / STATE_PATH
    value = _validate(json.loads(path.read_text(encoding="utf-8")))
    claim = value.get("active_claim")
    if (
        not isinstance(claim, dict)
        or claim.get("stage") != stage
        or claim.get("claim_id") != claim_id
        or value["stages"].get(stage, {}).get("status") != "claimed"
    ):
        raise ReleaseCampaignBlocked("release stage completion does not bind its claim")
    if passed and not release_campaign_status(root, verify_source=True)["valid"]:
        passed = False
    final = "passed" if passed else "failed"
    value["stages"][stage] = {
        **value["stages"][stage],
        "status": final,
        "finished_at": _now(),
    }
    value["active_claim"] = None
    if not passed:
        value["state"] = "failed"
    elif stage == "certify":
        value["state"] = "certified"
    _write(path, value)
    return release_campaign_status(root, verify_source=passed)
