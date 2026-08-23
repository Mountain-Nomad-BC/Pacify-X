"""Read-only attribution for host startup and skill-discovery boundaries.

PX can report timestamps emitted by VS Code and Codex, but it does not own
those processes and must not turn temporal proximity into a causal claim.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable, Mapping

from .native_skills import validate_skill_index


SCHEMA = "px.host-startup-attribution/1.0"
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")
_MAX_LOG_BYTES = 16 * 1024 * 1024


def _timestamp(line: str) -> datetime | None:
    match = _STAMP.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def _read_tail(path: Path) -> tuple[list[str], bool]:
    size = path.stat().st_size
    with path.open("rb") as stream:
        if size > _MAX_LOG_BYTES:
            stream.seek(size - _MAX_LOG_BYTES)
            stream.readline()
        payload = stream.read()
    return payload.decode("utf-8", errors="replace").splitlines(), size > _MAX_LOG_BYTES


def _latest_substantive_session(logs_root: Path) -> tuple[Path, Path, Path] | None:
    if not logs_root.is_dir():
        return None
    for session in sorted(
        (path for path in logs_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )[:64]:
        candidates = sorted(
            session.glob("window*/exthost/openai.chatgpt/Codex.log"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for codex in candidates:
            exthost = codex.parents[1] / "exthost.log"
            if exthost.is_file():
                return session, exthost, codex
    return None


def startup_log_revision(logs_root: Path | None = None) -> dict[str, object]:
    """Return compact metadata that invalidates cached attribution on log change."""
    resolved_logs = logs_root
    if resolved_logs is None:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return {"available": False, "reason": "APPDATA unavailable"}
        resolved_logs = Path(appdata) / "Code" / "logs"
    selected = _latest_substantive_session(resolved_logs.resolve())
    if selected is None:
        return {"available": False, "reason": "no substantive session"}
    session, exthost, codex = selected
    return {
        "available": True,
        "session": session.name,
        "exthost": {"size": exthost.stat().st_size, "mtime_ns": exthost.stat().st_mtime_ns},
        "codex": {"size": codex.stat().st_size, "mtime_ns": codex.stat().st_mtime_ns},
    }


def _last_matching(lines: Iterable[str], pattern: str) -> tuple[datetime, str] | None:
    expression = re.compile(pattern, re.I)
    matches = [(_timestamp(line), line) for line in lines if expression.search(line)]
    valid = [(stamp, line) for stamp, line in matches if stamp is not None]
    return max(valid, key=lambda row: row[0]) if valid else None


def _first_matching(
    lines: Iterable[str], pattern: str, *, after: datetime
) -> tuple[datetime, str] | None:
    expression = re.compile(pattern, re.I)
    for line in lines:
        stamp = _timestamp(line)
        if stamp is not None and stamp >= after and expression.search(line):
            return stamp, line
    return None


def startup_attribution(logs_root: Path | None = None) -> dict[str, Any]:
    """Return the latest observable VS Code/Codex startup cycle.

    The report exposes only component markers and durations. It deliberately
    omits log payloads, URLs, account data, conversation IDs, and command text.
    """
    resolved_logs = logs_root
    if resolved_logs is None:
        appdata = os.environ.get("APPDATA")
        resolved_logs = Path(appdata) / "Code" / "logs" if appdata else Path()
    selected = _latest_substantive_session(resolved_logs.resolve())
    if selected is None:
        return {
            "schema_version": SCHEMA,
            "available": False,
            "source": "VS Code/Codex host logs",
            "ownership": "external-host-observation",
            "limitations": ["No substantive VS Code session containing a Codex log was found."],
        }
    session, exthost_path, codex_path = selected
    exthost, exthost_truncated = _read_tail(exthost_path)
    codex, codex_truncated = _read_tail(codex_path)
    host_start = _last_matching(exthost, r"Extension host with pid \d+ started")
    if host_start is None:
        return {
            "schema_version": SCHEMA,
            "available": False,
            "source_session": session.name,
            "ownership": "external-host-observation",
            "limitations": ["The latest Codex log has no matching extension-host start marker."],
        }
    cycle_start = host_start[0]
    start_markers = sorted(
        stamp
        for line in exthost
        if re.search(r"Extension host with pid \d+ started", line)
        and (stamp := _timestamp(line)) is not None
    )
    earlier_starts = len(start_markers)
    specifications = (
        ("vscode.extension-host", "vscode-host", exthost, r"Extension host with pid \d+ started", "observed-start"),
        ("openai.codex.activation", "codex-host", codex, r"Activating Codex extension", "observed-start"),
        ("openai.codex.app-server-initialize", "codex-host", codex, r"Initialize received id=", "initialize-received"),
        ("github.copilot.activation-request", "github-copilot-host", exthost, r"_doActivateExtension GitHub\.copilot-chat", "activation-requested"),
        ("python.extension.activation-request", "python-extension-host", exthost, r"_doActivateExtension ms-python\.python", "activation-requested"),
        ("pacify-x.extension.activation-request", "pacify-x-extension", exthost, r"_doActivateExtension mountain-nomad-bc\.pacify-x-vscode", "activation-requested"),
        ("vscode.eager-extensions", "vscode-host", exthost, r"Eager extensions activated", "observed-ready"),
        ("openai.codex.account-lookup", "codex-host", codex, r"chatgpt-account-lookup.*completed", "observed-ready"),
        ("openai.codex.renderer-routes", "codex-host", codex, r"\[startup\]\[renderer\] app routes mounted", "observed-ready"),
        ("openai.codex.skill-loader-activity", "codex-host", codex, r"codex_core_skills::loader", "activity-observed-not-ready"),
        ("openai.codex.plugin-loader-activity", "codex-host", codex, r"codex_core_plugins::loader", "activity-observed-not-ready"),
        ("openai.codex.thread-resume", "codex-host", codex, r"maybe_resume_success", "observed-usable-existing-thread"),
    )
    milestones: list[dict[str, Any]] = []
    for identifier, owner, lines, pattern, status in specifications:
        match = (
            host_start
            if identifier == "vscode.extension-host"
            else _first_matching(lines, pattern, after=cycle_start)
        )
        milestones.append(
            {
                "id": identifier,
                "owner": owner,
                "status": status if match else "not-observed",
                "observed": match is not None,
                "timestamp_local": match[0].isoformat(timespec="milliseconds") if match else None,
                "offset_from_extension_host_ms": (
                    round((match[0] - cycle_start).total_seconds() * 1000)
                    if match
                    else None
                ),
                "evidence_marker": pattern,
            }
        )
    milestones.extend(
        {
            "id": identifier,
            "owner": "codex-host",
            "status": "host-marker-not-emitted",
            "observed": False,
            "timestamp_local": None,
            "offset_from_extension_host_ms": None,
            "evidence_marker": None,
        }
        for identifier in (
            "openai.codex.skill-discovery-complete",
            "openai.codex.configured-mcp-readiness",
            "openai.codex.first-usable-tool",
        )
    )
    observed = sorted(
        (row for row in milestones if row["observed"]),
        key=lambda row: int(row["offset_from_extension_host_ms"]),
    )
    previous = 0
    for row in observed:
        current = int(row["offset_from_extension_host_ms"])
        row["delta_from_previous_observed_ms"] = current - previous
        previous = current
    by_id = {row["id"]: row for row in milestones}

    def offset(identifier: str) -> int | None:
        value = by_id[identifier]["offset_from_extension_host_ms"]
        return int(value) if value is not None else None

    activation = offset("openai.codex.activation")
    routes = offset("openai.codex.renderer-routes")
    resumed = offset("openai.codex.thread-resume")

    def cycle_summary(start: datetime, label: str) -> dict[str, object]:
        next_start = next((item for item in start_markers if item > start), None)

        def within(lines: Iterable[str], pattern: str) -> datetime | None:
            match = _first_matching(lines, pattern, after=start)
            if match is None or (next_start is not None and match[0] >= next_start):
                return None
            return match[0]

        cycle_activation = within(codex, r"Activating Codex extension")
        cycle_routes = within(codex, r"\[startup\]\[renderer\] app routes mounted")
        cycle_resume = within(codex, r"maybe_resume_success")
        cycle_eager = within(exthost, r"Eager extensions activated")

        def elapsed(stamp: datetime | None) -> int | None:
            return round((stamp - start).total_seconds() * 1000) if stamp else None

        return {
            "cycle": label,
            "extension_host_started_local": start.isoformat(timespec="milliseconds"),
            "extension_host_to_eager_extensions_ms": elapsed(cycle_eager),
            "extension_host_to_codex_routes_ms": elapsed(cycle_routes),
            "extension_host_to_existing_thread_resume_ms": elapsed(cycle_resume),
            "codex_activation_to_existing_thread_resume_ms": (
                round((cycle_resume - cycle_activation).total_seconds() * 1000)
                if cycle_resume and cycle_activation
                else None
            ),
        }

    comparisons = []
    if start_markers:
        comparisons.append(cycle_summary(start_markers[0], "session-first-extension-host"))
        if start_markers[-1] != start_markers[0]:
            comparisons.append(cycle_summary(start_markers[-1], "latest-warm-extension-host-restart"))

    main_path = session / "main.log"
    gateway_path = session / "mcpGateway.log"
    main_lines, _ = _read_tail(main_path) if main_path.is_file() else ([], False)
    gateway_lines, _ = _read_tail(gateway_path) if gateway_path.is_file() else ([], False)
    vscode_launch = next(
        (stamp for line in main_lines if (stamp := _timestamp(line)) is not None), None
    )
    gateway_ready = _first_matching(
        gateway_lines,
        r"McpGatewayService.*Initialized",
        after=vscode_launch or datetime.min,
    )
    return {
        "schema_version": SCHEMA,
        "available": True,
        "source_session": session.name,
        "cycle": "warm-extension-host-restart" if earlier_starts > 1 else "session-first-extension-host",
        "timestamp_basis": "host-local-log-time-without-offset",
        "ownership": "VS Code, Codex, Copilot, Python, and PX remain separate owners",
        "milestones": milestones,
        "durations_ms": {
            "extension_host_to_eager_extensions": offset("vscode.eager-extensions"),
            "extension_host_to_codex_routes": routes,
            "extension_host_to_existing_thread_resume": resumed,
            "codex_activation_to_routes": routes - activation if routes is not None and activation is not None else None,
            "codex_activation_to_existing_thread_resume": resumed - activation if resumed is not None and activation is not None else None,
        },
        "cycle_comparison": comparisons,
        "vscode_launch": {
            "observed": vscode_launch is not None,
            "timestamp_local": vscode_launch.isoformat(timespec="milliseconds") if vscode_launch else None,
            "launch_to_first_extension_host_ms": (
                round((start_markers[0] - vscode_launch).total_seconds() * 1000)
                if vscode_launch and start_markers
                else None
            ),
            "marker": "first timestamp emitted in main.log; process creation may predate it",
        },
        "px_attribution": {
            "activation_request_offset_ms": offset("pacify-x.extension.activation-request"),
            "causal_contribution_to_codex_readiness": "not-established-by-host-logs",
            "must_not_attribute_vscode_or_codex_host_costs_to_px": True,
        },
        "mcp": {
            "codex_app_server_initialize_observed": by_id["openai.codex.app-server-initialize"]["observed"],
            "vscode_gateway_initialized": gateway_ready is not None,
            "vscode_gateway_offset_from_launch_ms": (
                round((gateway_ready[0] - vscode_launch).total_seconds() * 1000)
                if gateway_ready and vscode_launch
                else None
            ),
            "configured_server_readiness_observable": False,
        },
        "log_tail_truncated": exthost_truncated or codex_truncated,
        "limitations": [
            "Markers are host observations, not causal proof or a benchmark.",
            "The host log does not emit a complete skill-discovery duration.",
            "The host log does not expose readiness for every configured MCP server.",
            "Existing-thread resume is not proof of first successful tool execution.",
        ],
    }


def skill_index_integrity(root: Path) -> dict[str, Any]:
    """Compare all current native skill projections from the same record set."""
    root = root.resolve()
    index = json.loads((root / ".px" / "skill-index.json").read_text(encoding="utf-8"))
    validation = validate_skill_index(index, require_derived=True)
    native_ids = {
        str(row["id"])
        for row in index["records"]
        if row.get("domain") == "px-standard" and row.get("native")
    }
    catalog = tomllib.loads(
        (root / "registry" / "skill_catalog.toml").read_text(encoding="utf-8")
    )
    catalog_ids = {str(row["id"]) for row in catalog.get("skills", ())}
    directory_ids = {
        path.name for path in (root / ".px" / "skills").iterdir() if path.is_dir()
    }
    projection_ids = {
        path.stem for path in (root / "registry" / "skill_packages").glob("*.json")
    }
    equal = native_ids == catalog_ids == directory_ids == projection_ids
    return {
        "schema_version": "px.skill-index-integrity/1.0",
        "valid": bool(validation.get("valid")) and equal,
        "revision": validation["revision"],
        "declared_record_count": index.get("record_count"),
        "derived_domain_counts": validation["counts"],
        "projections": {
            "native_index": len(native_ids),
            "catalog": len(catalog_ids),
            "package_directories": len(directory_ids),
            "package_records": len(projection_ids),
        },
        "differences": {
            "catalog_only": sorted(catalog_ids - native_ids),
            "index_only": sorted(native_ids - catalog_ids),
            "directory_only": sorted(directory_ids - native_ids),
            "package_record_only": sorted(projection_ids - native_ids),
        },
        "publication_rule": "records, counts, revision, catalog, package directories, and package records must agree before publication",
    }


def skill_host_boundary(
    root: Path, *, global_skills_root: Path | None = None
) -> dict[str, Any]:
    """Report the enforceable PX boundary and the Codex-owned global gap."""
    root = root.resolve()
    if global_skills_root is not None:
        host_root: Path | None = global_skills_root.resolve()
    else:
        try:
            host_root = (Path.home() / ".agents" / "skills").resolve()
        except RuntimeError:
            host_root = None
    host_skills = sorted(
        path.parent.relative_to(host_root).as_posix()
        for path in host_root.rglob("SKILL.md")
    ) if host_root is not None and host_root.is_dir() else []
    microsoft = [identifier for identifier in host_skills if "microsoft-foundry" in identifier.casefold().split("/")]
    facades = sorted(
        path.parent.name for path in (root / ".agents" / "skills").glob("*/SKILL.md")
    )
    isolation_journal_path = root / ".px" / "global-skill-isolation" / "journal.json"
    isolation_journal = (
        json.loads(isolation_journal_path.read_text(encoding="utf-8"))
        if isolation_journal_path.is_file()
        else None
    )
    policy_path = root / "policies" / "codex-host-skill-boundary.json"
    policy = (
        json.loads(policy_path.read_text(encoding="utf-8"))
        if policy_path.is_file()
        else {}
    )
    remediation = policy.get("remediation", {}) if isinstance(policy, Mapping) else {}
    return {
        "schema_version": "px.codex-skill-host-boundary/1.0",
        "status": (
            "host-skill-root-unavailable"
            if host_root is None
            else "host-visible-global-skills-outside-px-enforcement"
            if host_skills
            else "no-global-skills-observed"
        ),
        "project": {
            "facade_count": len(facades),
            "facade_only": 10 <= len(facades) <= 20 and all(item.startswith("px-") for item in facades),
            "selection": "PX metadata query; maximum three candidates; exactly one body hydrated",
            "default_domains": ["px-standard"],
        },
        "codex_host": {
            "authority": "Codex retains native skill discovery, selection, execution, and approval authority",
            "global_skill_root": host_root.as_posix() if host_root is not None else None,
            "global_skill_count": len(host_skills),
            "global_skill_ids": host_skills,
            "px_policy_enforced_during_direct_host_selection": False,
        },
        "microsoft_foundry": {
            "directly_host_visible": bool(microsoft),
            "skill_count": len(microsoft),
            "skill_ids": microsoft,
            "px_broker_requires_explicit_intent_and_grant": True,
        },
        "isolation_transaction": {
            "available": isolation_journal is not None,
            "state": isolation_journal.get("state") if isolation_journal else "not-started",
            "journal": isolation_journal_path.relative_to(root).as_posix(),
            "preview_command": "python -m runtime.cli --root . skill-host-isolation preview",
            "apply_requires_explicit_command": True,
            "restore_command": "python -m runtime.cli --root . skill-host-isolation restore-preview",
        },
        "policy_source": policy_path.relative_to(root).as_posix() if policy_path.is_file() else None,
        "policy_schema_version": policy.get("schema_version"),
        "limitation": policy.get("host_limitation") or "Repository PX policy cannot prevent the Codex host from directly enumerating user-global .agents skills.",
        "remediation": {
            "required_owner": remediation.get("owner") or "Codex host or user configuration",
            "preferred": remediation.get("preferred") or "Use a host-supported workspace profile or allowlist that exposes only project PX facades by default.",
            "until_supported": remediation.get("interim") or "Treat global vendor skills as host-visible, require explicit vendor intent, and never claim PX-enforced isolation.",
            "px_must_not_modify_user_codex_configuration": True,
        },
    }
