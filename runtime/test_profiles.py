"""Deterministic fast/full/release test profile resolution."""

from __future__ import annotations

import json
import fnmatch
import hashlib
import hmac
import ast
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from .test_runner import validate_timeout


REPAIR_CAMPAIGN_PATH = Path("registry/repair_campaign.json")
MANAGED_PROJECT_MARKER = Path(".engineering-bootstrap/project-record.json")
PROJECT_REPAIR_CAMPAIGN_PATH = Path(
    ".engineering-bootstrap/processing-order/repair-campaign.json"
)
PROCESSING_PHASES = (
    "intake", "repair", "operational_verification", "repair_frozen",
    "revision_reconciled", "sections_current", "full_profile_passed",
    "validated", "packaged", "installed_operational", "certified",
)
STAGE_MINIMUM_PHASE = {
    "diagnose": "intake", "repair": "repair", "focused_test": "repair",
    "governed_section": "repair", "operational_verification": "operational_verification",
    "revision_reconciliation": "repair_frozen", "full_profile": "sections_current",
    "validate": "full_profile_passed", "package": "validated", "install": "packaged",
    "installed_operational_test": "installed_operational", "certify": "installed_operational",
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
    minimum = STAGE_MINIMUM_PHASE.get(stage)
    if minimum is None:
        raise ValueError(f"unknown processing stage: {stage}")
    if stage in CLOSURE_STAGES and (intake_open or unresolved):
        return False
    return PROCESSING_PHASES.index(phase) >= PROCESSING_PHASES.index(minimum)


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
        raise ProcessingOrderBlocked(
            f"PROCESSING_ORDER_BLOCKED: {stage} requires phase {STAGE_MINIMUM_PHASE[stage]}; "
            f"current={status['phase']}; intake_open={str(status['intake_open']).lower()}; "
            f"unresolved={unresolved}"
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
    # Expand only the declared roots. A whole-repository walk here made compact
    # section-status checks traverse retained project maps, environments, and
    # custody trees even though none could match the section patterns.
    matched: set[str] = set()
    for pattern in patterns:
        # Path.glob('directory/**') has different descendant semantics across
        # supported CPython releases. Expand that recursive form explicitly so
        # receipt identities remain runtime- and platform-stable.
        normalized = pattern.replace("\\", "/")
        if normalized.endswith("/**"):
            base = root / normalized[:-3]
            candidates = base.rglob("*") if base.is_dir() else ()
        else:
            candidates = root.glob(pattern)
        for path in candidates:
            if path.is_file():
                matched.add(path.relative_to(root).as_posix())
    return sorted(matched)


def _structural_scan_files(root: Path, max_bytes: int = 1_000_000) -> list[str]:
    """Return the incompleteness scanner's exact governed source inventory."""

    from .repository_scope import is_external_environment_relative

    excluded = {
        ".git",
        ".venv",
        ".vscode-test",
        "python",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "quarantine",
        "__pycache__",
    }
    suffixes = {".py", ".js", ".jsx", ".ts", ".tsx"}
    paths: list[str] = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        relative_current = Path(current).relative_to(root)
        if is_external_environment_relative(relative_current):
            dirs[:] = []
            continue
        folded_parts = tuple(part.casefold() for part in relative_current.parts)
        if len(folded_parts) >= 2 and folded_parts[:2] == (
            ".px",
            "preserved-skills",
        ):
            dirs[:] = []
            continue
        dirs[:] = sorted(
            (
                name
                for name in dirs
                if name.casefold() not in excluded
                and not name.casefold().startswith(".venv")
                and not is_external_environment_relative(relative_current / name)
            ),
            key=str.casefold,
        )
        for name in sorted(files, key=str.casefold):
            path = Path(current, name)
            try:
                eligible = (
                    path.suffix.casefold() in suffixes
                    and not is_external_environment_relative(path.relative_to(root))
                    and not path.is_symlink()
                    and path.stat().st_size <= max_bytes
                )
            except OSError:
                eligible = False
            if eligible:
                paths.append(path.relative_to(root).as_posix())
    return sorted(paths)


def _fingerprint(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        payload = (root / relative).read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def resolve_test_section(root: Path, name: str) -> dict[str, Any]:
    """Resolve one affected test section and its exact content identity."""
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    section = config.get("sections", {}).get(name)
    if not isinstance(section, dict):
        raise ValueError(f"unknown test section: {name}")
    patterns = list(map(str, section.get("source_patterns", ())))
    inputs = _section_files(root, patterns)
    if not inputs:
        raise ValueError(f"test section has no current inputs: {name}")
    command = list(map(str, section.get("command", ())))
    if not command:
        raise ValueError(f"test section has no command: {name}")
    cwd = (root / str(section.get("cwd", "."))).resolve()
    if cwd != root and root not in cwd.parents:
        raise ValueError("test section cwd escapes repository root")
    timeout = validate_timeout(section.get("timeout_seconds"))
    section_input_sha256 = _fingerprint(root, inputs)
    chunks: list[dict[str, object]] = []
    chunk_size = int(section.get("chunk_size", 0) or 0)
    max_parallel_chunks = int(section.get("max_parallel_chunks", 1) or 1)
    if chunk_size:
        if not 1 <= chunk_size <= 20 or not 1 <= max_parallel_chunks <= 8:
            raise ValueError("test section chunk bounds are invalid")
        chunk_timeout = validate_timeout(section.get("chunk_timeout_seconds"))
        members = [
            value
            for value in command
            if not value.startswith("-") and (cwd / value).is_file()
        ]
        if len(members) < 2:
            raise ValueError("chunked test section requires at least two file members")
        member_set = set(members)
        base_command = [value for value in command if value not in member_set]
        member_inputs = {
            (cwd / value).resolve().relative_to(root).as_posix(): value
            for value in members
        }
        shared_inputs = sorted(set(inputs) - set(member_inputs))
        for index in range(0, len(members), chunk_size):
            selected = members[index : index + chunk_size]
            chunk_id = f"chunk-{index // chunk_size + 1:02d}"
            selected_inputs = sorted(
                (cwd / value).resolve().relative_to(root).as_posix()
                for value in selected
            )
            chunk_inputs = sorted({*shared_inputs, *selected_inputs})
            identity = hashlib.sha256(
                json.dumps(
                    {
                        "content_sha256": _fingerprint(root, chunk_inputs),
                        "chunk_id": chunk_id,
                        "command": [*base_command, *selected],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "members": selected,
                    "member_count": len(selected),
                    "inputs": chunk_inputs,
                    "command": [*base_command, *selected],
                    "input_sha256": identity,
                    "timeout_seconds": chunk_timeout,
                }
            )
    return {
        "schema_version": "px.test-section/1.0",
        "valid": True,
        "section": name,
        "description": str(section.get("description", "")),
        "dependencies": sorted(set(map(str, section.get("dependencies", ())))),
        "inputs": inputs,
        "input_sha256": section_input_sha256,
        "command": command,
        "cwd": str(cwd),
        "cwd_relative": cwd.relative_to(root).as_posix() or ".",
        "timeout_seconds": timeout,
        "chunks": chunks,
        "max_parallel_chunks": max_parallel_chunks if chunks else 1,
        "environment": {
            **config.get("environment", {}),
            **section.get("environment", {}),
        },
    }


def section_receipt(
    section: dict[str, Any], execution: dict[str, Any]
) -> dict[str, Any]:
    exit_code = execution.get("exit_code", execution.get("returncode"))
    body = {
        "schema_version": "px.test-section-receipt/1.0",
        "section": section["section"],
        "input_sha256": section["input_sha256"],
        "dependencies": section["dependencies"],
        "command": section["command"],
        "cwd": section.get("cwd_relative", "."),
        "passed": (
            exit_code == 0
            and execution.get("timed_out") is not True
            and execution.get("valid", True) is True
        ),
        "exit_code": exit_code,
        "timed_out": bool(execution.get("timed_out")),
        "duration_seconds": execution.get("duration_seconds"),
        "chunks": list(execution.get("chunks", [])),
    }
    return {
        **body,
        "receipt_sha256": hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def section_chunk_receipt(
    section: Mapping[str, Any], chunk: Mapping[str, Any], execution: Mapping[str, Any]
) -> dict[str, Any]:
    exit_code = execution.get("exit_code")
    body = {
        "schema_version": "px.test-section-chunk-receipt/1.0",
        "section": section["section"],
        "chunk_id": chunk["chunk_id"],
        "input_sha256": chunk["input_sha256"],
        "member_count": chunk["member_count"],
        "passed": exit_code == 0
        and execution.get("timed_out") is not True
        and execution.get("valid") is True,
        "exit_code": exit_code,
        "timed_out": bool(execution.get("timed_out")),
        "duration_seconds": execution.get("duration_seconds"),
    }
    return {
        **body,
        "receipt_sha256": hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def section_chunk_receipt_path(root: Path, section: str, chunk_id: str) -> Path:
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in f"{section}{chunk_id}"
    ):
        raise ValueError("section chunk receipt identity is invalid")
    return root.resolve() / ".engineering-bootstrap/test-evidence/section-chunks" / section / f"{chunk_id}.json"


def read_section_chunk_receipt(root: Path, section: str, chunk_id: str) -> dict[str, Any]:
    try:
        value = json.loads(
            section_chunk_receipt_path(root, section, chunk_id).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    expected_keys = {
        "schema_version",
        "section",
        "chunk_id",
        "input_sha256",
        "member_count",
        "passed",
        "exit_code",
        "timed_out",
        "duration_seconds",
        "receipt_sha256",
    }
    if (
        set(value) != expected_keys
        or value.get("schema_version") != "px.test-section-chunk-receipt/1.0"
        or value.get("section") != section
        or value.get("chunk_id") != chunk_id
    ):
        return {}
    supplied = str(value.get("receipt_sha256") or "")
    body = {key: value[key] for key in expected_keys - {"receipt_sha256"}}
    expected = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value if hmac.compare_digest(supplied, expected) else {}


def write_section_chunk_receipt(root: Path, receipt: Mapping[str, Any]) -> Path:
    target = section_chunk_receipt_path(
        root, str(receipt.get("section", "")), str(receipt.get("chunk_id", ""))
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".json.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, target)
    return target


def write_section_receipt(root: Path, receipt: Mapping[str, Any]) -> Path:
    """Atomically retain the latest exact-input receipt for one section."""
    root = root.resolve()
    name = str(receipt.get("section", ""))
    if not name or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name
    ):
        raise ValueError("section receipt name is invalid")
    target = root / ".engineering-bootstrap/test-evidence/sections" / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".json.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, target)
    return target


def section_status(root: Path) -> dict[str, Any]:
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    receipt_root = root / ".engineering-bootstrap/test-evidence/sections"
    rows = []
    for name in sorted(config.get("sections", {})):
        current = resolve_test_section(root, name)
        path = receipt_root / f"{name}.json"
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipt = {}
        passed = receipt.get("passed") is True
        fresh = receipt.get("input_sha256") == current["input_sha256"]
        rows.append(
            {
                "section": name,
                "dependencies": current["dependencies"],
                "passed": passed,
                "fresh": fresh,
                "dependencies_current": False,
                "current": False,
                "input_sha256": current["input_sha256"],
                "receipt": path.as_posix(),
            }
        )
    by_name = {row["section"]: row for row in rows}

    def current(name: str, visiting: frozenset[str] = frozenset()) -> bool:
        if name in visiting or name not in by_name:
            return False
        row = by_name[name]
        dependencies_current = all(
            current(dependency, visiting | {name}) for dependency in row["dependencies"]
        )
        row["dependencies_current"] = dependencies_current
        row["current"] = row["passed"] and row["fresh"] and dependencies_current
        return bool(row["current"])

    for name in by_name:
        current(name)
    required = list(
        map(str, config.get("certification", {}).get("required_sections", ()))
    )
    return {
        "schema_version": "px.test-section-status/1.0",
        "valid": all(by_name.get(name, {}).get("current") is True for name in required),
        "required_sections": required,
        "sections": rows,
    }


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


def _local_python_dependencies(
    root: Path, members: list[str], module_paths: Mapping[str, str] | None = None
) -> list[str]:
    """Resolve deterministic local Python import closure for group freshness."""
    module_paths = dict(module_paths or _local_module_paths(root))
    selected = set(members)
    pending = list(members)
    while pending:
        relative = pending.pop()
        path = root / relative
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError):
            continue
        candidates: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                candidates.add(node.module)
        for candidate in candidates:
            parts = candidate.split(".")
            while parts:
                module = ".".join(parts)
                dependency = module_paths.get(module)
                if dependency:
                    if dependency not in selected:
                        selected.add(dependency)
                        pending.append(dependency)
                    break
                parts.pop()
    selected.add("registry/test_profiles.json")
    return sorted(selected)


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
    """Build or incrementally update the native certification-group manifest."""
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    target = root / "registry/test_group_index.json"
    try:
        previous = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}
    prior_files = (
        previous.get("files", {}) if isinstance(previous.get("files"), dict) else {}
    )
    paths = sorted(
        {
            *(
                path.relative_to(root).as_posix()
                for path in (root / "tests").glob("test_*.py")
            ),
            *(
                path.relative_to(root).as_posix()
                for top in ("runtime", "builders", "scripts")
                for path in (root / top).rglob("*.py")
            ),
        }
    )
    records: dict[str, dict[str, Any]] = {}
    for relative in paths:
        payload = (root / relative).read_bytes()
        sha256 = hashlib.sha256(payload).hexdigest()
        prior = prior_files.get(relative, {})
        if prior.get("sha256") == sha256 and isinstance(prior.get("imports"), list):
            imports = list(map(str, prior["imports"]))
        else:
            tree = ast.parse(payload.decode("utf-8"), filename=relative)
            imports = sorted(
                {
                    *(
                        alias.name
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Import)
                        for alias in node.names
                    ),
                    *(
                        node.module
                        for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom)
                        and node.level == 0
                        and node.module
                    ),
                }
            )
        records[relative] = {
            "sha256": sha256,
            "imports": imports,
            "index_state": "verified",
        }
    module_paths: dict[str, str] = {}
    for relative in paths:
        if not relative.startswith(("runtime/", "builders/", "scripts/")):
            continue
        parts = list(Path(relative).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module_paths[".".join(parts)] = relative
    all_tests = sorted(
        relative for relative in paths if relative.startswith("tests/test_")
    )
    assigned: set[str] = set()
    groups = []
    for name, definition in config.get("groups", {}).items():
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
        selected = set(members)
        pending = list(members)
        while pending:
            relative = pending.pop()
            for candidate in records.get(relative, {}).get("imports", ()):
                parts = str(candidate).split(".")
                while parts:
                    dependency = module_paths.get(".".join(parts))
                    if dependency:
                        if dependency not in selected:
                            selected.add(dependency)
                            pending.append(dependency)
                        break
                    parts.pop()
        declared_inputs: set[str] = set()
        for pattern in map(str, definition.get("input_patterns", ())):
            for path in root.glob(pattern):
                if path.is_file():
                    declared_inputs.add(path.relative_to(root).as_posix())
        base_inputs = sorted(
            {*selected, *declared_inputs, "registry/test_profiles.json"}
        )
        scan_inputs = (
            _structural_scan_files(root)
            if name == "structural-adversarial"
            else []
        )
        inputs = sorted({*base_inputs, *scan_inputs})
        groups.append(
            {
                "group": name,
                "description": str(definition.get("description", "")),
                "members": members,
                "member_count": len(members),
                "inputs": inputs,
                "base_inputs": base_inputs,
                "scan_inputs": scan_inputs,
                "input_sha256": _fingerprint(root, inputs),
                "parallel_safe": definition.get("parallel_safe") is True,
                "timeout_seconds": validate_timeout(definition.get("timeout_seconds")),
            }
        )
    missing = sorted(set(all_tests) - assigned)
    if missing:
        raise ValueError("test groups leave files unassigned: " + ", ".join(missing))
    return {
        "schema_version": "px.test-group-index/1.1",
        "topology_sha256": _group_topology_sha256(config),
        "test_file_count": len(all_tests),
        "tracked_python_file_count": len(records),
        "verified_file_count": len(records),
        "files": records,
        "groups": groups,
    }


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
    """Read compact native group metadata; never rediscover during status."""
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    path = root / "registry/test_group_index.json"
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            "test group index missing or corrupt; run python scripts/build_test_group_index.py"
        ) from error
    if index.get("topology_sha256") != _group_topology_sha256(config):
        raise ValueError(
            "test group topology is stale; run python scripts/build_test_group_index.py"
        )
    current_tests = sorted(
        path.relative_to(root).as_posix() for path in (root / "tests").glob("test_*.py")
    )
    indexed_tests = sorted(
        member
        for group in index.get("groups", ())
        for member in group.get("members", ())
    )
    if current_tests != indexed_tests:
        raise ValueError(
            "test group membership is stale; run python scripts/build_test_group_index.py"
        )
    environment = dict(config.get("environment", {}))
    groups = []
    for stored in index.get("groups", ()):
        group_name = str(stored.get("group", ""))
        stored_scan_inputs = list(map(str, stored.get("scan_inputs", ())))
        base_inputs = list(
            map(str, stored.get("base_inputs", stored.get("inputs", ())))
        )
        current_scan_inputs = (
            _structural_scan_files(root)
            if group_name == "structural-adversarial"
            else []
        )
        inputs = sorted({*base_inputs, *current_scan_inputs})
        try:
            current_sha256 = _fingerprint(root, inputs)
        except OSError:
            current_sha256 = ""
        inventory_current = current_scan_inputs == stored_scan_inputs
        index_current = (
            inventory_current and current_sha256 == stored.get("input_sha256")
        )
        groups.append(
            {
                "schema_version": "px.test-group/1.0",
                "valid": index_current,
                **stored,
                "index_current": index_current,
                "scan_inventory_current": inventory_current,
                "input_sha256": current_sha256,
                "indexed_input_sha256": stored.get("input_sha256"),
                "environment": environment,
                "command": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--durations=20",
                    "-p",
                    "no:cacheprovider",
                    *stored["members"],
                ],
            }
        )
    return groups


def resolve_test_group(root: Path, name: str) -> dict[str, Any]:
    return next(
        (group for group in resolve_test_groups(root) if group["group"] == name), None
    ) or (_ for _ in ()).throw(ValueError(f"unknown test group: {name}"))


def group_receipt(group: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    exit_code = execution.get("exit_code", execution.get("returncode"))
    output_evidence: dict[str, object] = {}
    failure_nodes: list[str] = []
    for stream in ("stdout", "stderr"):
        value = str(execution.get(stream) or "")
        encoded = value.encode("utf-8")
        output_evidence[f"{stream}_sha256"] = hashlib.sha256(encoded).hexdigest()
        output_evidence[f"{stream}_bytes"] = len(encoded)
        for line in value.splitlines():
            if not line.startswith("FAILED "):
                continue
            node = line[len("FAILED ") :].split(" - ", 1)[0].strip()
            if node and node not in failure_nodes:
                failure_nodes.append(node[:300])
    output_evidence["failure_nodes"] = failure_nodes[:50]
    body = {
        "schema_version": "px.test-group-receipt/1.0",
        "group": group["group"],
        "input_sha256": group["input_sha256"],
        "member_count": group["member_count"],
        "passed": (
            exit_code == 0
            and execution.get("timed_out") is not True
            and execution.get("valid", True) is True
        ),
        "exit_code": exit_code,
        "timed_out": bool(execution.get("timed_out")),
        "duration_seconds": execution.get("duration_seconds"),
        # Retain enough bounded evidence to identify a failing chunk without
        # persisting raw command output, environment values, or secret-bearing
        # assertion payloads in the durable receipt.
        "output_evidence": output_evidence,
    }
    return {
        **body,
        "receipt_sha256": hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def write_group_receipt(root: Path, receipt: Mapping[str, Any]) -> Path:
    name = str(receipt.get("group", ""))
    if not name or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name
    ):
        raise ValueError("group receipt name is invalid")
    target = (
        root.resolve() / ".engineering-bootstrap/test-evidence/groups" / f"{name}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".json.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, target)
    return target


def group_status(root: Path) -> dict[str, Any]:
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    required = list(
        map(str, config.get("certification", {}).get("required_groups", ()))
    )
    rows = []
    for group in resolve_test_groups(root):
        path = (
            root
            / ".engineering-bootstrap/test-evidence/groups"
            / f"{group['group']}.json"
        )
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipt = {}
        current = (
            receipt.get("passed") is True
            and receipt.get("input_sha256") == group["input_sha256"]
        )
        rows.append(
            {
                "group": group["group"],
                "member_count": group["member_count"],
                "parallel_safe": group["parallel_safe"],
                "passed": receipt.get("passed") is True,
                "fresh": receipt.get("input_sha256") == group["input_sha256"],
                "current": current,
                "input_sha256": group["input_sha256"],
                "receipt": path.as_posix(),
            }
        )
    by_name = {row["group"]: row for row in rows}
    return {
        "schema_version": "px.test-group-status/1.0",
        "valid": all(by_name.get(name, {}).get("current") is True for name in required),
        "required_groups": required,
        "groups": rows,
        "member_count": sum(row["member_count"] for row in rows),
    }


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
