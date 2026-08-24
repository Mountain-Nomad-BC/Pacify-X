"""Versioned, read-only dashboard and catalog adapter for Pacify-X clients.

The VS Code extension consumes this module instead of opening registries itself.
Detailed catalogs are normalized lazily and returned in bounded pages.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import tomllib
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "2.0.0"
MAX_PAGE_SIZE = 100
HARDWARE_CACHE_TTL_SECONDS = 300.0
HARDWARE_CACHE_MAX_TTL_SECONDS = 3600.0
HARDWARE_CACHE_SCHEMA = "px.hardware-dashboard-cache/1.1"

_DISPLAY_ACRONYMS = {
    "ai": "AI",
    "api": "API",
    "cpu": "CPU",
    "gpu": "GPU",
    "json": "JSON",
    "mcp": "MCP",
    "n8n": "n8n",
    "rag": "RAG",
    "rls": "RLS",
    "ui": "UI",
    "ux": "UX",
    "vram": "VRAM",
    "vscode": "VS Code",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _completion(root: Path) -> dict[str, Any]:
    """Recompute live completion truth; use stored state only as a fallback.

    The registry projection is generated evidence, not an authority that may stay
    green after the operational ledger changes.  Artifact custody can strengthen
    the live result, but its absence must not suppress the ledger-backed rebuild.
    """
    baseline = _read_json(root / "registry" / "completion_status.json", {})
    baseline = dict(baseline) if isinstance(baseline, Mapping) else {}
    runtime_path = (
        root
        / ".engineering-bootstrap"
        / "runtime-core"
        / "completion_status.json"
    )
    runtime_value = _read_json(runtime_path, {})
    artifact_dir: Path | None = None
    if isinstance(runtime_value, Mapping):
        runtime_projection = runtime_value.get("runtime_projection", {})
        artifact_value = (
            runtime_projection.get("artifact_dir")
            if isinstance(runtime_projection, Mapping)
            else None
        )
        if isinstance(artifact_value, str) and artifact_value.strip():
            artifact_dir = Path(artifact_value)
    try:
        from scripts.build_completion_status import build

        if artifact_dir is not None:
            try:
                return dict(build(root, artifact_dir=artifact_dir))
            except (OSError, ValueError, json.JSONDecodeError):
                # A malformed derived binding cannot preserve a prior claim.
                pass
        return dict(build(root))
    except (OSError, ValueError, json.JSONDecodeError):
        fallback = dict(baseline)
        fallback["projection_freshness"] = "stored_fallback_unverified"
        fallback["certified"] = False
        fallback["operationally_complete"] = False
        return fallback


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _version(root: Path) -> str | None:
    try:
        payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        project = payload.get("project", {})
        return str(project.get("version")) if project.get("version") else None
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _array(root: Path, relative: str, field: str) -> list[dict[str, Any]]:
    payload = _read_json(root / relative, {})
    rows = payload.get(field, []) if isinstance(payload, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _skill_rows(root: Path) -> list[dict[str, Any]]:
    payload = _read_json(root / ".px" / "skill-index.json", {})
    records = payload.get("records", []) if isinstance(payload, Mapping) else []
    return [dict(row) for row in records if isinstance(row, Mapping)]


def _workflow_rows(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _array(
        root, "registry/project_stream_orchestrations.json", "orchestrations"
    ):
        result.append(
            {
                **row,
                "catalog_kind": "project-orchestration",
                "execution_class": "bounded_runtime_handler"
                if str(row.get("integration_status", "")).startswith("executable")
                else "definition_only",
            }
        )
    for row in _array(root, "registry/skill_orchestrations.json", "workflows"):
        result.append(
            {
                **row,
                "catalog_kind": "skill-orchestration",
                "execution_class": "definition_only",
            }
        )
    bindings = _read_json(root / "registry" / "workflow_execution_bindings.json", {})
    if isinstance(bindings, Mapping):
        for key in ("bindings", "workflows", "records"):
            rows = bindings.get(key)
            if isinstance(rows, list):
                result.extend(
                    {
                        **dict(row),
                        "catalog_kind": "execution-binding",
                        "execution_class": "validator_only"
                        if row.get("mode") == "executable_validator"
                        else "runtime_binding",
                    }
                    for row in rows
                    if isinstance(row, Mapping)
                )
                break
    return result


def _humanize_identifier(value: object) -> str:
    """Turn a stable machine identifier into a readable display label."""
    words = str(value or "").replace("_", "-").split("-")
    return " ".join(
        _DISPLAY_ACRONYMS.get(word.casefold(), word.capitalize())
        for word in words
        if word
    )


def _enterprise_catalog(root: Path) -> dict[str, Any]:
    payload = _read_json(root / "registry" / "ms_enterprise_catalog.json", {})
    return dict(payload) if isinstance(payload, Mapping) else {}


def _enterprise_rows(root: Path, field: str, catalog_kind: str) -> list[dict[str, Any]]:
    payload = _enterprise_catalog(root)
    rows = payload.get(field, [])
    if not isinstance(rows, list):
        return []
    return [
        {**dict(row), "catalog_kind": catalog_kind}
        for row in rows
        if isinstance(row, Mapping)
    ]


def _coordination(root: Path) -> dict[str, Any]:
    base = root / ".engineering-bootstrap" / "coordination"
    state = _read_json(base / "state.json", {})
    if not isinstance(state, Mapping) or not state:
        return {
            "instrumented": False,
            "root": base.as_posix(),
            "active_plan": None,
            "tasks": 0,
            "active_claims": 0,
            "state_hash": None,
        }
    claims = state.get("claims", []) if isinstance(state.get("claims"), list) else []
    return {
        "instrumented": True,
        "root": base.as_posix(),
        "active_plan": state.get("active_plan"),
        "tasks": len(state.get("tasks", []))
        if isinstance(state.get("tasks"), list)
        else 0,
        "active_claims": sum(
            1
            for item in claims
            if isinstance(item, Mapping) and item.get("status") == "active"
        ),
        "state_hash": state.get("state_hash"),
        "updated_utc": state.get("updated_utc"),
        "handoff": (base / "handoff.json").as_posix(),
        "events": (base / "events.jsonl").as_posix(),
    }


def _memory(root: Path, workspace_root: Path | None) -> dict[str, Any]:
    if workspace_root is None:
        return {
            "instrumented": False,
            "status": "detached",
            "authority": "canonical workspace memory vault",
            "record_count": None,
            "eligible_record_count": None,
            "bytes": None,
            "projects": [],
            "workspace_root": None,
            "error": "pacifyX.workspaceRoot is not configured",
        }
    try:
        from .workspace_manager import workspace_monitor

        report = workspace_monitor(workspace_root, source_root=root)
        if not isinstance(report, Mapping):
            return {
                "instrumented": False,
                "status": "invalid",
                "authority": "canonical workspace memory vault",
                "record_count": None,
                "eligible_record_count": None,
                "bytes": None,
                "projects": [],
                "workspace_root": workspace_root.resolve().as_posix(),
                "error": "workspace monitor returned an invalid report",
            }
        rows = (
            report.get("memory", []) if isinstance(report.get("memory"), list) else []
        )
        workspace = (
            report.get("workspace", {})
            if isinstance(report.get("workspace"), Mapping)
            else {}
        )
        memory_valid = bool(report.get("memory_valid"))
        workspace_valid = bool(workspace.get("valid"))
        configured = True
        project_registered = (
            len(rows) > 0 or int(workspace.get("registered_count") or 0) > 0
        )
        lease_active = int(workspace.get("active_session_count") or 0) > 0
        vault_open = project_registered and memory_valid
        retrieval_ready = workspace_valid and vault_open and lease_active
        layer_counts: Counter[str] = Counter()
        lifecycle_counts: Counter[str] = Counter()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            layer_counts.update(
                {
                    str(key): int(value)
                    for key, value in (row.get("layer_counts", {}) or {}).items()
                }
            )
            lifecycle_counts.update(
                {
                    str(key): int(value)
                    for key, value in (row.get("lifecycle_counts", {}) or {}).items()
                }
            )
        return {
            "instrumented": retrieval_ready,
            "configured": configured,
            "configuration_valid": workspace_valid,
            "project_registered": project_registered,
            "lease_active": lease_active,
            "lease": {
                "state": "current"
                if lease_active
                else "expired"
                if workspace.get("expired_session_ids")
                else "required",
                "active_session_count": int(
                    workspace.get("active_session_count") or 0
                ),
                "sessions": list(workspace.get("active_session_expiries") or []),
                "expired_session_ids": list(
                    workspace.get("expired_session_ids") or []
                ),
                "renewal_route": "project renew --session-id <session> --minutes <bounded>",
                "reacquire_route": "project activate <project> --session-id <session>",
            },
            "vault_open": vault_open,
            "retrieval_ready": retrieval_ready,
            "status": "healthy"
            if retrieval_ready
            else "empty"
            if workspace_valid and not project_registered
            else "lease-required"
            if vault_open
            else "degraded"
            if configured
            else "invalid",
            "authority": "canonical workspace memory vault",
            "workspace_root": workspace_root.resolve().as_posix(),
            "project_count": len(rows),
            "projects": rows,
            "record_count": sum(
                int(row.get("record_count") or 0)
                for row in rows
                if isinstance(row, Mapping)
            ),
            "eligible_record_count": sum(
                int(row.get("eligible_record_count") or 0)
                for row in rows
                if isinstance(row, Mapping)
            ),
            "bytes": sum(
                int(row.get("bytes") or 0) for row in rows if isinstance(row, Mapping)
            ),
            "layer_counts": dict(sorted(layer_counts.items())),
            "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
            "memory_errors": list(report.get("memory_errors", [])),
            "workspace_errors": list(workspace.get("errors", [])),
            "integration_status": "healthy"
            if report.get("integrations", {}).get("valid")
            else "degraded",
            "limitations": []
            if retrieval_ready
            else [
                "Canonical retrieval requires a registered project with a current active lease."
            ]
            if project_registered
            else [
                "The workspace is valid but contains no registered project or canonical vault."
            ],
        }
    except Exception as error:  # UI discovery must degrade with an explicit error.
        return {
            "instrumented": False,
            "status": "invalid",
            "authority": "canonical workspace memory vault",
            "record_count": None,
            "eligible_record_count": None,
            "bytes": None,
            "projects": [],
            "workspace_root": workspace_root.resolve().as_posix(),
            "error": f"{type(error).__name__}: {error}",
        }


def _knowledge_core(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    records = []
    invalid = []
    for source in sources:
        relative = str(source.get("location") or "")
        reason = None
        supplied = Path(relative) if relative else None
        target = None
        if supplied is None:
            reason = "declared_source_missing"
        elif supplied.is_absolute() or ".." in supplied.parts:
            reason = "declared_source_outside_project"
        else:
            candidate = root / supplied
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root.resolve(strict=True))
                target = resolved
            except (FileNotFoundError, OSError):
                reason = "declared_source_missing"
            except ValueError:
                reason = "declared_source_outside_project"
        available = target is not None
        identity = None
        identity_scope = None
        if target is not None and target.is_file():
            identity = hashlib.sha256(target.read_bytes()).hexdigest()
            identity_scope = "complete-file-bytes"
        elif target is not None and target.is_dir():
            members = [path for path in sorted(target.rglob("*")) if path.is_file()]
            if any(member.is_symlink() for member in members):
                reason = "declared_source_contains_symbolic_link"
                available = False
                target = None
            elif len(members) > 1000:
                reason = "declared_source_exceeds_1000_file_identity_bound"
                available = False
                target = None
            else:
                digest = hashlib.sha256()
                for member in members:
                    relative_member = member.relative_to(target).as_posix().encode("utf-8")
                    content = member.read_bytes()
                    digest.update(len(relative_member).to_bytes(8, "big"))
                    digest.update(relative_member)
                    digest.update(len(content).to_bytes(8, "big"))
                    digest.update(content)
                identity = digest.hexdigest()
                identity_scope = "complete-directory-relative-paths-and-file-bytes"
        row = {
            "id": str(source.get("id") or "unknown"),
            "kind": str(source.get("kind") or "unknown"),
            "lifecycle": str(source.get("status") or "unknown"),
            "location": relative,
            "visibility": list(source.get("visibility") or []),
            "uses": list(source.get("uses") or []),
            "available": available,
            "source_sha256": identity,
            "source_sha256_scope": identity_scope,
            "provenance": {
                "registry": "registry/knowledge_sources.json",
                "authority": "declared knowledge source",
            },
        }
        records.append(row)
        if not available:
            invalid.append({"id": row["id"], "reason": reason, "location": relative})
    proposal_heads = list(
        root.glob(
            ".engineering-bootstrap/studios/knowledge/proposals/*/head.json"
        )
    )
    canonical_heads = list(
        root.glob(
            ".engineering-bootstrap/studios/knowledge/canonical/*/head.json"
        )
    )
    return {
        "schema_version": "px.knowledge-core-browser/1.1",
        "records": records,
        "record_count": len(records),
        "invalid_records": invalid,
        "conflicts": [],
        "proposal_count": len(proposal_heads),
        "canonical_record_count": len(canonical_heads),
        "promotion_state": "governed-proposal-controller",
        "lifecycle": {
            state: sum(row["lifecycle"] == state for row in records)
            for state in sorted({row["lifecycle"] for row in records})
        },
        "actions": {
            "rebuild": {
                "available": True,
                "reason": None,
                "route": "studio knowledge propose",
                "prerequisites": [
                    "explicit host approval",
                    "declared project-local source",
                    "evidence references",
                ],
            },
            "promotion": {
                "available": True,
                "reason": None,
                "route": "studio knowledge verify -> approve -> promote",
                "prerequisites": [
                    "current eligible verification",
                    "authenticated single-use approval",
                    "optimistic canonical-head match",
                ],
            },
        },
    }


def _extension_source_identity(root: Path) -> dict[str, Any]:
    extension_root = root / "extension"
    package_path = extension_root / "package.json"
    package = _read_json(package_path, {})
    asset_paths = sorted((extension_root / "media" / "dashboard").glob("*.js"))
    asset_paths.extend(
        path
        for path in (
            extension_root / "media" / "dashboard.css",
            extension_root / "media" / "sidebar.css",
            extension_root / "media" / "sidebar.js",
        )
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in sorted(asset_paths, key=lambda item: item.relative_to(extension_root).as_posix()):
        relative = path.relative_to(extension_root).as_posix()
        data = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    sidebar = (extension_root / "media" / "sidebar.js").read_text(encoding="utf-8")
    messages = (extension_root / "src" / "sidebarMessages.js").read_text(
        encoding="utf-8"
    )
    asset_match = re.search(r"ASSET_PROTOCOL\s*=\s*['\"]([^'\"]+)", sidebar)
    schema_match = re.search(
        r"MESSAGE_SCHEMA_VERSION\s*=\s*['\"]([^'\"]+)", messages
    )
    return {
        "schema_version": "px.extension-source-identity/1.0",
        "version": str(package.get("version") or "unknown"),
        "package_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest()
        if package_path.is_file()
        else None,
        "asset_sha256": digest.hexdigest(),
        "asset_file_count": len(asset_paths),
        "asset_protocol": asset_match.group(1) if asset_match else None,
        "message_schema": schema_match.group(1) if schema_match else None,
    }


def _hardware(
    root: Path | None = None,
    *,
    now: float | None = None,
    cache_ttl_seconds: float = HARDWARE_CACHE_TTL_SECONDS,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return sensor telemetry through a short-lived derived cache.

    Dashboard snapshots are separate Python processes, so an in-memory cache
    would not prevent repeated ``nvidia-smi`` startup cost.  This cache is
    explicitly derived, bounded to one fixed project-owned path, and is never
    accepted as authority for execution routing or certification.
    """
    observed = time.time() if now is None else float(now)
    if not 0 <= cache_ttl_seconds <= HARDWARE_CACHE_MAX_TTL_SECONDS:
        raise ValueError(
            f"hardware cache TTL must be between 0 and {HARDWARE_CACHE_MAX_TTL_SECONDS:g} seconds"
        )
    cache_path = (
        root
        / ".engineering-bootstrap"
        / "diagnostics"
        / "hardware-dashboard-cache.json"
        if root is not None
        else None
    )
    cache_error: str | None = None
    if (
        not force_refresh
        and cache_path is not None
        and cache_ttl_seconds > 0
        and cache_path.is_file()
    ):
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_report = (
                cached.get("report") if isinstance(cached, Mapping) else None
            )
            report_sha256 = (
                hashlib.sha256(
                    json.dumps(
                        cached_report, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                ).hexdigest()
                if isinstance(cached_report, Mapping)
                else None
            )
            if (
                isinstance(cached, Mapping)
                and cached.get("schema_version") == HARDWARE_CACHE_SCHEMA
                and isinstance(cached.get("sampled_epoch"), (int, float))
                and isinstance(cached_report, Mapping)
                and cached.get("report_sha256") == report_sha256
            ):
                age = observed - float(cached["sampled_epoch"])
                if 0 <= age < cache_ttl_seconds:
                    sampled_at = datetime.fromtimestamp(
                        float(cached["sampled_epoch"]), timezone.utc
                    )
                    report = dict(cached_report)
                    report["cache"] = {
                        "status": "hit",
                        "age_seconds": round(age, 3),
                        "ttl_seconds": cache_ttl_seconds,
                        "fresh": True,
                        "sampled_at": sampled_at.isoformat(),
                        "fresh_until": (
                            sampled_at + timedelta(seconds=cache_ttl_seconds)
                        ).isoformat(),
                        "authority": "informational-derived-only",
                    }
                    return report
                if age < 0:
                    cache_error = "cache timestamp is in the future"
            elif isinstance(cached, Mapping):
                cache_error = "cache schema or integrity hash is invalid"
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            cache_error = f"{type(error).__name__}: {error}"
    try:
        from .hardware_routing import hardware_report

        report = dict(
            hardware_report(
                probe_external=False,
                probe_libraries=False,
                probe_sensors=True,
                timeout_seconds=2.0,
            )
        )
        report["cache"] = {
            "status": "miss",
            "age_seconds": 0.0,
            "ttl_seconds": cache_ttl_seconds,
            "fresh": True,
            "sampled_at": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
            "fresh_until": datetime.fromtimestamp(
                observed + cache_ttl_seconds, timezone.utc
            ).isoformat(),
            "authority": "informational-derived-only",
            "read_error": cache_error,
            "refresh_trigger": "forced" if force_refresh else "expired-or-absent",
        }
        if cache_path is not None and cache_ttl_seconds > 0:
            temporary = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.tmp")
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cached_report = {
                    key: value for key, value in report.items() if key != "cache"
                }
                payload = {
                    "schema_version": HARDWARE_CACHE_SCHEMA,
                    "sampled_epoch": observed,
                    "sampled_at": _now(),
                    "report": cached_report,
                    "report_sha256": hashlib.sha256(
                        json.dumps(
                            cached_report, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                    ).hexdigest(),
                }
                with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(payload, stream, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, cache_path)
            except OSError as error:
                report["cache"]["write_error"] = f"{type(error).__name__}: {error}"
                report["cache"]["retained_prepared_path"] = temporary.name
        return report
    except Exception as error:
        return {
            "valid": False,
            "error": str(error),
            "cache": {"status": "error", "authority": "informational-derived-only"},
        }


def _turbovec() -> dict[str, Any]:
    available = importlib.util.find_spec("turbovec") is not None
    return {
        "available": available,
        "active": False,
        "status": "available-unadmitted" if available else "candidate-not-installed",
        "authority": "optional derived retrieval accelerator",
        "fallback": "deterministic lexical + metadata + graph",
        "reason": "Activation requires compatibility, recall, isolation, benchmark, observability, and recovery evidence.",
    }


def _placement_runtime(root: Path, hardware: Mapping[str, Any]) -> dict[str, Any]:
    artifact_root = root / ".engineering-bootstrap" / "runtime-core" / "placement"
    paths = (
        sorted(
            artifact_root.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:50]
        if artifact_root.is_dir()
        else []
    )
    records = [row for path in paths if isinstance((row := _read_json(path, None)), Mapping)]
    tier_counts = Counter(int(row.get("promotion_tier", 0) or 0) for row in records)
    decisions = [
        row
        for row in records
        if str(row.get("schema_version", "")).startswith("px.execution-placement-decision/")
    ]
    current = decisions[0] if decisions else None
    hardware_profile = hardware.get("hardware", {})
    if not isinstance(hardware_profile, Mapping):
        hardware_profile = {}
    cuda_visible = hardware_profile.get("cuda_available") is True
    cuda_executor_ready = hardware_profile.get("cuda_executor_available") is True
    current_acceleration_route = "cuda-eligible" if cuda_executor_ready else "cpu"
    acceleration_reason = (
        "A compatible CUDA executor is available; each workload still requires current correctness and matched benchmark evidence."
        if cuda_executor_ready
        else str(
            hardware_profile.get("gpu_parallelism_reason")
            or "No admitted compatible CUDA executor is currently available."
        )
    )
    return {
        "schema_version": "px.execution-placement-runtime/1.0",
        "artifact_root": artifact_root.as_posix(),
        "artifact_count": len(records),
        "promotion_tiers": {str(key): value for key, value in sorted(tier_counts.items())},
        "current_decision": current,
        "recent": records[:10],
        "cpu_authority": [
            "filesystem_io",
            "database",
            "serialization",
            "cleanup_safety",
            "destructive_decision",
        ],
        "gpu_policy": {
            "optional": True,
            "device_visible": cuda_visible,
            "executor_ready": cuda_executor_ready,
            "current_route": current_acceleration_route,
            "reason": acceleration_reason,
            "requires_current_correctness_benchmark": True,
            "fallback": "cpu",
            "scorer_authorizes_migration": False,
        },
        "available": bool(records),
        "limitations": []
        if records
        else ["No observed placement lifecycle artifact has been published yet."],
    }


def _provider_activity(root: Path) -> list[dict[str, Any]]:
    """Project current provider budgets into secret-free live sidebar telemetry."""
    policy = _read_json(root / "registry" / "provider_budget_policy.json", {})
    adapters = _read_json(root / "registry" / "provider_adapters.json", {})
    policy_rows = policy.get("budgets", []) if isinstance(policy, Mapping) else []
    adapter_rows = adapters.get("adapters", []) if isinstance(adapters, Mapping) else []
    adapter_by_provider = {
        str(row.get("provider_id")): row
        for row in adapter_rows
        if isinstance(row, Mapping) and row.get("provider_id")
    }
    budget_root = root / ".engineering-bootstrap" / "provider-budget"
    ledger_path = budget_root / "ledger.json"
    try:
        from .provider_budget import ProviderBudgetLedger

        state = ProviderBudgetLedger(
            root, budget_root, root / ".engineering-bootstrap"
        ).snapshot()
        ledger_error = None
    except Exception as error:
        state = {"budgets": {}, "invocations": {}}
        ledger_error = f"{type(error).__name__}: {error}"
    budgets = state.get("budgets", {}) if isinstance(state, Mapping) else {}
    invocations = state.get("invocations", {}) if isinstance(state, Mapping) else {}
    if not isinstance(budgets, Mapping):
        budgets = {}
    if not isinstance(invocations, Mapping):
        invocations = {}
    fresh_at = (
        datetime.fromtimestamp(ledger_path.stat().st_mtime, timezone.utc).isoformat()
        if ledger_path.is_file()
        else None
    )
    result: list[dict[str, Any]] = []
    for raw in policy_rows:
        if not isinstance(raw, Mapping) or raw.get("enabled") is not True:
            continue
        row = dict(raw)
        provider_id = str(row.get("provider_id") or "unknown")
        budget_id = str(row.get("budget_id") or "unknown")
        actor_id = str(row.get("actor_id") or "unknown")
        key = f"{budget_id}\u241f{actor_id}\u241f{provider_id}"
        counters = budgets.get(key, {})
        counters = counters if isinstance(counters, Mapping) else {}
        matching = [
            item
            for item in invocations.values()
            if isinstance(item, Mapping)
            and item.get("budget_id") == budget_id
            and item.get("actor_id") == actor_id
            and item.get("provider_id") == provider_id
        ]
        active = [item for item in matching if item.get("state") == "reserved"]
        current = active[-1] if active else matching[-1] if matching else {}
        adapter = adapter_by_provider.get(provider_id, {})
        local = (
            adapter.get("mode") == "local"
            or adapter.get("billing_state") == "local_non_billable"
        )
        spent = int(counters.get("settled_charge_microunits", 0) or 0)
        reserved = int(counters.get("reserved_charge_microunits", 0) or 0)
        hard_limit = int(row.get("hard_limit_microunits", 0) or 0)
        tokens = sum(
            int(counters.get(field, 0) or 0)
            for field in (
                "settled_input_tokens",
                "reserved_input_tokens",
                "settled_output_tokens",
                "reserved_output_tokens",
            )
        )
        budget_percent = (
            round(((spent + reserved) / hard_limit) * 100, 1)
            if hard_limit > 0
            else None
        )
        result.append(
            {
                "providerId": f"{provider_id}:{budget_id}:{actor_id}",
                "providerName": provider_id,
                "providerClass": "local" if local else "billable-api",
                "connectionState": (
                    "connected"
                    if adapter.get("admitted") is True
                    and adapter.get("status") == "ready"
                    else "blocked"
                ),
                "activityState": "active" if active else "idle",
                "billingEnabled": False
                if local
                else (None if current.get("billing_state") == "unknown" else True),
                "fallbackEnabled": bool(row.get("fallback_adapter_ids")),
                "fallbackActive": any(item.get("fallback_from") for item in active),
                "currentTaskId": None,
                "currentTaskName": None,
                "currentAgentName": actor_id,
                "spendCurrent": spent / 1_000_000,
                "budgetLimit": hard_limit / 1_000_000,
                "budgetRemaining": max(0, hard_limit - spent - reserved) / 1_000_000,
                "budgetPercent": budget_percent,
                "tokenTotal": tokens,
                "tokenBudget": int(row.get("max_input_tokens", 0) or 0)
                + int(row.get("max_output_tokens", 0) or 0),
                "requestCount": int(counters.get("request_count", 0) or 0),
                "ratePerMinute": None,
                "currency": row.get("currency"),
                "telemetrySource": "provider-budget-ledger"
                if ledger_error is None
                else f"provider-budget-ledger-unavailable:{ledger_error}",
                "telemetryFreshAt": fresh_at,
            }
        )
    return result


def _project_service_route_map(
    manifest: Mapping[str, Any], topology: object, *, service_limit: int = 16,
    route_limit: int = 64,
) -> dict[str, Any]:
    """Return bounded static service/route evidence without inferred joins."""

    source = topology if isinstance(topology, Mapping) else {}
    raw_services = source.get("services", [])
    raw_routes = source.get("routes", [])
    service_values = raw_services if isinstance(raw_services, list) else []
    route_values = raw_routes if isinstance(raw_routes, list) else []
    dropped_invalid = 0

    def text(value: object) -> str | None:
        if value is None:
            return None
        candidate = str(value).strip()
        return candidate[:512] if candidate else None

    services: list[dict[str, Any]] = []
    for source_index, value in enumerate(service_values):
        if not isinstance(value, Mapping):
            dropped_invalid += 1
            continue
        route_ids = value.get("route_ids", [])
        services.append(
            {
                "source_index": source_index,
                "service_id": text(value.get("id") or value.get("service_id")),
                "name": text(value.get("name")),
                "kind": text(value.get("kind")) or "declared-service",
                "source": text(value.get("source")),
                "image": text(value.get("image")),
                "explicit_route_ids": [
                    item for item in (text(item) for item in route_ids[:64]) if item
                ]
                if isinstance(route_ids, list)
                else [],
            }
        )

    routes: list[dict[str, Any]] = []
    for source_index, value in enumerate(route_values):
        if not isinstance(value, Mapping):
            dropped_invalid += 1
            continue
        methods = value.get("methods", [])
        routes.append(
            {
                "source_index": source_index,
                "route_id": text(value.get("id") or value.get("route_id")),
                "service_id": text(value.get("service_id")),
                "methods": [
                    item for item in (text(item) for item in methods[:8]) if item
                ]
                if isinstance(methods, list)
                else [],
                "path": text(value.get("path")),
                "protocol": text(value.get("protocol")) or "http",
                "handler": text(value.get("handler")),
                "source": text(value.get("file") or value.get("source")),
                "link_state": "unlinked",
            }
        )

    service_by_id = {
        item["service_id"]: item for item in services if item.get("service_id")
    }
    route_by_id = {item["route_id"]: item for item in routes if item.get("route_id")}
    links: set[tuple[str, str]] = set()
    conflicts = 0
    for route in routes:
        service_id = route.get("service_id")
        route_id = route.get("route_id")
        if service_id in service_by_id and route_id:
            links.add((str(service_id), str(route_id)))
    for service in services:
        service_id = service.get("service_id")
        if not service_id:
            continue
        for route_id in service["explicit_route_ids"]:
            route = route_by_id.get(route_id)
            if route is None:
                continue
            if route.get("service_id") not in {None, service_id}:
                conflicts += 1
                continue
            route["service_id"] = service_id
            links.add((str(service_id), str(route_id)))
    for route in routes:
        if (str(route.get("service_id")), str(route.get("route_id"))) in links:
            route["link_state"] = "explicit"

    valid_service_count = len(services)
    valid_route_count = len(routes)
    services = services[:service_limit]
    routes = routes[:route_limit]
    visible_route_ids = {item.get("route_id") for item in routes}
    visible_service_ids = {item.get("service_id") for item in services}
    visible_links = [
        {"service_id": service_id, "route_id": route_id, "basis": "explicit-id"}
        for service_id, route_id in sorted(links)
        if service_id in visible_service_ids and route_id in visible_route_ids
    ]
    limitations = [
        str(value)[:512]
        for value in source.get("limitations", [])[:8]
        if str(value).strip()
    ] if isinstance(source.get("limitations"), list) else []
    if "routes" not in source:
        limitations.append("route-records-not-emitted-by-project-map; rebuild required")
    if conflicts:
        limitations.append(f"{conflicts} conflicting explicit service-route link(s) rejected")
    limitations.append(
        "Static declaration/discovery evidence only; not proof that a service is listening or a route is reachable."
    )
    return {
        "schema_version": "px.project-service-route-map/1.0",
        "evidence_basis": "static-project-map-artifacts",
        "runtime_observed": False,
        "map_revision": manifest.get("map_revision"),
        "source_artifacts": ["runtime-topology.json"],
        "services": services,
        "routes": routes,
        "links": visible_links,
        "coverage": {
            "source_service_count": len(service_values),
            "returned_service_count": len(services),
            "source_route_count": len(route_values),
            "returned_route_count": len(routes),
            "linked_route_count": sum(
                1 for item in routes if item.get("link_state") == "explicit"
            ),
            "unlinked_route_count": sum(
                1 for item in routes if item.get("link_state") != "explicit"
            ),
            "dropped_invalid_count": dropped_invalid,
            "truncated": valid_service_count > service_limit
            or valid_route_count > route_limit,
        },
        "limitations": limitations,
    }


def _project_test_link_map(
    payload: object, *, link_limit: int = 32, gap_limit: int = 16,
) -> dict[str, Any]:
    """Return bounded static test traceability rows and honest denominators."""

    source = payload if isinstance(payload, Mapping) else {}
    raw_links = source.get("links", [])
    raw_untested = source.get("untested_source_candidates", [])
    raw_unmapped = source.get("unmapped_test_files", [])
    link_values = raw_links if isinstance(raw_links, list) else []
    untested_values = raw_untested if isinstance(raw_untested, list) else []
    unmapped_values = raw_unmapped if isinstance(raw_unmapped, list) else []
    dropped_invalid = {"links": 0, "untested_sources": 0, "unmapped_tests": 0}

    def text(value: object) -> str | None:
        if value is None:
            return None
        candidate = str(value).strip()
        return candidate[:1024] if candidate else None

    links: list[dict[str, Any]] = []
    for source_index, value in enumerate(link_values):
        if not isinstance(value, Mapping):
            dropped_invalid["links"] += 1
            continue
        test = text(value.get("test"))
        linked_source = text(value.get("source"))
        basis = text(value.get("basis"))
        if not test or not linked_source or not basis:
            dropped_invalid["links"] += 1
            continue
        links.append(
            {
                "source_index": source_index,
                "test": test,
                "source": linked_source,
                "basis": basis,
            }
        )

    def gap_rows(
        values: list[object], field: str, category: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for source_index, value in enumerate(values):
            candidate = text(value)
            if not candidate:
                dropped_invalid[category] += 1
                continue
            result.append({"source_index": source_index, field: candidate})
        return result

    untested_sources = gap_rows(
        untested_values, "source", "untested_sources"
    )
    unmapped_tests = gap_rows(unmapped_values, "test", "unmapped_tests")
    valid_link_count = len(links)
    valid_untested_count = len(untested_sources)
    valid_unmapped_count = len(unmapped_tests)
    links = links[:link_limit]
    untested_sources = untested_sources[:gap_limit]
    unmapped_tests = unmapped_tests[:gap_limit]
    basis_counts = Counter(str(item["basis"]) for item in links)
    limitations = [
        "Static traceability candidates only; not proof that a test executed, passed, or covers behavior."
    ]
    if any(str(item.get("basis")) == "name_proximity" for item in links):
        limitations.append(
            "This sealed revision contains legacy substring-proximity links; rebuild with the current parser before treating them as exact basename evidence."
        )
    return {
        "schema_version": "px.project-test-link-map/1.0",
        "coverage_kind": source.get("coverage_kind"),
        "execution_observed": False,
        "links": links,
        "untested_sources": untested_sources,
        "unmapped_tests": unmapped_tests,
        "coverage": {
            "source_file_count": len(source.get("source_files", []))
            if isinstance(source.get("source_files"), list)
            else 0,
            "test_file_count": len(source.get("test_files", []))
            if isinstance(source.get("test_files"), list)
            else 0,
            "source_link_count": len(link_values),
            "returned_link_count": len(links),
            "source_untested_count": len(untested_values),
            "returned_untested_count": len(untested_sources),
            "source_unmapped_count": len(unmapped_values),
            "returned_unmapped_count": len(unmapped_tests),
            "returned_basis_counts": dict(sorted(basis_counts.items())),
            "dropped_invalid_link_count": dropped_invalid["links"],
            "dropped_invalid_untested_count": dropped_invalid["untested_sources"],
            "dropped_invalid_unmapped_count": dropped_invalid["unmapped_tests"],
            "dropped_invalid_count": sum(dropped_invalid.values()),
            "truncated": valid_link_count > link_limit
            or valid_untested_count > gap_limit
            or valid_unmapped_count > gap_limit,
        },
        "limitations": limitations,
    }


def _project_map_drilldown(project: Path) -> dict[str, Any]:
    def rows(payload: object, key: str, limit: int) -> list[object]:
        value = payload.get(key, []) if isinstance(payload, Mapping) else []
        return list(value[:limit]) if isinstance(value, list) else []

    def row_count(payload: object, key: str) -> int:
        value = payload.get(key, []) if isinstance(payload, Mapping) else []
        return len(value) if isinstance(value, list) else 0

    map_dir = project / ".engineering-bootstrap" / "project-map"
    manifest = _read_json(map_dir / "project-manifest.json", {})
    receipt = _read_json(map_dir / "map-receipt.json", {})
    risks = _read_json(map_dir / "risk-and-gap-map.json", {})
    topology = _read_json(map_dir / "runtime-topology.json", {})
    integrations = _read_json(map_dir / "integration-map.json", {})
    tests = _read_json(map_dir / "test-coverage-map.json", {})
    service_route = _project_service_route_map(manifest, topology)
    test_links = _project_test_link_map(tests)
    history_root = project / ".engineering-bootstrap" / "project-map-history"
    history = []
    if history_root.is_dir():
        for archived in sorted(
            (item for item in history_root.iterdir() if item.is_dir()),
            key=lambda item: item.name,
            reverse=True,
        )[:6]:
            archived_manifest = _read_json(archived / "project-manifest.json", {})
            history.append(
                {
                    "archive_id": archived.name,
                    "map_revision": archived_manifest.get("map_revision"),
                    "source_inventory_sha256": archived_manifest.get(
                        "source_inventory_sha256"
                    ),
                    "counts": archived_manifest.get("counts", {}),
                }
            )
    return {
        "schema_version": "px.project-map-dashboard-drilldown/1.0",
        "built_utc": receipt.get("promoted_utc") or receipt.get("created_utc"),
        "run_id": receipt.get("run_id"),
        "promotion": receipt.get("promotion"),
        "incremental": manifest.get("incremental"),
        "build_stats": manifest.get("build_stats", {}),
        "entrypoints": rows(topology, "entrypoints", 16),
        "service_route_map": service_route,
        "services": service_route["services"],
        "routes": service_route["routes"],
        "runtime_limitations": service_route["limitations"],
        "packages": rows(integrations, "packages", 16),
        "risks": rows(risks, "findings", 12),
        "unknowns": rows(risks, "unknowns", 8),
        "test_link_map": test_links,
        "test_links": test_links["links"],
        "untested_sources": test_links["untested_sources"],
        "unmapped_tests": test_links["unmapped_tests"],
        "test_coverage": {
            "kind": tests.get("coverage_kind"),
            "source_files": row_count(tests, "source_files"),
            "test_files": row_count(tests, "test_files"),
            "links": row_count(tests, "links"),
            "unmapped_test_files": row_count(tests, "unmapped_test_files"),
            "untested_source_candidates": row_count(
                tests, "untested_source_candidates"
            ),
        }
        if isinstance(tests, Mapping)
        else {},
        "history": history,
    }


def _project(root: Path, project: Path) -> dict[str, Any]:
    try:
        from .project_intelligence import project_map_status

        map_state = project_map_status(project, verify_integrity=False)
        if map_state.get("available"):
            map_state["drilldown"] = _project_map_drilldown(project)
    except Exception as error:
        map_state = {"valid": False, "available": False, "error": str(error)}
    return {
        "id": project.name,
        "name": project.name,
        "path": project.as_posix(),
        "branch": _git(project, "branch", "--show-current") or "unknown",
        "commit": _git(project, "rev-parse", "--short", "HEAD"),
        "map": map_state,
    }


def _bounded_operational_progress(progress: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in progress.items():
        if isinstance(value, list):
            result[key] = value[:25]
            result[f"{key}_count"] = len(value)
            result[f"{key}_truncated"] = len(value) > 25
        else:
            result[key] = value
    return result


def _operational_punch_cards(
    root: Path,
    *,
    query: str = "",
    state: str = "",
    severity: str = "",
    surface: str = "",
    owner: str = "",
    evidence_gap: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Project the append-only operational ledger as bounded dashboard data."""
    from .operational_gap_ledger import LEDGER_RELATIVE, read_head, read_snapshot

    source = root / LEDGER_RELATIVE
    bounded_offset = max(0, int(offset))
    bounded_limit = max(1, min(100, int(limit)))
    compact_request = not any((query.strip(), state, severity, surface, owner, evidence_gap))
    try:
        if compact_request:
            head = read_head(root)
            compact = head.get("dashboard", {})
            cached_rows = compact.get("cards", []) if isinstance(compact, Mapping) else []
            if bounded_offset + bounded_limit <= len(cached_rows) or not compact.get("truncated"):
                rows = list(cached_rows[bounded_offset : bounded_offset + bounded_limit])
                count = int(compact.get("count") or 0)
                open_count = int(compact.get("open_count") or 0)
                return {
                    "schema_version": "px.operational-punch-card-projection/2.0",
                    "source": source.relative_to(root).as_posix(),
                    "source_created_utc": head.get("created_utc"),
                    "source_status": "open" if open_count else "closed",
                    "integrity_basis": head.get("verification_basis"),
                    "checkpoint_sha256": head.get("checkpoint_sha256"),
                    "count": count,
                    "open_count": open_count,
                    "status_counts": dict(compact.get("status_counts", {})),
                    "progress": dict(compact.get("progress", {})),
                    "head_event_sha256": head.get("head_event_sha256"),
                    "event_count": head.get("event_count"),
                    "cards": rows,
                    "query": {"text": "", "state": "", "severity": "", "surface": "", "owner": "", "evidence_gap": False},
                    "offset": bounded_offset,
                    "limit": bounded_limit,
                    "filtered_count": count,
                    "has_more": bounded_offset + len(rows) < count,
                    "truncated": count > len(rows),
                }
        payload = read_snapshot(root)
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        lowered = detail.casefold()
        source_status = (
            "checkpoint_stale"
            if any(token in lowered for token in ("stale", "changed during read", "does not match", "fingerprint"))
            else "recovery_required"
        )
        return {
            "schema_version": "px.operational-punch-card-projection/2.0",
            "source": LEDGER_RELATIVE.as_posix(),
            "source_status": source_status,
            "recovery_action": "python -m scripts.operational_gap_ledger --root . project",
            "count": 0,
            "open_count": 0,
            "status_counts": {},
            "progress": {},
            "cards": [],
            "error": detail,
        }
    findings = list(payload.get("cards", {}).values()) if isinstance(payload, Mapping) else []
    all_findings = [item for item in findings if isinstance(item, Mapping)]
    status_counts = Counter(str(item.get("current_state") or "discovered") for item in all_findings)
    open_count = sum(1 for item in all_findings if item.get("current_state") != "closed")
    needle = query.strip().casefold()[:500]
    filtered = all_findings
    if needle:
        filtered = [item for item in filtered if needle in " ".join(str(item.get(key) or "") for key in ("gap_id", "parent_surface", "feature", "control_action", "observed_behavior", "expected_behavior", "next_action")).casefold()]
    if state:
        filtered = [item for item in filtered if str(item.get("current_state") or "") == state]
    if severity:
        filtered = [item for item in filtered if str(item.get("severity") or "") == severity]
    if surface:
        filtered = [item for item in filtered if surface in {str(item.get("parent_surface") or ""), str(item.get("canonical_surface") or "")}]
    if owner:
        filtered = [item for item in filtered if str(item.get("assigned_owner") or "") == owner]
    evidence_lacking = set(payload.get("progress", {}).get("cards_lacking_required_evidence", []))
    if evidence_gap:
        filtered = [item for item in filtered if str(item.get("gap_id") or "") in evidence_lacking]
    priority = {"blocker": 0, "critical": 1, "high": 2, "medium": 3, "low": 4}
    filtered.sort(key=lambda item: (item.get("current_state") == "closed", priority.get(str(item.get("severity") or "low"), 9), str(item.get("gap_id") or "")))
    page = filtered[bounded_offset : bounded_offset + bounded_limit]
    rows = []
    for item in page:
        rows.append(
            {
                "id": str(item.get("gap_id") or "unknown"),
                "severity": str(item.get("severity") or "UNKNOWN").lower(),
                "area": str(item.get("parent_surface") or "unclassified"),
                "feature": str(item.get("feature") or "unclassified"),
                "control_action": str(item.get("control_action") or "unknown"),
                "status": str(item.get("current_state") or "discovered"),
                "finding": str(item.get("observed_behavior") or "No observation retained."),
                "acceptance": str(item.get("expected_behavior") or "No expected behavior retained."),
                "next_action": item.get("next_action"),
                "assigned_owner": item.get("assigned_owner"),
                "canonical_surface": item.get("canonical_surface"),
                "linked_control_count": len(item.get("linked_controls", [])),
                "evidence_lacking": str(item.get("gap_id") or "") in evidence_lacking,
            }
        )
    return {
        "schema_version": "px.operational-punch-card-projection/2.0",
        "source": source.relative_to(root).as_posix(),
        "source_created_utc": payload.get("created_utc"),
        "source_status": "open" if open_count else "closed",
        "integrity_basis": "checkpoint_bound_projection",
        "count": len(all_findings),
        "open_count": open_count,
        "status_counts": dict(sorted(status_counts.items())),
        "progress": _bounded_operational_progress(payload.get("progress", {})),
        "head_event_sha256": payload.get("head_event_sha256"),
        "event_count": payload.get("event_count"),
        "cards": rows,
        "query": {"text": query, "state": state, "severity": severity, "surface": surface, "owner": owner, "evidence_gap": evidence_gap},
        "offset": bounded_offset,
        "limit": bounded_limit,
        "filtered_count": len(filtered),
        "has_more": bounded_offset + len(rows) < len(filtered),
        "truncated": len(filtered) > len(rows),
    }


def query_operational_punch_card(root: Path, gap_id: str) -> dict[str, Any]:
    from .operational_gap_ledger import read_snapshot

    identifier = str(gap_id or "").strip()
    payload = read_snapshot(root)
    card = payload.get("cards", {}).get(identifier)
    if not isinstance(card, Mapping):
        raise ValueError(f"operational punch card not found: {identifier}")
    return {
        "schema_version": "px.operational-punch-card-detail/1.0",
        "head_event_sha256": payload.get("head_event_sha256"),
        "event_count": payload.get("event_count"),
        "card": dict(card),
    }


def query_operational_inventory(root: Path, *, surface_id: str = "") -> dict[str, Any]:
    from .operational_gap_ledger import read_snapshot

    payload = read_snapshot(root)
    surfaces = payload.get("surfaces", {})
    if surface_id:
        surface = surfaces.get(surface_id)
        if not isinstance(surface, Mapping):
            raise ValueError(f"operational surface not found: {surface_id}")
        items = [{"surface_id": surface_id, **dict(surface)}]
    else:
        items = [
            {
                "surface_id": key,
                "name": item.get("name"),
                "examined": item.get("examined", False),
                "known_control_count": len(item.get("known_controls", [])),
                "disposed_control_count": len(item.get("control_dispositions", {})),
                "inventory_evidence": item.get("inventory_evidence", []),
            }
            for key, item in sorted(surfaces.items())
        ]
    return {
        "schema_version": "px.operational-surface-query/1.0",
        "head_event_sha256": payload.get("head_event_sha256"),
        "progress": _bounded_operational_progress(payload.get("progress", {})),
        "surfaces": items,
    }


def _readiness_dimension(
    identifier: str,
    name: str,
    question: str,
    signals: list[tuple[bool, str, str]],
    *,
    blocking: bool = False,
) -> dict[str, Any]:
    passed = [evidence for ok, evidence, _gap in signals if ok]
    gaps = [gap for ok, _evidence, gap in signals if not ok]
    # Structural evidence alone is deliberately capped at 4. A score of 5 is
    # reserved for a fresh, separately retained end-to-end certification.
    score = min(4, max(1, len(passed)))
    return {
        "id": identifier,
        "name": name,
        "question": question,
        "score": score,
        "maximum": 5,
        "status": "ready" if score >= 4 else "partial" if score >= 2 else "gap",
        "blocking": blocking,
        "evidence": passed,
        "gaps": gaps,
    }


def build_readiness(
    root: Path,
    *,
    project_state: Mapping[str, Any],
    counts: Mapping[str, int],
    coordination: Mapping[str, Any],
    memory: Mapping[str, Any],
    hardware: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a conservative, deterministic agent-readiness matrix.

    This is a structural assessment, not a substitute for the live validation,
    full test, packaging, install, and UI gates used for release certification.
    """
    ownership = _read_json(root / "registry/python_surface_ownership.json", {})
    ownership = ownership if isinstance(ownership, Mapping) else {}
    dependency_ownership = root / "registry/python_dependency_ownership.json"
    reachability = _read_json(root / "registry/artifact_reachability.json", {})
    reachability = reachability if isinstance(reachability, Mapping) else {}
    map_counts = (
        project_state.get("map", {}).get("counts", {})
        if isinstance(project_state.get("map"), Mapping)
        else {}
    )
    telemetry = (
        hardware.get("telemetry", {})
        if isinstance(hardware.get("telemetry"), Mapping)
        else {}
    )
    hardware_cache = (
        hardware.get("cache", {}) if isinstance(hardware.get("cache"), Mapping) else {}
    )
    hardware_telemetry_fresh = bool(hardware_cache.get("fresh"))
    ci = root / ".github/workflows/ci.yml"
    effects = int(counts.get("effects", 0))
    contracts = int(counts.get("contracts", 0))
    tests = int(counts.get("tests", 0))
    dimensions = [
        _readiness_dimension(
            "D1",
            "Verification feedback",
            "Can an agent prove that a bounded change worked?",
            [
                (
                    tests > 0,
                    f"{tests} test modules are indexed",
                    "No test modules were indexed",
                ),
                (
                    ci.is_file(),
                    ".github/workflows/ci.yml is present",
                    "CI workflow is absent",
                ),
                (
                    (root / "policies/coverage-assurance.json").is_file(),
                    "coverage-assurance policy is declared",
                    "Coverage assurance policy is absent",
                ),
                (
                    int(ownership.get("direct_behavior_count", 0)) > 0,
                    f"{int(ownership.get('direct_behavior_count', 0))} direct behavior surfaces are mapped",
                    "No direct behavior ownership is mapped",
                ),
            ],
            blocking=True,
        ),
        _readiness_dimension(
            "D2",
            "Contracts and predictability",
            "Can an agent predict the contracts affected by a change?",
            [
                (
                    bool(ownership.get("valid")),
                    "Python surface ownership registry is valid",
                    "Python surface ownership is invalid",
                ),
                (
                    int(ownership.get("syntax_valid_count", -1))
                    == int(ownership.get("python_file_count", 0))
                    and int(ownership.get("python_file_count", 0)) > 0,
                    f"{int(ownership.get('syntax_valid_count', 0))}/{int(ownership.get('python_file_count', 0))} Python files are syntax-valid",
                    "Python syntax inventory is incomplete",
                ),
                (
                    contracts > 0,
                    f"{contracts} JSON contracts are indexed",
                    "No contracts are indexed",
                ),
                (
                    dependency_ownership.is_file(),
                    "Python dependency ownership is mapped",
                    "Dependency ownership map is absent",
                ),
            ],
            blocking=True,
        ),
        _readiness_dimension(
            "D3",
            "Context legibility",
            "Can an agent acquire a bounded, current view of the project?",
            [
                (
                    bool(project_state.get("map", {}).get("valid"))
                    if isinstance(project_state.get("map"), Mapping)
                    else False,
                    "Project-map receipt and projection metadata are coherent; full byte validation is a separate release gate",
                    "Project intelligence map is unavailable or its sealed projection metadata is invalid",
                ),
                (
                    int(map_counts.get("files", 0)) > 0,
                    f"{int(map_counts.get('files', 0))} files are mapped",
                    "No files are mapped",
                ),
                (
                    int(map_counts.get("symbols", 0)) > 0,
                    f"{int(map_counts.get('symbols', 0))} symbols are indexed",
                    "No symbols are indexed",
                ),
                (
                    int(map_counts.get("retrieval_documents", 0)) > 0,
                    f"{int(map_counts.get('retrieval_documents', 0))} bounded retrieval documents are indexed",
                    "No retrieval documents are indexed",
                ),
            ],
        ),
        _readiness_dimension(
            "D4",
            "Boundary clarity",
            "Are actions, ownership, and relationships explicitly bounded?",
            [
                (
                    effects > 0,
                    f"{effects} executable effect surfaces have owners",
                    "No effect surfaces are owned",
                ),
                (
                    int(reachability.get("record_count", 0)) > 0,
                    f"{int(reachability.get('record_count', 0))} artifacts are in the reachability inventory",
                    "Artifact reachability is absent",
                ),
                (
                    int(map_counts.get("architecture_edges", 0)) > 0,
                    f"{int(map_counts.get('architecture_edges', 0))} architecture edges are mapped",
                    "Architecture relationships are absent",
                ),
                (
                    (root / "policies/permission-boundary.json").is_file(),
                    "Permission boundary policy is declared",
                    "Permission boundary policy is absent",
                ),
            ],
        ),
        _readiness_dimension(
            "D5",
            "Action directness",
            "Can an agent see what a tool or workflow will actually do?",
            [
                (
                    int(counts.get("tools", 0)) > 0,
                    f"{int(counts.get('tools', 0))} governed tools are cataloged",
                    "No governed tools are cataloged",
                ),
                (
                    int(counts.get("execution_bindings", 0)) > 0,
                    f"{int(counts.get('execution_bindings', 0))} execution bindings are explicit",
                    "No execution bindings are explicit",
                ),
                (
                    effects > 0,
                    "Executable effects are separately classified",
                    "Executable effects are not classified",
                ),
                (
                    (root / "registry/contract_ownership.json").is_file(),
                    "Contract ownership registry is present",
                    "Contract ownership registry is absent",
                ),
            ],
            blocking=True,
        ),
        _readiness_dimension(
            "D6",
            "Documented intent",
            "Can an agent distinguish policy and design intent from incidental code?",
            [
                (
                    (root / "AGENTS.md").is_file(),
                    "Repository AGENTS.md is present",
                    "Repository agent guidance is absent",
                ),
                (
                    (root / "docs").is_dir(),
                    "Project documentation tree is present",
                    "Project documentation tree is absent",
                ),
                (
                    contracts > 0,
                    "Machine-readable contracts accompany implementation",
                    "Machine-readable contracts are absent",
                ),
                (
                    (root / "registry/corrective_release_ledger.json").is_file(),
                    "Corrective release decisions are retained",
                    "Corrective release ledger is absent",
                ),
            ],
        ),
        _readiness_dimension(
            "D7",
            "Observability",
            "Can an agent perceive runtime and coordination state without guessing?",
            [
                (
                    hardware_telemetry_fresh
                    and int(telemetry.get("available_count", 0)) > 0,
                    f"{int(telemetry.get('available_count', 0))} fresh hardware sensor metrics are readable",
                    "No fresh hardware metric is readable on this host",
                ),
                (
                    bool(coordination.get("instrumented")),
                    "Project coordination ledger is instrumented",
                    "Project coordination ledger is not initialized",
                ),
                (
                    bool(memory.get("instrumented")),
                    "Canonical memory telemetry is instrumented",
                    "Canonical memory telemetry is unavailable",
                ),
                (
                    int(counts.get("assurance", 0)) > 0,
                    f"{int(counts.get('assurance', 0))} assurance capabilities are cataloged",
                    "No assurance capabilities are cataloged",
                ),
            ],
        ),
        _readiness_dimension(
            "D8",
            "Iteration and delivery",
            "Can an agent use reproducible local build and delivery gates?",
            [
                (
                    (root / "pyproject.toml").is_file(),
                    "Python build metadata is present",
                    "Python build metadata is absent",
                ),
                (ci.is_file(), "CI workflow is present", "CI workflow is absent"),
                (
                    (root / "runtime/cli.py").is_file(),
                    "Canonical validation CLI is present",
                    "Canonical validation CLI is absent",
                ),
                (
                    (root / "runtime/release_distribution.py").is_file(),
                    "Release distribution controls are present",
                    "Release distribution controls are absent",
                ),
            ],
        ),
        _readiness_dimension(
            "D9",
            "Supply-chain currency",
            "Are dependencies and external capabilities governed as versioned inputs?",
            [
                (
                    (root / "requirements-release.lock").is_file(),
                    "Release dependency lock is retained",
                    "Release dependency lock is absent",
                ),
                (
                    (root / "policies/external-tool-quarantine.json").is_file(),
                    "External-tool quarantine policy is declared",
                    "External-tool quarantine policy is absent",
                ),
                (
                    (root / "registry/external_capability_catalog.json").is_file(),
                    "External capability candidates are cataloged",
                    "External capability catalog is absent",
                ),
                (
                    (root / "runtime/dependency_audit.py").is_file(),
                    "Dependency audit implementation is present",
                    "Dependency audit implementation is absent",
                ),
            ],
        ),
    ]
    blocking_scores = [item["score"] for item in dimensions if item["blocking"]]
    ceiling = min(blocking_scores) if blocking_scores else 1
    level = max(0, min(3, ceiling - 1))
    labels = {
        0: "Assisted only",
        1: "Review-bound",
        2: "Collaborative",
        3: "Autonomous bounded candidate",
    }
    gaps = [
        f"{item['id']} {item['name']}: {gap}"
        for item in dimensions
        for gap in item["gaps"]
    ]
    return {
        "schema_version": "1.0",
        "generated_at": _now(),
        "assessment": "structural-agent-readiness",
        "authority": "advisory; release certification remains separate",
        "score_cap_reason": "Structural evidence is capped at 4/5 until a fresh full E2E certification is retained.",
        "maturity": {
            "level": level,
            "label": labels[level],
            "readiness_ceiling": ceiling,
            "maximum": 5,
        },
        "dimensions": dimensions,
        "summary": {
            "ready": sum(1 for item in dimensions if item["status"] == "ready"),
            "partial": sum(1 for item in dimensions if item["status"] == "partial"),
            "gaps": len(gaps),
        },
        "priority_gaps": gaps[:6],
        "safe_now": [
            "read-only discovery",
            "bounded catalog and graph queries",
            "claim-safe parallel planning",
            "test-gated scoped changes",
        ],
        "requires_fresh_gate": [
            "broad autonomous execution",
            "deployment",
            "external plugin installation",
            "billable or credentialed operations",
        ],
    }


def _build_snapshot_admitted(
    root: Path,
    *,
    project: Path | None = None,
    workspace_root: Path | None = None,
    refresh_hardware: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    project = (project or root).resolve()
    skills = list((root / "registry" / "skill_packages").glob("*.json"))
    skill_catalog_path = root / "registry" / "skill_catalog.toml"
    skill_catalog = (
        tomllib.loads(skill_catalog_path.read_text(encoding="utf-8"))
        if skill_catalog_path.is_file()
        else {"skills": []}
    )
    skill_catalog_rows = list(skill_catalog.get("skills", []))
    skill_index = _read_json(root / ".px" / "skill-index.json", {})
    skill_index_rows = (
        list(skill_index.get("records", [])) if isinstance(skill_index, Mapping) else []
    )
    native_root = root / ".px" / "skills"
    native_skill_directories = (
        [path for path in native_root.iterdir() if path.is_dir()]
        if native_root.is_dir()
        else []
    )
    tools = _array(root, "registry/tools.json", "tools")
    agents = _array(root, "registry/agency_agent_registry.json", "agents")
    project_flows = _array(
        root, "registry/project_stream_orchestrations.json", "orchestrations"
    )
    skill_flows = _array(root, "registry/skill_orchestrations.json", "workflows")
    bindings_payload = _read_json(
        root / "registry" / "workflow_execution_bindings.json", {}
    )
    binding_rows: list[Any] = []
    if isinstance(bindings_payload, Mapping):
        for key in ("bindings", "workflows", "records"):
            if isinstance(bindings_payload.get(key), list):
                binding_rows = bindings_payload[key]
                break
    validator_bindings = [
        row
        for row in binding_rows
        if isinstance(row, Mapping) and row.get("mode") == "executable_validator"
    ]
    runtime_bindings = [
        row
        for row in binding_rows
        if isinstance(row, Mapping) and row.get("mode") == "executable_runtime"
    ]
    workflow_receipts = list(
        project.glob(
            ".engineering-bootstrap/studios/workflows/*/revisions/*/admission-receipt.json"
        )
    )
    workflow_runs = list(
        project.glob(
            ".engineering-bootstrap/studios/workflows/*/revisions/*/runs/*.json"
        )
    )
    workflow_runs.extend(
        project.glob(".engineering-bootstrap/studios/workflows/runs/run-*.json")
    )
    agent_session_heads = list(
        project.glob(
            ".engineering-bootstrap/studios/agents/sessions/run-*/head.json"
        )
    )
    runnable_revisions = sum(
        1
        for path in workflow_receipts
        if _read_json(path, {}).get("runnable_state") == "runnable"
    )
    graph_payload = _read_json(root / "registry" / "cognitive_map_index.json", {})
    graph_records = (
        graph_payload.get("records", []) if isinstance(graph_payload, Mapping) else []
    )
    graph_edges = (
        graph_payload.get("edges", []) if isinstance(graph_payload, Mapping) else []
    )
    knowledge = _array(root, "registry/knowledge_sources.json", "knowledge_sources")
    models = _array(root, "registry/models.json", "models")
    integrations = _array(root, "registry/integrations.json", "integrations")
    assurance = _array(root, "registry/assurance_capabilities.json", "capabilities")
    effects = _array(root, "registry/effect_surface_ownership.json", "records")
    enterprise = _enterprise_catalog(root)
    coordination = _coordination(project)
    memory = _memory(root, workspace_root)
    knowledge_core = _knowledge_core(root, knowledge)
    completion = _completion(root)
    if not isinstance(completion, Mapping):
        completion = {}
    completion = {**dict(completion), "operational_punch_cards": _operational_punch_cards(root)}
    project_state = _project(root, project)
    attention: list[dict[str, str]] = []
    if not project_state["map"].get("valid"):
        attention.append(
            {
                "severity": "warning",
                "title": "Project map unavailable or invalid",
                "detail": str(project_state["map"].get("error") or project.name),
            }
        )
    if memory.get("configured") and not memory.get("configuration_valid"):
        attention.append(
            {
                "severity": "warning",
                "title": "Canonical memory workspace invalid",
                "detail": str(
                    memory.get("error")
                    or "Repair or select a valid Pacify-X canonical workspace."
                ),
            }
        )
    elif memory.get("project_registered") and not memory.get("lease_active"):
        attention.append(
            {
                "severity": "warning",
                "title": "Canonical memory lease required",
                "detail": "Reacquire a bounded project lease to enable canonical retrieval.",
            }
        )
    if not coordination.get("instrumented"):
        attention.append(
            {
                "severity": "info",
                "title": "Cross-IDE coordination not initialized",
                "detail": "The extension initializes the project-owned rolling ledger when this workspace is opened.",
            }
        )
    counts = {
        "skills": len(skill_catalog_rows),
        "skill_catalog_metadata": len(skill_catalog_rows),
        "skill_package_records": len(skills),
        "skill_native_packages": len(native_skill_directories),
        "skill_index_records_all_domains": len(skill_index_rows),
        "skill_preserved_originals": sum(bool(row.get("backup")) for row in skill_index_rows if isinstance(row, Mapping)),
        "skill_microsoft_vendor": sum(str(row.get("domain")) == "microsoft-vendor" for row in skill_index_rows if isinstance(row, Mapping)),
        "skill_index_default_eligible": sum(
            bool(row.get("default_eligible"))
            for row in skill_index_rows
            if isinstance(row, Mapping)
        ),
        "tools": len(tools),
        "agents": len(agents),
        "agents_registered": len(agents),
        "agents_advisory": sum(
            str(row.get("lifecycle_state")) == "advisory"
            for row in agents
            if isinstance(row, Mapping)
        ),
        "agents_reference_only": sum(
            str(row.get("lifecycle_state")) == "reference_only"
            for row in agents
            if isinstance(row, Mapping)
        ),
        "agents_runnable_revisions": sum(
            1
            for path in project.glob(
                ".engineering-bootstrap/studios/agents/*/revisions/*/admission-receipt.json"
            )
            if _read_json(path, {}).get("decision") == "admitted"
        ),
        "agents_running": sum(
            _read_json(path, {}).get("state") in {"running", "pause_requested"}
            for path in agent_session_heads
        ),
        "agent_runs": len(agent_session_heads),
        "project_orchestrations": len(project_flows),
        "skill_orchestrations": len(skill_flows),
        "execution_bindings": len(binding_rows),
        "orchestrations_total": len(project_flows)
        + len(skill_flows)
        + len(binding_rows),
        "workflow_definitions": len(project_flows) + len(skill_flows),
        "workflow_validator_bindings": len(validator_bindings),
        "workflow_runtime_bindings": len(runtime_bindings),
        "workflow_runnable_revisions": runnable_revisions,
        "workflow_runs": len(workflow_runs),
        "knowledge_sources": len(knowledge),
        "models": len(models),
        "graph_records": len(graph_records),
        "graph_edges": len(graph_edges),
        "contracts": len(list((root / "contracts").rglob("*.json"))),
        "tests": len(list((root / "tests").glob("test_*.py"))),
        "assurance": len(assurance),
        "effects": len(effects),
        "enterprise_packs": len(enterprise.get("packs", [])),
        "enterprise_skills": len(enterprise.get("skills", [])),
        "enterprise_agents": len(enterprise.get("agents", [])),
        "enterprise_workflows": len(enterprise.get("workflows", [])),
        "enterprise_connectors": len(enterprise.get("connectors", [])),
        "enterprise_models": len(enterprise.get("models", [])),
    }
    from .work_admission import RuntimeWorkPlane, WorkAdmissionTimeout
    from .host_boundaries import (
        skill_host_boundary,
        skill_index_integrity,
        startup_attribution,
        startup_log_revision,
    )

    work_plane = RuntimeWorkPlane(root)
    try:
        hardware_work = work_plane.execute(
            "dashboard.hardware",
            lambda: _hardware(root, force_refresh=refresh_hardware),
            reason="explicit dashboard runtime snapshot",
            input_fingerprint={
                "probe_policy": HARDWARE_CACHE_SCHEMA,
                "force_refresh": refresh_hardware,
            },
            domains=("hardware", "runtime"),
            lane="light",
            cache_seconds=0 if refresh_hardware else HARDWARE_CACHE_TTL_SECONDS,
            timeout_seconds=5.0,
            authoritative=False,
        )
        hardware = dict(hardware_work["result"])
        hardware["work_admission"] = hardware_work["admission"]
    except WorkAdmissionTimeout as error:
        hardware = {
            "valid": False,
            "error": str(error),
            "work_admission": {
                "decision": "wait_timeout",
                "operation": "dashboard.hardware",
                "fallback": "no duplicate probe started",
            },
        }
    try:
        startup_work = work_plane.execute(
            "dashboard.host-startup",
            startup_attribution,
            reason="explicit dashboard runtime snapshot",
            input_fingerprint=startup_log_revision(),
            domains=("startup", "host-runtime"),
            lane="light",
            cache_seconds=120,
            timeout_seconds=5.0,
            authoritative=False,
        )
        host_startup = dict(startup_work["result"])
        host_startup["work_admission"] = startup_work["admission"]
    except WorkAdmissionTimeout as error:
        host_startup = {
            "schema_version": "px.host-startup-attribution/1.0",
            "available": False,
            "limitations": [str(error)],
            "work_admission": {
                "decision": "wait_timeout",
                "operation": "dashboard.host-startup",
                "fallback": "no duplicate log scan started",
            },
        }
    try:
        skill_integrity = skill_index_integrity(root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        skill_integrity = {
            "schema_version": "px.skill-index-integrity/1.0",
            "valid": False,
            "error": f"{type(error).__name__}: {error}",
        }
    skill_boundary = skill_host_boundary(root)
    runtime_core = work_plane.snapshot()
    placement_runtime = _placement_runtime(root, hardware)
    readiness = build_readiness(
        root,
        project_state=project_state,
        counts=counts,
        coordination=coordination,
        memory=memory,
        hardware=hardware,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "connected": True,
        "mode": "canonical-dashboard-api",
        "source": {
            "root": root.as_posix(),
            "name": root.name,
            "version": _version(root),
            "branch": _git(root, "branch", "--show-current"),
            "commit": _git(root, "rev-parse", "--short", "HEAD"),
        },
        "extension_identity": _extension_source_identity(root),
        "project": project_state,
        "counts": counts,
        "memory": memory,
        "knowledge_core": knowledge_core,
        "completion": completion,
        "coordination": coordination,
        "enterprise": {
            "schema_version": enterprise.get("schema_version"),
            "catalog_id": enterprise.get("catalog_id"),
            "authority": enterprise.get("authority"),
            "separation": enterprise.get("separation", {}),
            "defaults": enterprise.get("defaults", {}),
            "packs": enterprise.get("packs", []),
            "connectors": enterprise.get("connectors", []),
            "models": enterprise.get("models", []),
            "source_evidence": enterprise.get("source_evidence", {}),
        },
        "runtime": {
            "hardware": hardware,
            "host_startup": host_startup,
            "skill_index_integrity": skill_integrity,
            "skill_host_boundary": skill_boundary,
            "models": models,
            "integrations": integrations,
            "turbovec": _turbovec(),
            "core": runtime_core,
            "execution_placement": placement_runtime,
            "bottlenecks": {
                "active_work": len(runtime_core.get("active", {})),
                "waits": int(runtime_core.get("counters", {}).get("waits", 0)),
                "failures": sum(
                    1
                    for operation in runtime_core.get("operations", [])
                    if operation.get("outcome") == "failed"
                ),
                "historical_failures": int(
                    runtime_core.get("counters", {}).get("failures", 0)
                ),
                "legacy_direct_producers": int(
                    runtime_core.get("producer_trace_summary", {}).get(
                        "legacy_direct", 0
                    )
                ),
            },
        },
        "providerActivity": _provider_activity(root),
        "readiness": readiness,
        "attention": attention,
        "provenance": {
            "counts": {
                "class": "DERIVED",
                "source": "Pacify-X registries normalized by runtime.dashboard_api",
            },
            "memory": {
                "class": "LIVE" if memory.get("instrumented") else "UNAVAILABLE",
                "source": "runtime.workspace_manager.workspace_monitor",
            },
            "coordination": {
                "class": "LIVE" if coordination.get("instrumented") else "UNAVAILABLE",
                "source": ".engineering-bootstrap/coordination",
            },
            "runtime": {
                "class": "LIVE",
                "source": "runtime.work_admission state bus + runtime.hardware_routing + execution placement artifacts",
            },
            "providerActivity": {
                "class": "LIVE",
                "source": "verified provider budget ledger; values and credentials excluded",
            },
            "readiness": {
                "class": "DERIVED",
                "source": "current static project map, registries, policies, and local sensor availability; advisory only",
            },
            "enterprise": {
                "class": "DECLARED",
                "source": "registry/ms_enterprise_catalog.json; separate enterprise namespace",
            },
        },
    }


def build_snapshot(
    root: Path,
    *,
    project: Path | None = None,
    workspace_root: Path | None = None,
    refresh_hardware: bool = False,
) -> dict[str, Any]:
    """Build one snapshot through the canonical bounded admission owner.

    The composed snapshot may invoke narrower admitted producers (hardware and
    startup attribution).  It therefore uses the interactive lane while those
    producers use the light lane, avoiding self-contention and retaining one
    single-flight identity for concurrent dashboard refreshes.
    """
    from .work_admission import RuntimeWorkPlane

    resolved_root = root.resolve()
    resolved_project = (project or resolved_root).resolve()
    resolved_workspace = workspace_root.resolve() if workspace_root else None
    work_plane = RuntimeWorkPlane(resolved_root)
    work = work_plane.execute(
        "dashboard.snapshot",
        lambda: _build_snapshot_admitted(
            resolved_root,
            project=resolved_project,
            workspace_root=resolved_workspace,
            refresh_hardware=refresh_hardware,
        ),
        reason="explicit canonical dashboard snapshot",
        input_fingerprint={
            "root": resolved_root.as_posix(),
            "project": resolved_project.as_posix(),
            "workspace_root": resolved_workspace.as_posix() if resolved_workspace else None,
            "refresh_hardware": refresh_hardware,
        },
        domains=("dashboard", "runtime"),
        lane="interactive",
        cache_seconds=0,
        timeout_seconds=30.0,
        authoritative=False,
    )
    result = dict(work["result"])
    result["work_admission"] = work["admission"]
    return result


def _normalize(kind: str, row: Mapping[str, Any], index: int) -> dict[str, Any]:
    catalog_kind = str(row.get("catalog_kind") or kind)
    record_id = (
        row.get("id")
        or row.get("agent_id")
        or row.get("skill_id")
        or row.get("workflow_id")
        or row.get("orchestration_id")
        or row.get("binding_id")
        or row.get("key")
    )
    label = row.get("label") or row.get("title") or row.get("name")
    summary = (
        row.get("description")
        or row.get("summary")
        or row.get("purpose")
        or row.get("source_title")
        or ""
    )
    if catalog_kind == "execution-binding" and not record_id:
        stem = Path(str(row.get("path") or "binding")).stem
        record_id = f"execution-binding:{stem}"
        label = (
            label
            or f"{stem.replace('-', ' ').replace('_', ' ').title()} — execution binding"
        )
        mode = str(row.get("mode") or "declared binding").replace("_", " ")
        entrypoint = str(row.get("entrypoint") or "entrypoint unavailable")
        summary = summary or f"{mode.capitalize()} through {entrypoint}."
    record_id = record_id or f"{kind}-{index + 1}"
    label = label or _humanize_identifier(record_id)
    status = (
        row.get("status")
        or row.get("lifecycle_state")
        or row.get("integration_status")
        or row.get("source_status")
        or "declared"
    )
    tags: list[str] = []
    for key in ("capability_tags", "capabilities", "tags", "skills", "concepts"):
        if isinstance(row.get(key), list):
            tags.extend(str(item) for item in row[key])
    effects = (
        [str(item) for item in row.get("effects", [])]
        if isinstance(row.get("effects"), list)
        else []
    )
    normalized = {
        "id": str(record_id),
        "label": str(label),
        "status": str(status),
        "kind": catalog_kind,
        "summary": str(summary),
        "tags": sorted(set(tags)),
        "effects": effects,
        "risk": row.get("risk_tier") or row.get("risk") or None,
        "owner": row.get("runtime_owner")
        or row.get("owner")
        or row.get("provenance", {}).get("canonical_owner")
        if isinstance(row.get("provenance"), Mapping)
        else row.get("runtime_owner") or row.get("owner"),
        "path": row.get("path")
        or row.get("body")
        or row.get("source_path")
        or row.get("manifest_path"),
        "details": dict(row),
    }
    if kind in {"agents", "enterprise-agents"} or "agent" in catalog_kind:
        capabilities = sorted(set(tags))
        handoffs = (
            [str(item) for item in row.get("handoffs", [])]
            if isinstance(row.get("handoffs"), list)
            else []
        )
        avoid_when = (
            [str(item) for item in row.get("avoid_when", [])]
            if isinstance(row.get("avoid_when"), list)
            else []
        )
        checks = {
            "stable_identity": bool(record_id and label),
            "description": bool(summary),
            "capabilities": bool(capabilities),
            "lifecycle": bool(status),
            "provenance": bool(
                row.get("manifest_path") or row.get("path") or row.get("source_path")
            ),
            "safety_boundary": bool(
                avoid_when
                or row.get("requires_human_review") is not None
                or row.get("risk_tier")
                or row.get("risk")
            ),
        }
        normalized["agent_model"] = {
            "schema_version": "1.0",
            "identity": {
                "id": str(record_id),
                "name": str(label),
                "division": row.get("division"),
                "role_mode": row.get("role_mode"),
            },
            "capabilities": capabilities,
            "handoffs": handoffs,
            "boundaries": {
                "avoid_when": avoid_when,
                "requires_human_review": row.get("requires_human_review"),
                "risk": normalized["risk"],
            },
            "lifecycle": {
                "status": str(status),
                "source_audit_status": row.get("source_audit_status"),
            },
            "provenance": {
                "path": normalized["path"],
                "manifest_path": row.get("manifest_path"),
                "manifest_sha256": row.get("manifest_sha256"),
                "body_sha256": row.get("body_sha256"),
            },
            "readiness": {
                "passed": sum(1 for value in checks.values() if value),
                "total": len(checks),
                "checks": checks,
                "status": "complete" if all(checks.values()) else "partial",
            },
        }
    return normalized


def catalog_rows(root: Path, kind: str) -> list[dict[str, Any]]:
    root = root.resolve()
    if kind == "skills":
        rows = [
            {**row, "catalog_kind": "px-native-skill"}
            for row in _skill_rows(root)
            if row.get("domain") == "px-standard" and row.get("native")
        ]
    elif kind == "preserved-skills":
        rows = [
            {**row, "catalog_kind": "preserved-skill-backup"}
            for row in _skill_rows(root)
            if row.get("backup")
        ]
    elif kind == "microsoft-skills":
        rows = [
            {**row, "catalog_kind": "microsoft-vendor-skill"}
            for row in _skill_rows(root)
            if row.get("domain") == "microsoft-vendor"
        ]
    elif kind == "tools":
        rows = _array(root, "registry/tools.json", "tools")
    elif kind == "agents":
        rows = _array(root, "registry/agency_agent_registry.json", "agents")
    elif kind == "workflows":
        rows = _workflow_rows(root)
    elif kind == "graph":
        rows = _array(root, "registry/cognitive_map_index.json", "records")
    elif kind == "enterprise-skills":
        rows = _enterprise_rows(root, "skills", "ms-enterprise-skill")
    elif kind == "enterprise-agents":
        rows = _enterprise_rows(root, "agents", "ms-enterprise-agent")
    elif kind == "enterprise-workflows":
        rows = _enterprise_rows(root, "workflows", "ms-enterprise-workflow")
    elif kind == "enterprise-integrations":
        rows = _enterprise_rows(root, "connectors", "ms-enterprise-connector")
    elif kind == "enterprise-models":
        rows = _enterprise_rows(root, "models", "ms-enterprise-model")
    else:
        raise ValueError(f"unsupported catalog kind: {kind}")
    return [_normalize(kind, row, index) for index, row in enumerate(rows)]


def query_catalog(
    root: Path,
    kind: str,
    *,
    query: str = "",
    status: str = "",
    offset: int = 0,
    limit: int = 50,
    sort: str = "label",
) -> dict[str, Any]:
    rows = catalog_rows(root, kind)
    total = len(rows)
    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    needle = query.casefold().strip()
    wanted_status = status.casefold().strip()
    if needle:
        rows = [
            row
            for row in rows
            if needle
            in " ".join(
                [row["id"], row["label"], row["summary"], row["kind"], *row["tags"]]
            ).casefold()
        ]
    if wanted_status:
        rows = [row for row in rows if row["status"].casefold() == wanted_status]
    sort_key = sort if sort in {"id", "label", "status", "kind"} else "label"
    rows.sort(
        key=lambda row: (str(row.get(sort_key, "")).casefold(), row["id"].casefold())
    )
    bounded_limit = max(1, min(MAX_PAGE_SIZE, int(limit)))
    bounded_offset = max(0, int(offset))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "kind": kind,
        "source": "runtime.dashboard_api",
        "total": total,
        "status_counts": dict(sorted(status_counts.items())),
        "filtered": len(rows),
        "offset": bounded_offset,
        "limit": bounded_limit,
        "items": rows[bounded_offset : bounded_offset + bounded_limit],
        "has_more": bounded_offset + bounded_limit < len(rows),
    }


def query_canonical_memory(
    workspace_root: Path,
    *,
    query: str = "",
    offset: int = 0,
    limit: int = 60,
    status: str = "",
    project_id: str = "",
    source: str = "",
) -> dict[str, Any]:
    from .workspace_manager import browse_canonical_memory

    return dict(
        browse_canonical_memory(
            workspace_root.resolve(strict=True),
            query,
            offset=max(0, min(10_000, int(offset))),
            limit=max(1, min(100, int(limit))),
            status=status,
            project_id=project_id,
            source=source,
        )
    )


def _graph_node(row: Mapping[str, Any]) -> dict[str, Any]:
    provenance = row.get("provenance")
    if not isinstance(provenance, Mapping):
        provenance = {}
    source = row.get("source")
    if not isinstance(source, Mapping):
        source = {}
    aliases = row.get("aliases")
    if not isinstance(aliases, Sequence) or isinstance(aliases, (str, bytes)):
        aliases = ()
    node = {
        "key": str(row.get("key") or row.get("id") or ""),
        "id": str(row.get("id") or row.get("key") or ""),
        "title": str(
            row.get("title")
            or row.get("name")
            or row.get("id")
            or row.get("key")
            or "Unknown"
        ),
        "kind": str(row.get("kind") or "unknown"),
        "summary": str(row.get("summary") or ""),
        "owner": row.get("owner"),
        "status": str(row.get("status") or "unknown"),
        "domain": row.get("domain"),
        "path": row.get("path") or row.get("implementation_path"),
        "risk": row.get("risk"),
        "community_id": row.get("community_id"),
        "degree": int(row.get("degree") or 0),
        "source": dict(source),
        "provenance": dict(provenance),
        "source_sha256": row.get("source_sha256") or row.get("sha256"),
        "aliases": [str(alias) for alias in aliases if str(alias)],
    }
    return node


def _graph_edge(
    edge: Mapping[str, Any], by_key: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    source = str(edge.get("source") or edge.get("from") or "")
    target = str(edge.get("target") or edge.get("to") or "")
    relation = str(edge.get("relation") or edge.get("kind") or "related_to")
    source_title = str(by_key.get(source, {}).get("title") or source)
    target_title = str(by_key.get(target, {}).get("title") or target)
    provenance = edge.get("provenance")
    if not isinstance(provenance, Mapping):
        provenance = {}
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "why": str(
            edge.get("why")
            or f"{source_title} —{relation}→ {target_title}"
        ),
        "status": edge.get("status"),
        "evidence": edge.get("evidence") or edge.get("evidence_refs") or [],
        "source_path": edge.get("source_path") or edge.get("path"),
        "source_sha256": edge.get("source_sha256") or edge.get("sha256"),
        "provenance": dict(provenance),
    }


def _graph_edit_distance(left: str, right: str) -> int:
    """Interpreter-neutral bounded Levenshtein distance for graph metadata."""
    left = left.casefold()
    right = right.casefold()
    if len(left) > len(right):
        left, right = right, left
    row = list(range(len(left) + 1))
    for right_index, right_value in enumerate(right, start=1):
        previous = row[0]
        row[0] = right_index
        for left_index, left_value in enumerate(left, start=1):
            diagonal = previous
            previous = row[left_index]
            row[left_index] = min(
                row[left_index] + 1,
                row[left_index - 1] + 1,
                diagonal + (left_value != right_value),
            )
    return row[-1]


def _graph_fuzzy_score(query: str, fields: Sequence[str]) -> int:
    query_tokens = re.findall(r"[a-z0-9]+", query.casefold())
    field_tokens = [
        token
        for field in fields
        for token in re.findall(r"[a-z0-9]+", field.casefold())
    ]
    if not query_tokens or not field_tokens:
        return 0
    score = 0
    for query_token in query_tokens:
        tolerance = 2 if len(query_token) >= 8 else 1 if len(query_token) >= 4 else 0
        distances = (_graph_edit_distance(query_token, token) for token in field_tokens)
        distance = min(distances, default=len(query_token))
        if distance > tolerance:
            return 0
        score += 38 - distance * 8
    return score


def _graph_cluster_identity(row: Mapping[str, Any], view: str) -> tuple[str, str, str]:
    """Build useful semantic overview groups instead of one bubble per record kind."""
    kind = str(row.get("kind") or "unknown").strip().casefold() or "unknown"
    if view == "capabilities":
        facet = str(row.get("domain") or row.get("category") or "general").strip().casefold()
        if kind == "skill":
            searchable = " ".join(
                str(row.get(field) or "")
                for field in ("id", "title", "summary", "domain")
            ).casefold()
            buckets = (
                ("security", ("security", "threat", "secret", "vulnerab")),
                ("testing-and-assurance", ("test", "verify", "validat", "audit", "assurance")),
                ("knowledge-and-memory", ("knowledge", "memory", "retriev", "learn")),
                ("agents-and-orchestration", ("agent", "orchestrat", "workflow", "parallel", "handoff")),
                ("release-and-deployment", ("release", "deploy", "package", "install")),
                ("data-and-integrations", ("data", "database", "api", "integration", "supabase", "n8n")),
                ("runtime-and-performance", ("runtime", "performance", "gpu", "hardware", "latency")),
                ("project-and-repository", ("project", "repository", "git", "dependency", "architecture")),
                ("governance-and-policy", ("govern", "policy", "authority", "contract", "admission")),
                ("research-and-analysis", ("research", "analy", "reason", "decision")),
            )
            facet = next((name for name, words in buckets if any(word in searchable for word in words)), "general")
        if "/" in facet:
            facet = facet.split("/", 1)[0]
    else:
        value = str(row.get("path") or row.get("id") or row.get("key") or "")
        normalized = value.replace("\\", "/")
        if kind == "external_package":
            normalized = "dependencies"
        elif "/" in normalized:
            head, tail = normalized.split("/", 1)
            normalized = f"{head.split(':')[-1]}/{tail}"
        elif ":" in normalized:
            normalized = "project-root"
        normalized = normalized.lstrip("./")
        facet = normalized.split("/", 1)[0].casefold() if normalized else "project-root"
        if not facet or ("." in facet and "/" not in normalized):
            facet = "project-root"
    facet = re.sub(r"[^a-z0-9._-]+", "-", facet).strip("-") or "general"
    cluster_id = f"{kind}::{facet}"
    return cluster_id, f"{_humanize_identifier(kind)} · {_humanize_identifier(facet)}", facet


def query_graph(
    root: Path,
    *,
    project: Path | None = None,
    view: str = "capabilities",
    node: str = "",
    target: str = "",
    query: str = "",
    relation: str = "",
    direction: str = "both",
    mode: str = "neighborhood",
    cluster: str = "",
    kind: str = "",
    status: str = "",
    offset: int = 0,
    edge_offset: int = 0,
    depth: int = 1,
    max_nodes: int = 24,
    max_edges: int = 48,
) -> dict[str, Any]:
    """Return a deterministic bounded graph page or relationship neighborhood."""
    if view not in {"capabilities", "repository"}:
        raise ValueError("graph view must be capabilities or repository")
    if direction not in {"incoming", "outgoing", "both"}:
        raise ValueError("graph direction must be incoming, outgoing, or both")
    graph_modes = {
        "full",
        "overview",
        "neighborhood",
        "path",
        "impact",
        "dependencies",
        "dependents",
        "hubs",
        "orphans",
        "provenance",
    }
    if mode not in graph_modes:
        raise ValueError(f"graph mode must be one of {', '.join(sorted(graph_modes))}")
    bounded_depth = max(1, min(6, int(depth)))
    bounded_nodes = max(2, min(500, int(max_nodes)))
    bounded_edges = max(1, min(1000, int(max_edges)))
    bounded_offset = max(0, min(10_000_000, int(offset)))
    bounded_edge_offset = max(0, min(10_000_000, int(edge_offset)))
    root = root.resolve()
    if view == "repository":
        project = (project or root).resolve()
        source_path = (
            project
            / ".engineering-bootstrap"
            / "project-map"
            / "architecture-graph.json"
        )
        if not source_path.is_file():
            return {
                "schema_version": SCHEMA_VERSION,
                "generated_at": _now(),
                "available": False,
                "source": source_path.as_posix(),
                "view": view,
                "selected": None,
                "nodes": [],
                "edges": [],
                "relations": [],
                "requested_query": query,
                "requested_relation": relation,
                "search_results": [],
                "ambiguous_matches": [],
                "total_nodes": None,
                "total_edges": None,
                "direction": direction,
                "depth": bounded_depth,
                "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
                "truncated": False,
                "limitations": [
                    "Repository architecture graph is missing; no zero-node graph is inferred."
                ],
                "build_action": {
                    "operation": "project-map build",
                    "project": project.as_posix(),
                    "approval_required": True,
                },
            }
        payload = _read_json(source_path, {})
        raw_records = payload.get("nodes", []) if isinstance(payload, Mapping) else []
        records = [
            {
                **dict(row),
                "key": row.get("id"),
                "title": row.get("name") or row.get("id"),
                "summary": row.get("contract_kind")
                or row.get("ecosystem_hint")
                or row.get("kind"),
                "status": "mapped",
                "path": str(row.get("id") or "").removeprefix("file:")
                if str(row.get("id") or "").startswith("file:")
                else None,
            }
            for row in raw_records
            if isinstance(row, Mapping)
        ]
        raw_edges = (
            [
                {
                    **dict(edge),
                    "source": edge.get("from"),
                    "target": edge.get("to"),
                    "relation": edge.get("kind"),
                }
                for edge in payload.get("edges", [])
                if isinstance(edge, Mapping)
            ]
            if isinstance(payload, Mapping)
            else []
        )
    else:
        source_path = root / "registry" / "cognitive_map_index.json"
        payload = _read_json(source_path, {})
        records = payload.get("records", []) if isinstance(payload, Mapping) else []
        raw_edges = payload.get("edges", []) if isinstance(payload, Mapping) else []
    rows = [
        row
        for row in records
        if isinstance(row, Mapping) and (row.get("key") or row.get("id"))
    ]
    by_key = {str(row.get("key") or row.get("id")): row for row in rows}
    aliases: dict[str, set[str]] = {}
    for key, row in by_key.items():
        aliases.setdefault(key.casefold(), set()).add(key)
        aliases.setdefault(str(row.get("id") or "").casefold(), set()).add(key)
    edges = [
        _graph_edge(edge, by_key)
        for edge in raw_edges
        if isinstance(edge, Mapping)
        and str(edge.get("source") or edge.get("from") or "") in by_key
        and str(edge.get("target") or edge.get("to") or "") in by_key
    ]
    relation_filter = relation.casefold().strip()
    if relation_filter:
        edges = [
            edge for edge in edges if edge["relation"].casefold() == relation_filter
        ]
    if mode == "provenance" and not relation_filter:
        provenance_tokens = (
            "source",
            "evidence",
            "provenance",
            "derive",
            "declare",
            "validate",
            "promote",
            "admit",
        )
        edges = [
            edge
            for edge in edges
            if any(token in edge["relation"].casefold() for token in provenance_tokens)
        ]
    if mode == "full":
        requested_cluster = cluster.casefold().strip()
        requested_kind = kind.casefold().strip()
        requested_status = status.casefold().strip()
        eligible_rows: dict[str, dict[str, Any]] = {}
        communities: dict[str, dict[str, Any]] = {}
        for key, source_row in by_key.items():
            community_id, community_label, community_facet = _graph_cluster_identity(
                source_row, view
            )
            row_kind = str(source_row.get("kind") or "unknown").casefold()
            row_status = str(source_row.get("status") or "unknown").casefold()
            if requested_cluster and requested_cluster not in {
                community_id.casefold(),
                row_kind,
            }:
                continue
            if requested_kind and row_kind != requested_kind:
                continue
            if requested_status and row_status != requested_status:
                continue
            eligible_rows[key] = {
                **dict(source_row),
                "community_id": community_id,
            }
            community = communities.setdefault(
                community_id,
                {
                    "id": community_id,
                    "label": community_label,
                    "facet": community_facet,
                    "kind": row_kind,
                    "member_count": 0,
                    "edge_count": 0,
                    "status_counts": Counter(),
                },
            )
            community["member_count"] += 1
            community["status_counts"][row_status] += 1
        eligible_edges = [
            edge
            for edge in edges
            if edge["source"] in eligible_rows and edge["target"] in eligible_rows
        ]
        degree: Counter[str] = Counter()
        for edge in eligible_edges:
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1
            source_community = eligible_rows[edge["source"]]["community_id"]
            target_community = eligible_rows[edge["target"]]["community_id"]
            communities[source_community]["edge_count"] += 1
            if target_community != source_community:
                communities[target_community]["edge_count"] += 1
        ordered_keys = sorted(
            eligible_rows,
            key=lambda key: (
                str(eligible_rows[key]["community_id"]),
                -degree[key],
                str(eligible_rows[key].get("title") or key).casefold(),
                key.casefold(),
            ),
        )
        ordered_edges = sorted(
            eligible_edges,
            key=lambda edge: (
                edge["relation"].casefold(),
                edge["source"].casefold(),
                edge["target"].casefold(),
            ),
        )
        node_page_keys = ordered_keys[bounded_offset : bounded_offset + bounded_nodes]
        edge_page = ordered_edges[
            bounded_edge_offset : bounded_edge_offset + bounded_edges
        ]
        node_has_more = bounded_offset + len(node_page_keys) < len(ordered_keys)
        edge_has_more = bounded_edge_offset + len(edge_page) < len(ordered_edges)
        selected_key = str(node or "")
        if selected_key not in eligible_rows:
            selected_key = node_page_keys[0] if node_page_keys else None
        needle = query.casefold().strip()
        ranked_matches: list[tuple[int, int, str, str, str]] = []
        if needle:
            for key, row in eligible_rows.items():
                fields = [
                    key,
                    str(row.get("id") or ""),
                    str(row.get("title") or ""),
                    str(row.get("summary") or ""),
                    str(row.get("path") or ""),
                ]
                haystack = " ".join(fields).casefold()
                exact = needle in {
                    fields[0].casefold(),
                    fields[1].casefold(),
                    fields[2].casefold(),
                }
                prefix = any(field.casefold().startswith(needle) for field in fields[:3])
                contains = needle in haystack
                fuzzy_score = _graph_fuzzy_score(needle, fields)
                if exact or prefix or contains or fuzzy_score:
                    match = (
                        "exact"
                        if exact
                        else "prefix"
                        if prefix
                        else "contains"
                        if contains
                        else f"fuzzy-token score {fuzzy_score}"
                    )
                    ranked_matches.append(
                        (
                            0 if exact else 1 if prefix else 2 if contains else 3,
                            -fuzzy_score,
                            str(row.get("title") or key).casefold(),
                            key,
                            match,
                        )
                    )
            ranked_matches.sort()
        community_rows = [
            {
                **{key: value for key, value in row.items() if key != "status_counts"},
                "status_counts": dict(sorted(row["status_counts"].items())),
            }
            for row in sorted(
                communities.values(),
                key=lambda row: (-int(row["member_count"]), str(row["label"])),
            )
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "source": source_path.as_posix(),
            "source_provenance": payload.get("provenance", {})
            if isinstance(payload, Mapping)
            else {},
            "view": view,
            "mode": "full",
            "selected": selected_key,
            "nodes": [
                _graph_node({**eligible_rows[key], "degree": degree[key]})
                for key in node_page_keys
            ],
            "edges": edge_page,
            "communities": community_rows,
            "available_kinds": sorted(
                {str(row.get("kind") or "unknown") for row in by_key.values()}
            ),
            "available_statuses": sorted(
                {str(row.get("status") or "unknown") for row in by_key.values()}
            ),
            "relations": sorted({edge["relation"] for edge in edges}),
            "requested_query": query,
            "requested_relation": relation,
            "requested_cluster": cluster,
            "requested_kind": kind,
            "requested_status": status,
            "search_results": [
                {
                    **_graph_node(eligible_rows[item[3]]),
                    "rank": index + 1,
                    "match": item[4],
                }
                for index, item in enumerate(ranked_matches[:20])
            ],
            "ambiguous_matches": [],
            "source_total_nodes": len(by_key),
            "source_total_edges": len(raw_edges),
            "total_nodes": len(eligible_rows),
            "total_edges": len(eligible_edges),
            "covered_nodes": len(node_page_keys),
            "covered_edges": len(edge_page),
            "direction": direction,
            "depth": 0,
            "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
            "page": {
                "node_offset": bounded_offset,
                "node_returned": len(node_page_keys),
                "next_node_offset": bounded_offset + len(node_page_keys),
                "node_has_more": node_has_more,
                "edge_offset": bounded_edge_offset,
                "edge_returned": len(edge_page),
                "next_edge_offset": bounded_edge_offset + len(edge_page),
                "edge_has_more": edge_has_more,
            },
            "truncated": node_has_more or edge_has_more,
            "available": True,
            "representation": "record-page",
            "limitations": [
                "The full map is delivered in independent bounded node and edge pages. Loaded coverage is reported separately from source denominators."
            ],
        }
    if mode == "overview":
        cluster_members: dict[str, list[str]] = {}
        cluster_labels: dict[str, str] = {}
        cluster_facets: dict[str, str] = {}
        for key, row in by_key.items():
            cluster_id, cluster_label, cluster_facet = _graph_cluster_identity(row, view)
            cluster_members.setdefault(cluster_id, []).append(key)
            cluster_labels[cluster_id] = cluster_label
            cluster_facets[cluster_id] = cluster_facet
        cluster_nodes = []
        for cluster_id, members in sorted(
            cluster_members.items(), key=lambda item: (-len(item[1]), item[0])
        ):
            statuses = Counter(str(by_key[key].get("status") or "unknown") for key in members)
            cluster_nodes.append(
                {
                    "key": f"cluster:{cluster_id}",
                    "id": f"cluster:{cluster_id}",
                    "title": cluster_labels[cluster_id],
                    "kind": "cluster",
                    "cluster_kind": str(by_key[members[0]].get("kind") or "unknown"),
                    "cluster_facet": cluster_facets[cluster_id],
                    "summary": f"{len(members)} records in the {cluster_labels[cluster_id]} semantic group.",
                    "status": statuses.most_common(1)[0][0],
                    "member_count": len(members),
                    "status_counts": dict(sorted(statuses.items())),
                }
            )
        aggregate: Counter[tuple[str, str]] = Counter()
        aggregate_relations: dict[tuple[str, str], Counter[str]] = {}
        for edge in edges:
            source_kind = _graph_cluster_identity(by_key[edge["source"]], view)[0]
            target_kind = _graph_cluster_identity(by_key[edge["target"]], view)[0]
            pair = (source_kind, target_kind)
            aggregate[pair] += 1
            aggregate_relations.setdefault(pair, Counter())[edge["relation"]] += 1
        cluster_edges = [
            {
                "source": f"cluster:{source_kind}",
                "target": f"cluster:{target_kind}",
                "relation": "aggregate",
                "count": count,
                "relation_counts": dict(sorted(aggregate_relations[(source_kind, target_kind)].items())),
                "why": f"{count} typed relationship{'s' if count != 1 else ''} connect these complete-map groups.",
            }
            for (source_kind, target_kind), count in sorted(
                aggregate.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        selected_cluster = cluster_nodes[0]["key"] if cluster_nodes else None
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "source": source_path.as_posix(),
            "view": view,
            "mode": "overview",
            "selected": selected_cluster,
            "nodes": cluster_nodes,
            "edges": cluster_edges,
            "relations": sorted({edge["relation"] for edge in edges}),
            "requested_query": query,
            "requested_relation": relation,
            "search_results": [],
            "ambiguous_matches": [],
            "total_nodes": len(by_key),
            "total_edges": len(edges),
            "covered_nodes": sum(item["member_count"] for item in cluster_nodes),
            "covered_edges": sum(item["count"] for item in cluster_edges),
            "direction": direction,
            "depth": 0,
            "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
            "truncated": False,
            "available": True,
            "overview_level": "kind-and-domain" if view == "capabilities" else "kind-and-project-area",
            "limitations": ["Overview groups preserve complete counts while separating record kind by semantic domain or project area; drill into a group for bounded record-level relationships."],
        }
    if mode in {"hubs", "orphans"}:
        degree: Counter[str] = Counter()
        for edge in edges:
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1
        if mode == "hubs":
            selected_keys = [
                key
                for key in sorted(by_key, key=lambda item: (-degree[item], item.casefold()))
                if degree[key] > 0
            ][:bounded_nodes]
        else:
            selected_keys = [
                key for key in sorted(by_key, key=str.casefold) if degree[key] == 0
            ][:bounded_nodes]
        selected_set = set(selected_keys)
        selected_edges = [
            {
                **edge,
                "why": f"{by_key[edge['source']].get('title') or edge['source']} —{edge['relation']}→ {by_key[edge['target']].get('title') or edge['target']}",
            }
            for edge in edges
            if edge["source"] in selected_set and edge["target"] in selected_set
        ][:bounded_edges]
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "source": source_path.as_posix(),
            "view": view,
            "mode": mode,
            "selected": selected_keys[0] if selected_keys else None,
            "nodes": [
                {**_graph_node(by_key[key]), "degree": degree[key]}
                for key in selected_keys
            ],
            "edges": selected_edges,
            "relations": sorted({edge["relation"] for edge in edges}),
            "requested_query": query,
            "requested_relation": relation,
            "requested_target": target,
            "search_results": [],
            "ambiguous_matches": [],
            "total_nodes": len(by_key),
            "total_edges": len(edges),
            "direction": direction,
            "depth": 0,
            "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
            "truncated": len(selected_keys) < (
                sum(1 for key in by_key if degree[key] > 0)
                if mode == "hubs"
                else sum(1 for key in by_key if degree[key] == 0)
            ),
            "available": True,
            "limitations": [],
        }
    requested_alias = node.casefold().strip()
    alias_matches = (
        sorted(aliases.get(requested_alias, set())) if requested_alias else []
    )
    ambiguous_matches = (
        [_graph_node(by_key[key]) for key in alias_matches]
        if len(alias_matches) > 1
        else []
    )
    selected_key = alias_matches[0] if len(alias_matches) == 1 else None
    requested_cluster = cluster.casefold().strip()
    needle = query.casefold().strip()
    candidates: list[tuple[int, int, str, str, str]] = []
    if needle:
        for key, row in by_key.items():
            fields = [
                key,
                str(row.get("id") or ""),
                str(row.get("title") or ""),
                str(row.get("summary") or ""),
            ]
            haystack = " ".join(fields).casefold()
            exact = needle in {
                fields[0].casefold(),
                fields[1].casefold(),
                fields[2].casefold(),
            }
            prefix = any(field.casefold().startswith(needle) for field in fields[:3])
            contains = needle in haystack
            fuzzy_score = _graph_fuzzy_score(needle, fields)
            if exact or prefix or contains or fuzzy_score:
                match = (
                    "exact"
                    if exact
                    else "prefix"
                    if prefix
                    else "contains"
                    if contains
                    else f"fuzzy-token score {fuzzy_score}"
                )
                candidates.append(
                    (
                        0 if exact else 1 if prefix else 2 if contains else 3,
                        -fuzzy_score,
                        str(row.get("title") or key).casefold(),
                        key,
                        match,
                    )
                )
        candidates.sort()
        if selected_key is None and candidates:
            selected_key = candidates[0][3]
    search_results = [
        {
            **_graph_node(by_key[item[3]]),
            "rank": index + 1,
            "match": item[4],
        }
        for index, item in enumerate(candidates[:20])
    ]
    if selected_key is None and by_key and not ambiguous_matches:
        degree = Counter()
        for edge in edges:
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1
        eligible = [
            key
            for key, row in by_key.items()
            if not requested_cluster
            or str(row.get("kind") or "unknown").casefold() == requested_cluster
            or _graph_cluster_identity(row, view)[0].casefold() == requested_cluster
        ]
        selected_key = sorted(eligible or list(by_key), key=lambda key: (-degree[key], key.casefold()))[0]
    if selected_key is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "source": source_path.as_posix(),
            "view": view,
            "selected": None,
            "nodes": [],
            "edges": [],
            "relations": [],
            "requested_query": query,
            "requested_relation": relation,
            "search_results": search_results,
            "ambiguous_matches": ambiguous_matches,
            "total_nodes": len(by_key),
            "total_edges": len(edges),
            "direction": direction,
            "depth": bounded_depth,
            "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
            "truncated": False,
            "available": True,
            "limitations": ["Node identifier is ambiguous; select a qualified key."]
            if ambiguous_matches
            else [],
        }
    effective_direction = {
        "impact": "outgoing",
        "dependencies": "outgoing",
        "dependents": "incoming",
    }.get(mode, direction)
    adjacency: dict[str, list[dict[str, str]]] = {key: [] for key in by_key}
    for edge in edges:
        if effective_direction in {"outgoing", "both"}:
            adjacency[edge["source"]].append(edge)
        if effective_direction in {"incoming", "both"}:
            adjacency[edge["target"]].append(edge)
    for values in adjacency.values():
        values.sort(key=lambda edge: (edge["relation"], edge["source"], edge["target"]))
    if mode == "path":
        target_needle = target.casefold().strip()
        target_matches = sorted(aliases.get(target_needle, set())) if target_needle else []
        if len(target_matches) != 1 and target_needle:
            target_matches = sorted(
                key
                for key, row in by_key.items()
                if target_needle in " ".join(
                    (
                        key,
                        str(row.get("id") or ""),
                        str(row.get("title") or ""),
                    )
                ).casefold()
            )
        target_key = target_matches[0] if len(target_matches) == 1 else None
        if target_key is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "generated_at": _now(),
                "source": source_path.as_posix(),
                "view": view,
                "mode": mode,
                "selected": selected_key,
                "target": None,
                "nodes": [_graph_node(by_key[selected_key])],
                "edges": [],
                "relations": sorted({edge["relation"] for edge in edges}),
                "requested_query": query,
                "requested_target": target,
                "requested_relation": relation,
                "search_results": search_results,
                "ambiguous_matches": ambiguous_matches,
                "total_nodes": len(by_key),
                "total_edges": len(edges),
                "direction": effective_direction,
                "depth": 0,
                "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
                "truncated": False,
                "available": True,
                "limitations": ["Choose one unambiguous path target."],
            }
        queue: deque[str] = deque([selected_key])
        parents: dict[str, tuple[str, dict[str, str]] | None] = {selected_key: None}
        while queue and target_key not in parents:
            current = queue.popleft()
            for edge in adjacency.get(current, []):
                neighbor = edge["target"] if edge["source"] == current else edge["source"]
                if neighbor not in parents:
                    parents[neighbor] = (current, edge)
                    queue.append(neighbor)
        if target_key not in parents:
            path_keys = [selected_key, target_key]
            path_edges: list[dict[str, str]] = []
            path_limitations = ["No path exists for the selected relation and direction filters."]
        else:
            path_keys = []
            path_edges = []
            cursor = target_key
            while cursor != selected_key:
                path_keys.append(cursor)
                parent, edge = parents[cursor]  # type: ignore[misc]
                path_edges.append(
                    {
                        **edge,
                        "why": f"{by_key[edge['source']].get('title') or edge['source']} —{edge['relation']}→ {by_key[edge['target']].get('title') or edge['target']}",
                    }
                )
                cursor = parent
            path_keys.append(selected_key)
            path_keys.reverse()
            path_edges.reverse()
            path_limitations = []
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "source": source_path.as_posix(),
            "view": view,
            "mode": mode,
            "selected": selected_key,
            "target": target_key,
            "nodes": [_graph_node(by_key[key]) for key in path_keys],
            "edges": path_edges,
            "relations": sorted({edge["relation"] for edge in edges}),
            "requested_query": query,
            "requested_target": target,
            "requested_relation": relation,
            "search_results": search_results,
            "ambiguous_matches": ambiguous_matches,
            "total_nodes": len(by_key),
            "total_edges": len(edges),
            "direction": effective_direction,
            "depth": max(0, len(path_keys) - 1),
            "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
            "truncated": False,
            "available": True,
            "limitations": path_limitations,
        }
    selected_nodes = {selected_key}
    selected_edges: list[dict[str, str]] = []
    frontier = [selected_key]
    seen_edges: set[tuple[str, str, str]] = set()
    truncated = False
    for _ in range(bounded_depth):
        next_frontier: list[str] = []
        for current in frontier:
            for edge in adjacency.get(current, []):
                edge_key = (edge["source"], edge["relation"], edge["target"])
                if edge_key in seen_edges:
                    continue
                neighbor = (
                    edge["target"] if edge["source"] == current else edge["source"]
                )
                if (
                    neighbor not in selected_nodes
                    and len(selected_nodes) >= bounded_nodes
                ):
                    truncated = True
                    continue
                if len(selected_edges) >= bounded_edges:
                    truncated = True
                    break
                selected_nodes.add(neighbor)
                seen_edges.add(edge_key)
                source_title = str(
                    by_key[edge["source"]].get("title")
                    or by_key[edge["source"]].get("id")
                    or edge["source"]
                )
                target_title = str(
                    by_key[edge["target"]].get("title")
                    or by_key[edge["target"]].get("id")
                    or edge["target"]
                )
                selected_edges.append(
                    {
                        **edge,
                        "why": f"{source_title} —{edge['relation']}→ {target_title}",
                    }
                )
                if neighbor not in frontier and neighbor not in next_frontier:
                    next_frontier.append(neighbor)
            if len(selected_edges) >= bounded_edges:
                break
        frontier = sorted(next_frontier)
        if not frontier or len(selected_edges) >= bounded_edges:
            break
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "source": source_path.as_posix(),
        "view": view,
        "mode": mode,
        "cluster": cluster or None,
        "selected": selected_key,
        "nodes": [_graph_node(by_key[key]) for key in sorted(selected_nodes)],
        "edges": selected_edges,
        "relations": sorted({edge["relation"] for edge in edges}),
        "requested_query": query,
        "ambiguous_matches": ambiguous_matches,
        "requested_relation": relation,
        "search_results": search_results,
        "total_nodes": len(by_key),
        "total_edges": len(edges),
        "direction": effective_direction,
        "depth": bounded_depth,
        "limits": {"max_nodes": bounded_nodes, "max_edges": bounded_edges},
        "truncated": truncated,
        "available": True,
        "limitations": [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pacify-X dashboard adapter")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--source-root", type=Path, required=True)
    snapshot.add_argument("--project", type=Path)
    snapshot.add_argument("--workspace-root", type=Path)
    snapshot.add_argument(
        "--refresh-hardware",
        action="store_true",
        help="force a fresh bounded sensor probe instead of using the derived TTL cache",
    )
    snapshot.add_argument("--pretty", action="store_true")
    readiness = commands.add_parser("readiness")
    readiness.add_argument("--source-root", type=Path, required=True)
    readiness.add_argument("--project", type=Path)
    readiness.add_argument("--workspace-root", type=Path)
    readiness.add_argument("--pretty", action="store_true")
    catalog = commands.add_parser("catalog")
    catalog.add_argument("--source-root", type=Path, required=True)
    catalog.add_argument(
        "--kind",
        choices=(
            "skills",
            "preserved-skills",
            "microsoft-skills",
            "tools",
            "agents",
            "workflows",
            "graph",
            "enterprise-skills",
            "enterprise-agents",
            "enterprise-workflows",
            "enterprise-integrations",
            "enterprise-models",
        ),
        required=True,
    )
    catalog.add_argument("--query", default="")
    catalog.add_argument("--status", default="")
    catalog.add_argument("--offset", type=int, default=0)
    catalog.add_argument("--limit", type=int, default=50)
    catalog.add_argument("--sort", default="label")
    catalog.add_argument("--pretty", action="store_true")
    graph = commands.add_parser("graph")
    graph.add_argument("--source-root", type=Path, required=True)
    graph.add_argument("--project", type=Path)
    graph.add_argument(
        "--view", choices=("capabilities", "repository"), default="capabilities"
    )
    graph.add_argument("--node", default="")
    graph.add_argument("--query", default="")
    graph.add_argument("--relation", default="")
    graph.add_argument(
        "--direction", choices=("incoming", "outgoing", "both"), default="both"
    )
    graph.add_argument(
        "--mode",
        choices=(
            "full",
            "overview",
            "neighborhood",
            "path",
            "impact",
            "dependencies",
            "dependents",
            "hubs",
            "orphans",
            "provenance",
        ),
        default="neighborhood",
    )
    graph.add_argument("--target", default="")
    graph.add_argument("--cluster", default="")
    graph.add_argument("--kind", default="")
    graph.add_argument("--status", default="")
    graph.add_argument("--offset", type=int, default=0)
    graph.add_argument("--edge-offset", type=int, default=0)
    graph.add_argument("--depth", type=int, default=1)
    graph.add_argument("--max-nodes", type=int, default=24)
    graph.add_argument("--max-edges", type=int, default=48)
    graph.add_argument("--pretty", action="store_true")
    memory = commands.add_parser("memory")
    memory.add_argument("--source-root", type=Path, required=True)
    memory.add_argument("--workspace-root", type=Path, required=True)
    memory.add_argument("--query", default="")
    memory.add_argument("--offset", type=int, default=0)
    memory.add_argument("--limit", type=int, default=60)
    memory.add_argument("--status", default="")
    memory.add_argument("--project-id", default="")
    memory.add_argument("--source", default="")
    memory.add_argument("--pretty", action="store_true")
    punch_cards = commands.add_parser("operational-cards")
    punch_cards.add_argument("--source-root", type=Path, required=True)
    punch_cards.add_argument("--query", default="")
    punch_cards.add_argument("--state", default="")
    punch_cards.add_argument("--severity", default="")
    punch_cards.add_argument("--surface", default="")
    punch_cards.add_argument("--owner", default="")
    punch_cards.add_argument("--evidence-gap", action="store_true")
    punch_cards.add_argument("--offset", type=int, default=0)
    punch_cards.add_argument("--limit", type=int, default=50)
    punch_cards.add_argument("--pretty", action="store_true")
    punch_card = commands.add_parser("operational-card")
    punch_card.add_argument("--source-root", type=Path, required=True)
    punch_card.add_argument("--gap-id", required=True)
    punch_card.add_argument("--pretty", action="store_true")
    punch_inventory = commands.add_parser("operational-inventory")
    punch_inventory.add_argument("--source-root", type=Path, required=True)
    punch_inventory.add_argument("--surface-id", default="")
    punch_inventory.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "snapshot":
        result = build_snapshot(
            args.source_root,
            project=args.project,
            workspace_root=args.workspace_root,
            refresh_hardware=args.refresh_hardware,
        )
    elif args.command == "readiness":
        result = build_snapshot(
            args.source_root, project=args.project, workspace_root=args.workspace_root
        )["readiness"]
    elif args.command == "catalog":
        result = query_catalog(
            args.source_root,
            args.kind,
            query=args.query,
            status=args.status,
            offset=args.offset,
            limit=args.limit,
            sort=args.sort,
        )
    elif args.command == "graph":
        result = query_graph(
            args.source_root,
            project=args.project,
            view=args.view,
            node=args.node,
            target=args.target,
            query=args.query,
            relation=args.relation,
            direction=args.direction,
            mode=args.mode,
            cluster=args.cluster,
            kind=args.kind,
            status=args.status,
            offset=args.offset,
            edge_offset=args.edge_offset,
            depth=args.depth,
            max_nodes=args.max_nodes,
            max_edges=args.max_edges,
        )
    elif args.command == "memory":
        result = query_canonical_memory(
            args.workspace_root,
            query=args.query,
            offset=args.offset,
            limit=args.limit,
            status=args.status,
            project_id=args.project_id,
            source=args.source,
        )
    elif args.command == "operational-cards":
        result = _operational_punch_cards(
            args.source_root,
            query=args.query,
            state=args.state,
            severity=args.severity,
            surface=args.surface,
            owner=args.owner,
            evidence_gap=args.evidence_gap,
            offset=args.offset,
            limit=args.limit,
        )
    elif args.command == "operational-card":
        result = query_operational_punch_card(args.source_root, args.gap_id)
    else:
        result = query_operational_inventory(args.source_root, surface_id=args.surface_id)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
