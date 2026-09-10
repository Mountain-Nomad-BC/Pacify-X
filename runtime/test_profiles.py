"""Deterministic fast/full/release test profile resolution."""

from __future__ import annotations

import json
import fnmatch
import hashlib
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from .test_runner import aggregate_test_disk_consumption_limit, validate_timeout


REPAIR_CAMPAIGN_PATH = Path("registry/repair_campaign.json")
MANAGED_PROJECT_MARKER = Path(".engineering-bootstrap/project-record.json")
PROJECT_REPAIR_CAMPAIGN_PATH = Path(
    ".engineering-bootstrap/processing-order/repair-campaign.json"
)
PROCESSING_PHASES = (
    "intake", "repair", "operational_verification", "repair_frozen",
    "revision_reconciled", "sections_current", "full_profile_passed",
    "validated", "packaged", "installed", "installed_operational", "certified",
)
STAGE_MINIMUM_PHASE = {
    "diagnose": "intake", "repair": "repair", "focused_test": "repair",
    "governed_section": "repair", "operational_verification": "operational_verification",
    "revision_reconciliation": "repair_frozen", "full_profile": "sections_current",
    "validate": "full_profile_passed", "package": "validated", "install": "packaged",
    "installed_operational_test": "installed", "certify": "installed_operational",
}
STAGE_ALLOWED_PHASES = {
    "diagnose": frozenset({"intake", "repair"}),
    "repair": frozenset({"repair"}),
    "focused_test": frozenset({"repair"}),
    "governed_section": frozenset({"repair", "revision_reconciled"}),
    "operational_verification": frozenset({"operational_verification"}),
    "revision_reconciliation": frozenset({"repair_frozen"}),
    "full_profile": frozenset({"sections_current"}),
    "validate": frozenset({"full_profile_passed"}),
    "package": frozenset({"validated"}),
    "install": frozenset({"packaged"}),
    "installed_operational_test": frozenset({"installed"}),
    "certify": frozenset({"installed_operational"}),
}
CLOSURE_STAGES = frozenset({
    "revision_reconciliation", "full_profile", "validate", "package", "install",
    "installed_operational_test", "certify",
})


class ProcessingOrderBlocked(ValueError):
    """Raised when downstream closure is attempted before repair freeze."""


def _repair_campaign_path(root: Path) -> tuple[Path, bool]:
    repository_campaign = root / REPAIR_CAMPAIGN_PATH
    if repository_campaign.is_file():
        return repository_campaign, True
    if (root / MANAGED_PROJECT_MARKER).is_file():
        return root / PROJECT_REPAIR_CAMPAIGN_PATH, True
    return repository_campaign, False


def initialize_project_repair_campaign(root: Path) -> dict[str, Any]:
    """Create mandatory local processing-order state for a managed project."""

    root = root.resolve(strict=True)
    marker = root / MANAGED_PROJECT_MARKER
    if not marker.is_file():
        raise ProcessingOrderBlocked(
            "processing-order initialization requires a managed-project record"
        )
    project_record = json.loads(marker.read_text(encoding="utf-8"))
    project_id = str(project_record.get("project_id") or "")
    if not project_id.startswith("prj_"):
        raise ProcessingOrderBlocked("managed-project record is malformed")
    path = root / PROJECT_REPAIR_CAMPAIGN_PATH
    if path.exists():
        status = repair_campaign_status(root)
        return {
            **status,
            "initialized": False,
            "path": path.relative_to(root).as_posix(),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ProcessingOrderBlocked(
            "processing-order state parent must not be a symlink"
        )
    campaign = {
        "schema_version": "px.repair-campaign/1.0",
        "campaign_id": f"{project_id}-initial-operational-repair",
        "phase": "intake",
        "intake_open": True,
        "unresolved": ["initial-operational-intake"],
    }
    temporary = path.with_name(path.name + ".new")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(campaign, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Successful replacement consumes the prepared file. On failure it remains
    # in bounded project-local custody for explicit recovery; never hard-delete
    # unclassified evidence from an exception path.
    os.replace(temporary, path)
    status = repair_campaign_status(root)
    return {
        **status,
        "initialized": True,
        "path": path.relative_to(root).as_posix(),
    }


def processing_stage_allowed(
    phase: str, intake_open: bool, unresolved: list[str], stage: str
) -> bool:
    allowed_phases = STAGE_ALLOWED_PHASES.get(stage)
    if allowed_phases is None:
        raise ValueError(f"unknown processing stage: {stage}")
    if stage in CLOSURE_STAGES and (intake_open or unresolved):
        return False
    return phase in allowed_phases


def repair_campaign_status(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    path, managed = _repair_campaign_path(root)
    if not path.is_file():
        if managed:
            raise ProcessingOrderBlocked(
                "PROCESSING_ORDER_BLOCKED: managed project is missing mandatory "
                f"processing-order state at {path.relative_to(root).as_posix()}"
            )
        return {
            "schema_version": "px.processing-order-status/1.0", "valid": True,
            "managed": False, "phase": "unmanaged", "intake_open": False,
            "unresolved": [], "blocked_stages": [],
            "limitations": ["No active repair campaign is registered."],
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProcessingOrderBlocked("repair campaign must be a JSON object")
    phase = str(value.get("phase") or "")
    unresolved = value.get("unresolved")
    intake_open = value.get("intake_open")
    if (
        value.get("schema_version") != "px.repair-campaign/1.0"
        or phase not in PROCESSING_PHASES
        or not isinstance(intake_open, bool)
        or not isinstance(unresolved, list)
        or any(not isinstance(item, str) or not item.strip() for item in unresolved)
        or len(unresolved) != len(set(unresolved))
    ):
        raise ProcessingOrderBlocked("repair campaign is malformed")
    blocked = [stage for stage in STAGE_MINIMUM_PHASE if not processing_stage_allowed(phase, intake_open, unresolved, stage)]
    return {
        "schema_version": "px.processing-order-status/1.0", "valid": True,
        "managed": True, "campaign_id": value.get("campaign_id"), "phase": phase,
        "intake_open": intake_open, "unresolved": list(unresolved),
        "unresolved_count": len(unresolved), "blocked_stages": blocked,
        "next_required_phase": PROCESSING_PHASES[min(PROCESSING_PHASES.index(phase) + 1, len(PROCESSING_PHASES) - 1)],
        "rule": "Repair intake and operational work freeze before revision reconciliation; downstream closure advances once in order.",
    }


def require_processing_stage(root: Path, stage: str) -> dict[str, Any]:
    status = repair_campaign_status(root)
    if not status["managed"]:
        return status
    if not processing_stage_allowed(str(status["phase"]), bool(status["intake_open"]), list(status["unresolved"]), stage):
        unresolved = ", ".join(status["unresolved"][:8]) or "none"
        required = " or ".join(sorted(STAGE_ALLOWED_PHASES[stage], key=PROCESSING_PHASES.index))
        raise ProcessingOrderBlocked(
            f"PROCESSING_ORDER_BLOCKED: {stage} requires phase {required}; "
            f"current={status['phase']}; intake_open={str(status['intake_open']).lower()}; "
            f"unresolved={unresolved}"
        )
    identity_bound_section = (
        stage == "governed_section" and status.get("phase") == "revision_reconciled"
    )
    if (root.resolve() / MANAGED_PROJECT_MARKER).is_file() and (
        stage in CLOSURE_STAGES or identity_bound_section
    ):
        from .release_campaign import release_campaign_status

        release = release_campaign_status(
            root,
            verify_source=stage != "revision_reconciliation",
        )
        if stage == "revision_reconciliation":
            release_ready = (
                release.get("valid") is True
                and release.get("state") == "cleared"
                and release.get("apply_count") == 0
                and release.get("identity") is None
            )
        elif identity_bound_section:
            stages = release.get("stages", {})
            release_ready = (
                release.get("valid") is True
                and release.get("state") == "active"
                and release.get("apply_count") == 1
                and stages.get("sections", {}).get("status") == "claimed"
            )
        else:
            release_stage = {
                "full_profile": "full_profile",
                "validate": "validate",
                "package": "package",
                "install": "install",
                "installed_operational_test": "installed_operational",
                "certify": "certify",
            }[stage]
            stages = release.get("stages", {})
            stage_status = stages.get(release_stage, {}).get("status")
            active_claim = release.get("active_claim")
            claimed_here = (
                stage_status == "claimed"
                and isinstance(active_claim, dict)
                and active_claim.get("stage") == release_stage
                and active_claim.get("claim_id")
                == stages.get(release_stage, {}).get("claim_id")
            )
            release_ready = (
                release.get("valid") is True
                and release.get("state") == "active"
                and release.get("apply_count") == 1
                and isinstance(release.get("identity"), dict)
                and (stage_status == "pending" or claimed_here)
            )
        if not release_ready:
            raise ProcessingOrderBlocked(
                f"PROCESSING_ORDER_BLOCKED: {stage} has no exact one-shot "
                f"release identity/stage authority; release_state={release.get('state')}"
            )
    return {**status, "requested_stage": stage, "stage_allowed": True}


def resolve_test_profile(root: Path, name: str) -> dict[str, Any]:
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    if name not in config["profiles"]:
        raise ValueError(f"unknown test profile: {name}")
    all_tests = sorted(
        path.relative_to(root).as_posix() for path in (root / "tests").glob("test_*.py")
    )
    profile = config["profiles"][name]
    timeout = validate_timeout(profile.get("timeout_seconds"))
    if name == "release":
        source_name = "full"
    else:
        source_name = name
    excluded = set(config["profiles"][source_name].get("exclude_files", []))
    unknown_exclusions = sorted(excluded - set(all_tests))
    if unknown_exclusions:
        raise ValueError(
            "test profile contains unknown exclusions: " + ", ".join(unknown_exclusions)
        )
    members = [path for path in all_tests if path not in excluded]
    return {
        "schema_version": "1.0",
        "valid": True,
        "profile": name,
        "discovered_test_files": len(all_tests),
        "member_count": len(members),
        "members": members,
        "excluded": sorted(excluded),
        "safe_default": "Every new tests/test_*.py file is automatically included in full and release.",
        "timeout_seconds": timeout,
        "profile_budget_seconds": timeout,
        "duration_reporting": 50,
        "gates": profile.get("gates", []),
        "environment": {
            **config.get("environment", {}),
            **profile.get("environment", {}),
        },
        "command": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--durations=50",
            "-p",
            "no:cacheprovider",
            *members,
        ],
    }


def _section_files(root: Path, patterns: list[str]) -> list[str]:
    from .verification_inputs import CapturedInputs
    capture = CapturedInputs(root)
    result = capture.match(patterns)
    capture.verify()
    return result


def _structural_scan_files(root: Path, max_bytes: int = 1_000_000) -> list[str]:
    from .verification_inputs import CapturedInputs
    from .verification_status import structural_scan
    if type(max_bytes) is not int or not 0 < max_bytes <= 8 * 1024**2:
        raise ValueError("invalid structural scan file budget")
    capture = CapturedInputs(root)
    result = structural_scan(capture, max_bytes)
    capture.verify()
    return result


def _fingerprint(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        payload = (root / relative).read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def resolve_test_section(root: Path, name: str) -> dict[str, Any]:
    from .verification_inputs import resolve_test_section as resolve
    return resolve(root, name)


def section_receipt(section: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    from .verification_receipts import make_receipt
    return make_receipt('section', section, execution)


_PUBLIC_OUTPUT_CHAR_LIMIT = 64 * 1024 * 1024
_PUBLIC_OUTPUT_LINE_LIMIT = 100000
_PUBLIC_OUTPUT_LINE_CHARS = 4096
_PUBLIC_FAILURE_LIMIT = 50
_PUBLIC_SUPERVISION_STATUSES = frozenset(
    {
        "cancelled",
        "total_timeout",
        "startup_timeout",
        "idle_timeout",
        "shutdown_failed",
        "owner_lost",
        "disk_budget_exceeded",
        "spawn_failed",
    }
)


def _public_failure_node(node: str, reporter: str) -> str:
    """Retain static pytest syntax, never parameter bodies or free-form titles."""
    import re

    if reporter != "pytest":
        return reporter + ":details-redacted"
    base, marker, _parameters = node.partition("[")
    # This syntax is diagnostic attribution, not authenticated test membership.
    pattern = r"tests/(?:[A-Za-z0-9_-]{1,128}/){0,8}test_[A-Za-z0-9_]{1,128}\.py(?:::[A-Za-z_][A-Za-z0-9_]{0,127}){1,8}"
    if not re.fullmatch(pattern, base) or not base.rsplit("::", 1)[-1].startswith(
        "test_"
    ):
        return "pytest:details-redacted"
    result = base + ("[parameters-redacted]" if marker else "")
    return result if len(result) <= 300 else "pytest:details-redacted"


def _bounded_output_evidence(execution: Mapping[str, Any]) -> dict[str, object]:
    """Retain bounded diagnostic attribution without reporter parameter payloads."""
    import re
    from .numeric_inputs import bounded_integer

    if type(execution) is not dict or len(execution) > 128:
        raise ValueError("test execution must be a bounded actual object")
    streams = []
    for stream in ("stdout", "stderr"):
        value = execution.get(stream)
        if value is None:
            value = ""
        if type(value) is not str or len(value) > _PUBLIC_OUTPUT_CHAR_LIMIT:
            raise ValueError("test output must be bounded actual text")
        streams.append((stream, value))
    exit_code = execution.get("exit_code", execution.get("returncode"))
    if exit_code is not None:
        exit_code = bounded_integer(
            exit_code, "process exit", minimum=-(2**31), maximum=2**32 - 1
        )
    status = execution.get("supervision_status")
    if status is not None and (type(status) is not str or len(status) > 128):
        raise ValueError("supervision status must be bounded actual text")
    output_evidence = {}
    failure_nodes = []
    seen = set()
    lines_seen = 0
    attribution_complete = True
    for stream, value in streams:
        digest = hashlib.sha256()
        byte_count = 0
        # Hash the exact UTF-8 text supplied by the process owner without making
        # another whole-output byte image. This is not the raw pipe-byte hash.
        for offset in range(0, len(value), 65536):
            encoded = value[offset : offset + 65536].encode("utf-8")
            digest.update(encoded)
            byte_count += len(encoded)
        output_evidence[stream + "_sha256"] = digest.hexdigest()
        output_evidence[stream + "_bytes"] = byte_count
        if not attribution_complete:
            continue
        for match in re.finditer(r"[^\n\r\v\f\x1c-\x1e\x85\u2028\u2029]+", value):
            lines_seen += 1
            if lines_seen > _PUBLIC_OUTPUT_LINE_LIMIT:
                attribution_complete = False
                break
            if match.end() - match.start() > _PUBLIC_OUTPUT_LINE_CHARS:
                # A long line may contain a failure; do not publish its prefix.
                attribution_complete = False
                break
            line = match.group().strip()
            node = ""
            if line.startswith("FAILED "):
                node = _public_failure_node(
                    line[7:].split(" - ", 1)[0].strip(), "pytest"
                )
            elif line.startswith("\u2716 "):
                title = line[2:].strip()
                if title.casefold().rstrip(":") != "failing tests":
                    node = _public_failure_node(title, "node")
            elif line.startswith("not ok ") and " - " in line:
                node = _public_failure_node("", "tap")
            if node and node not in seen:
                if len(failure_nodes) >= _PUBLIC_FAILURE_LIMIT - 1:
                    attribution_complete = False
                    break
                seen.add(node)
                failure_nodes.append(node)
    if not attribution_complete:
        failure_nodes.append("diagnostics:attribution-truncated")
    if not failure_nodes and (
        exit_code not in {0, None} or status in _PUBLIC_SUPERVISION_STATUSES
    ):
        if status in _PUBLIC_SUPERVISION_STATUSES:
            failure_nodes.append("supervision:" + status)
        else:
            failure_nodes.append("unattributed-process-exit:" + str(exit_code))
    output_evidence["failure_nodes"] = failure_nodes
    return output_evidence



def _valid_bounded_output_evidence(value: object) -> bool:
    if type(value) is not dict or set(value) != {
        "stdout_sha256",
        "stdout_bytes",
        "stderr_sha256",
        "stderr_bytes",
        "failure_nodes",
    }:
        return False
    for stream in ("stdout", "stderr"):
        digest = value[stream + "_sha256"]
        count = value[stream + "_bytes"]
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            return False
        if type(count) is not int or not 0 <= count <= 4 * _PUBLIC_OUTPUT_CHAR_LIMIT:
            return False
    nodes = value["failure_nodes"]
    if type(nodes) is not list or len(nodes) > _PUBLIC_FAILURE_LIMIT:
        return False
    seen = set()
    for node in nodes:
        if type(node) is not str or not 0 < len(node) <= 300 or node in seen:
            return False
        seen.add(node)
        if node in {
            "pytest:details-redacted",
            "node:details-redacted",
            "tap:details-redacted",
            "diagnostics:attribution-truncated",
        }:
            continue
        if (
            node.startswith("supervision:")
            and node[12:] in _PUBLIC_SUPERVISION_STATUSES
        ):
            continue
        if node.startswith("unattributed-process-exit:"):
            number = node[26:]
            try:
                parsed = int(number)
            except ValueError:
                return False
            if str(parsed) == number and -(2**31) <= parsed <= 2**32 - 1:
                continue
            return False
        if _public_failure_node(node, "pytest") != node:
            return False
    return True



def section_chunk_receipt(section: Mapping[str, Any], chunk: Mapping[str, Any], execution: Mapping[str, Any]) -> dict[str, Any]:
    from .verification_receipts import make_receipt
    return make_receipt('chunk', chunk, execution, section=section)


def section_chunk_receipt_path(root: Path, section: str, chunk_id: str) -> Path:
    from .verification_receipts import receipt_path
    return receipt_path(root, 'chunk', section, chunk_id)


def read_section_chunk_receipt(root: Path, section: str, chunk_id: str) -> dict[str, Any]:
    from .verification_receipts import read
    return read(root, 'chunk', section, chunk_id)


def write_section_chunk_receipt(root: Path, receipt: Mapping[str, Any]) -> Path:
    from .verification_receipts import write
    return write(root, 'chunk', receipt)


def write_section_receipt(root: Path, receipt: Mapping[str, Any]) -> Path:
    from .verification_receipts import write
    return write(root, 'section', receipt)


def section_status(root: Path) -> dict[str, Any]:
    from .verification_status import section_status as status
    return status(root)


def stale_section_execution_order(status: Mapping[str, Any]) -> list[str]:
    """Return stale sections in deterministic dependency-topological order."""

    raw_rows = status.get("sections")
    if not isinstance(raw_rows, list):
        raise ValueError("test section status is missing its section denominator")
    rows: dict[str, Mapping[str, Any]] = {}
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ValueError("test section status contains a malformed row")
        name = str(raw.get("section") or "")
        dependencies = raw.get("dependencies")
        if (
            not name
            or name in rows
            or not isinstance(dependencies, list)
            or any(not isinstance(item, str) or not item for item in dependencies)
        ):
            raise ValueError("test section status has an invalid section topology")
        rows[name] = raw
    missing = sorted(
        {
            dependency
            for row in rows.values()
            for dependency in row["dependencies"]
            if dependency not in rows
        }
    )
    if missing:
        raise ValueError(
            "test section topology has missing dependencies: " + ", ".join(missing)
        )
    current = {name for name, row in rows.items() if row.get("current") is True}
    pending = set(rows) - current
    ordered: list[str] = []
    while pending:
        ready = sorted(
            (
                name
                for name in pending
                if all(dependency in current for dependency in rows[name]["dependencies"])
            ),
            key=str.casefold,
        )
        if not ready:
            raise ValueError("test section dependencies contain a stale cycle")
        ordered.extend(ready)
        current.update(ready)
        pending.difference_update(ready)
    return ordered


def _local_module_paths(root: Path) -> dict[str, str]:
    module_paths: dict[str, str] = {}
    for top in ("runtime", "builders", "scripts"):
        base = root / top
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            parts = list(path.relative_to(root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            module_paths[".".join(parts)] = relative
    return module_paths


def _local_python_dependencies(root: Path, members: list[str], module_paths: Mapping[str, str] | None = None) -> list[str]:
    from .verification_inputs import local_python_dependencies
    return local_python_dependencies(root, members, module_paths)


def _discover_test_groups(root: Path) -> list[dict[str, Any]]:
    """Resolve an exhaustive, mutually exclusive certification partition."""
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    definitions = config.get("groups", {})
    all_tests = sorted(
        path.relative_to(root).as_posix() for path in (root / "tests").glob("test_*.py")
    )
    assigned: set[str] = set()
    groups: list[dict[str, Any]] = []
    module_paths = _local_module_paths(root)
    for name, definition in definitions.items():
        patterns = list(map(str, definition.get("include_patterns", ())))
        members = [
            path
            for path in all_tests
            if path not in assigned
            and any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        ]
        if not members:
            raise ValueError(f"test group has no exclusively assigned members: {name}")
        assigned.update(members)
        inputs = _local_python_dependencies(root, members, module_paths)
        timeout = validate_timeout(definition.get("timeout_seconds"))
        disk_work_units = definition.get("disk_work_units", 1)
        disk_limit = aggregate_test_disk_consumption_limit(disk_work_units)
        groups.append(
            {
                "schema_version": "px.test-group/1.0",
                "valid": True,
                "group": name,
                "description": str(definition.get("description", "")),
                "members": members,
                "member_count": len(members),
                "inputs": inputs,
                "input_sha256": _fingerprint(root, inputs),
                "parallel_safe": definition.get("parallel_safe") is True,
                "timeout_seconds": timeout,
                "disk_work_units": disk_work_units,
                "disk_consumption_limit_bytes": disk_limit,
                "environment": dict(config.get("environment", {})),
                "command": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--durations=20",
                    "-p",
                    "no:cacheprovider",
                    *members,
                ],
            }
        )
    missing = sorted(set(all_tests) - assigned)
    if missing:
        raise ValueError("test groups leave files unassigned: " + ", ".join(missing))
    return groups


def _group_topology_sha256(config: Mapping[str, Any]) -> str:
    value = {
        "groups": config.get("groups", {}),
        "required_groups": config.get("certification", {}).get("required_groups", []),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _build_test_group_index_direct(root: Path) -> dict[str, Any]:
    from .verification_status import build_index
    return build_index(root)


def build_test_group_index(root: Path) -> dict[str, Any]:
    """Admit the expensive Python inventory through the canonical work plane."""
    from .work_admission import RuntimeWorkPlane

    resolved = root.resolve()
    work = RuntimeWorkPlane(resolved).execute(
        "test-index.build",
        lambda: _build_test_group_index_direct(resolved),
        reason="explicit test topology regeneration",
        input_fingerprint={
            "root": resolved.as_posix(),
            "profiles_sha256": hashlib.sha256(
                (resolved / "registry/test_profiles.json").read_bytes()
            ).hexdigest(),
        },
        domains=("tests", "validation"),
        lane="heavy",
        cache_seconds=0,
        timeout_seconds=300,
        authoritative=True,
    )
    return work["result"]


def resolve_test_groups(root: Path) -> list[dict[str, Any]]:
    from .verification_status import resolve_groups
    return resolve_groups(root)


def resolve_test_group(root: Path, name: str) -> dict[str, Any]:
    return next(
        (group for group in resolve_test_groups(root) if group["group"] == name), None
    ) or (_ for _ in ()).throw(ValueError(f"unknown test group: {name}"))


def group_receipt(group: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    from .verification_receipts import make_receipt
    return make_receipt('group', group, execution)


def write_group_receipt(root: Path, receipt: Mapping[str, Any]) -> Path:
    from .verification_receipts import write
    return write(root, 'group', receipt)


def group_status(root: Path) -> dict[str, Any]:
    from .verification_status import group_status as status
    return status(root)


def cross_group_certification(root: Path) -> dict[str, Any]:
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    certification = config.get("certification", {})
    command = [
        sys.executable if value == "python" else str(value)
        for value in certification.get("cross_group_command", ())
    ]
    if not command:
        raise ValueError("cross-group certification command is missing")
    return {
        "command": command,
        "timeout_seconds": validate_timeout(
            certification.get("cross_group_timeout_seconds")
        ),
        "environment": dict(config.get("environment", {})),
    }
