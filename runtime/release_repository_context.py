"""Independent authority checks for repository-context release gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any


RELEASE_GATE_REQUIRED_REPOSITORY_CONTEXT = (
    ".agentic_engineering_os_px/processing-order/repair-campaign.json",
    ".agentic_engineering_os_px/processing-order/release-identity.json",
    "evidence/README.md",
    "evidence/externalized-payload-index.json",
    "registry/corrective_release_ledger.json",
    "registry/operational_gap_ledger.head.json",
    "registry/operational_gap_ledger.jsonl",
    "registry/operational_gap_ledger.snapshot.json",
)


def verify_source_anchor(root: Path, anchor: dict, *, require_live: bool = False) -> dict:
    """Verify native retained bytes; optional live equality never fabricates a freeze."""
    import hashlib
    import zipfile
    from .archive_io import portable_member_name, reject_path_links, read_stream_bytes
    from .json_io import read_bounded_bytes
    from .plan_registry import _planning_object
    from .source_freeze import read_freeze, verify_freeze
    if type(anchor) is not dict or set(anchor) != {"path", "sha256"}:
        raise ValueError("exact native source-freeze reference required")
    if not isinstance(anchor, dict):
        raise ValueError("current source anchor is not bound")
    relative = portable_member_name(anchor["path"], allow_directory=False)
    if not relative.startswith("registry/source-freeze/current-campaign/"):
        raise ValueError("source anchor must belong to the current capture namespace")
    _planning_object(root / relative)
    if hashlib.sha256(read_bounded_bytes(root / relative, max_bytes=8 * 1024 * 1024)).hexdigest() != anchor["sha256"]:
        raise ValueError("current source anchor hash differs")
    receipt = read_freeze(root, relative=Path(relative))
    rows = receipt["files"]
    if (len(rows) != receipt["file_count"] or sum(row["bytes"] for row in rows) != receipt["byte_count"]
            or receipt["byte_count"] > 512 * 1024 * 1024):
        raise ValueError("current source manifest totals differ or exceed bounds")
    identity = hashlib.sha256()
    for row in rows:
        name = portable_member_name(row["path"], allow_directory=False)
        identity.update(name.encode("utf-8") + b"\0" + bytes.fromhex(row["sha256"]) + b"\0")
    if identity.hexdigest() != receipt["tree_sha256"]:
        raise ValueError("current source tree identity differs from manifest")
    archive_relative = portable_member_name(receipt["archive"]["path"], allow_directory=False)
    if not archive_relative.startswith("registry/source-freeze/current-campaign/"):
        raise ValueError("current source archive must be campaign-relative")
    archive = root / archive_relative
    reject_path_links(archive)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != receipt["archive"]["sha256"]:
        raise ValueError("current source archive hash differs")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if names != [row["path"] for row in rows] or len(set(names)) != len(names):
            raise ValueError("current source archive inventory differs")
        for row in rows:
            info = bundle.getinfo(row["path"])
            if info.file_size != row["bytes"] or row["bytes"] > 128 * 1024 * 1024:
                raise ValueError("current source member size differs or exceeds bounds")
            with bundle.open(info) as stream:
                data = read_stream_bytes(stream, max_bytes=row["bytes"] + 1)
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("current source member bytes differ")
    if require_live and not verify_freeze(root, relative=Path(relative))["valid"]:
        raise ValueError("final authored source differs from its retained freeze")
    return {"reference": dict(anchor), "receipt": receipt, "archive_relative": archive_relative}


def _current_repository_context(root: Path) -> dict[str, Any]:
    import hashlib
    import zipfile
    from .archive_io import portable_member_name, reject_path_links, read_stream_bytes
    from .json_io import read_bounded_bytes
    from .plan_registry import _planning_object, _require_current_campaign, requirement_report
    from .release_campaign import release_state_relative, release_campaign_status
    from .source_freeze import read_freeze

    required = ["policies/rev1xx-validation.json",
                ".agentic_engineering_os_px/processing-order/repair-campaign.json",
                release_state_relative(root).as_posix()]
    errors = []
    try:
        policy = _planning_object(root / required[0])
        _require_current_campaign(policy)
        campaign = _planning_object(root / required[1])
        if campaign.get("campaign_id") != policy["campaign_id"]:
            raise ValueError("current repair campaign does not match admitted owner policy")
        status = release_campaign_status(root)
        if not status["valid"]:
            raise ValueError("current release state is missing or mismatched")
        requirement_report(root)
        required.append(policy["requirement_trace"]["path"])
        verified = verify_source_anchor(root, {key: policy.get("source_anchor", {}).get(key) for key in ("path", "sha256")})
        required.extend((verified["reference"]["path"], verified["archive_relative"]))
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as error:
        errors.append(f"current repository custody: {error}")
    missing = [relative for relative in required if not (root / relative).is_file()]
    return {"schema_version": "px.release-gate-repository-context/1.0",
            "valid": not errors and not missing, "required": required, "missing": missing,
            "errors": errors, "validation_basis": "current_implementation",
            "historical_prerequisites": False,
            "git_acceptance": {"state": "deferred_by_owner", "satisfied": False},
            "authority": "OWNER-FRESH-VALIDATION-001; explicit owner Git hold"}


def validate_release_gate_repository_context(root: Path) -> dict[str, Any]:
    """Fail early unless repository-context release gates have their authorities."""
    resolved = root.resolve()
    from .archive_io import reject_path_links

    policy = resolved / "policies/rev1xx-validation.json"
    reject_path_links(policy)
    if policy.exists():
        return _current_repository_context(resolved)
    from .release_campaign import release_state_relative

    release_relative = release_state_relative(resolved).as_posix()
    required = list(RELEASE_GATE_REQUIRED_REPOSITORY_CONTEXT)
    legacy_release = ".agentic_engineering_os_px/processing-order/release-identity.json"
    required[required.index(legacy_release)] = release_relative
    missing: list[str] = []
    if not (resolved / ".git").exists():
        missing.append(".git")
    missing.extend(
        relative
        for relative in required
        if not (resolved / relative).is_file()
    )
    return {
        "schema_version": "px.release-gate-repository-context/1.0",
        "valid": not missing,
        "required": [".git", *required],
        "missing": missing,
        "errors": [
            f"authenticated release repository context is missing: {relative}"
            for relative in missing
        ],
    }
