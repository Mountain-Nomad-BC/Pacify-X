"""Unified, read-mostly PX Doctor diagnostics with optional WAL retention."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from .authoritative_json import load_state_classifications
from .contracts import validate_contract_corpus
from .health_model import assess_health_report, validate_health_registry
from .operation_coverage import reconcile_operation_coverage
from .operational_visibility import validate_route_registry
from .platform_support import runtime_python_status
from .provider_budget import load_budget_policy
from .provider_gateway import load_provider_registry, scan_direct_provider_routes
from .recovery import RecoveryConfiguration, RecoveryCoordinator
from .source_coverage import validate_source_coverage
from .wal_transaction import JsonArtifact, JsonWal


SCHEMA_VERSION = "px.doctor-report/1.0"
RECEIPT_SCHEMA_VERSION = "px.doctor-receipt/1.0"
STATES = ("healthy", "degraded", "blocked")
PRECEDENCE = ("blocked", "degraded", "healthy")
DEFAULT_RECEIPT_DIR = Path(".engineering-bootstrap/diagnostics")
MAX_PROBE_BYTES = 256 * 1024
# A PX checkout can legitimately contain thousands of preserved canonical-skill
# files.  Keep the probe bounded, but do not misclassify that normal inventory as
# unreadable merely because its NUL-delimited path list exceeds one MiB.
MAX_GIT_STATUS_BYTES = 16 * 1024 * 1024
ENVIRONMENT_EVIDENCE_MAX_AGE_SECONDS = 86_400


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _section(
    state: str,
    summary: str,
    *,
    details: Mapping[str, object] | None = None,
    remediation: str,
    deep_link: str,
) -> dict[str, object]:
    if state not in STATES:
        raise ValueError(f"invalid doctor state: {state}")
    return {
        "state": state,
        "summary": summary,
        "details": dict(details or {}),
        "remediation": {"summary": remediation, "deep_link": deep_link},
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_PROBE_BYTES:
        raise ValueError("diagnostic JSON is absent or exceeds its byte bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("diagnostic JSON must be an object")
    return value


def _git_probe(root: Path) -> dict[str, object]:
    executable = shutil.which("git")
    if executable is None:
        return _section(
            "degraded",
            "Git executable was not detected.",
            details={"available": False},
            remediation="Install Git or select a runtime with Git on PATH.",
            deep_link="px://doctor/git",
        )

    def run(*arguments: str, byte_limit: int = MAX_PROBE_BYTES) -> str:
        result = subprocess.run(
            [executable, "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError("Git metadata probe failed")
        output = result.stdout
        if len(output.encode("utf-8", errors="replace")) > byte_limit:
            raise RuntimeError("Git metadata probe exceeded its byte bound")
        return output.strip()

    try:
        inside = run("rev-parse", "--is-inside-work-tree") == "true"
        head = run("rev-parse", "HEAD") if inside else None
        branch = run("branch", "--show-current") if inside else None
        status = run("status", "--porcelain=v1", "--untracked-files=no")
        tracked_change_count = len(
            [line for line in status.splitlines() if line.strip()]
        )
        untracked = run(
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            byte_limit=MAX_GIT_STATUS_BYTES,
        )
        untracked_file_count = len([item for item in untracked.split("\0") if item])
        changed_count = tracked_change_count + untracked_file_count
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return _section(
            "blocked",
            "Git is present but repository metadata could not be inspected.",
            details={"available": True, "repository": False},
            remediation="Repair repository metadata or inspect Git manually.",
            deep_link="px://doctor/git",
        )
    return _section(
        "degraded" if changed_count else "healthy",
        (
            "Git repository is readable with "
            f"{tracked_change_count} tracked change(s) and "
            f"{untracked_file_count} untracked file(s)."
            if changed_count
            else "Git repository is readable and tracked/untracked files are clean."
        ),
        details={
            "available": True,
            "repository": inside,
            "head": head,
            "branch": branch or "detached",
            "dirty": bool(changed_count),
            "tracked_change_count": tracked_change_count,
            "untracked_file_count": untracked_file_count,
            "untracked_files_examined": True,
            "untracked_count_truncated": False,
        },
        remediation="Review tracked and untracked changes before release certification.",
        deep_link="px://doctor/git",
    )


def _evidence_age(
    value: object, evaluated_at: str, *, label: str, max_age_seconds: int
) -> tuple[dict[str, object], list[str]]:
    details: dict[str, object] = {}
    problems: list[str] = []
    try:
        observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        evaluated = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
        if observed.tzinfo is None or evaluated.tzinfo is None:
            raise ValueError("timezone required")
        age_seconds = (evaluated - observed).total_seconds()
        details[f"{label}_age_seconds"] = round(age_seconds, 3)
        details[f"{label}_max_age_seconds"] = max_age_seconds
        details[f"{label}_fresh"] = 0 <= age_seconds <= max_age_seconds
        if age_seconds < -300:
            problems.append(f"{label}_clock_skew")
        elif age_seconds > max_age_seconds:
            problems.append(f"{label}_stale")
    except (TypeError, ValueError):
        details[f"{label}_fresh"] = False
        problems.append(f"{label}_timestamp_invalid")
    return details, problems


def _environment_handoff_probe(
    root: Path,
    *,
    evaluated_at: str,
    max_age_seconds: int = ENVIRONMENT_EVIDENCE_MAX_AGE_SECONDS,
) -> dict[str, object]:
    environment = root / ".engineering-bootstrap" / "environment" / "current.json"
    handoff = root / ".engineering-bootstrap" / "coordination" / "handoff.json"
    details: dict[str, object] = {
        "environment_map_present": environment.is_file(),
        "handoff_present": handoff.is_file(),
        "secret_values_retained": False,
    }
    problems: list[str] = []
    try:
        current = _read_json(environment)
        if current.get("schema_version") not in {
            "px.environment-capability-map/1.0",
            "px.environment-capability-map/2.0",
        }:
            problems.append("environment_schema_unknown")
        details["environment_schema_version"] = current.get("schema_version")
        details["environment_snapshot_hash"] = current.get("snapshot_hash")
        details["environment_generated_utc"] = current.get("generated_utc")
        age, freshness_problems = _evidence_age(
            current.get("generated_utc"),
            evaluated_at,
            label="environment",
            max_age_seconds=max_age_seconds,
        )
        details.update(age)
        problems.extend(freshness_problems)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        problems.append("environment_map_unreadable")
    transfer: dict[str, Any] = {}
    try:
        transfer = _read_json(handoff)
        if not isinstance(transfer.get("schema_version"), str):
            problems.append("handoff_schema_unknown")
        if not isinstance(transfer.get("verified_state_hash"), str):
            problems.append("handoff_state_unverified")
        details["handoff_schema_version"] = transfer.get("schema_version")
        details["handoff_generated_utc"] = transfer.get("generated_utc")
        details["handoff_phase"] = transfer.get("phase")
        details["handoff_state_hash_present"] = isinstance(
            transfer.get("verified_state_hash"), str
        )
        age, freshness_problems = _evidence_age(
            transfer.get("generated_utc"),
            evaluated_at,
            label="handoff",
            max_age_seconds=max_age_seconds,
        )
        details.update(age)
        problems.extend(freshness_problems)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        problems.append("handoff_unreadable")
    coordination = root / ".engineering-bootstrap" / "coordination" / "state.json"
    if coordination.is_file() and transfer:
        try:
            coordination_state = _read_json(coordination)
            state_hash = coordination_state.get("state_hash")
            state_current = (
                isinstance(state_hash, str)
                and bool(state_hash)
                and transfer.get("verified_state_hash") == state_hash
            )
            details["handoff_state_current"] = state_current
            if state_current:
                problems = [
                    problem for problem in problems if problem != "handoff_stale"
                ]
                details["handoff_fresh"] = True
                details["handoff_freshness_basis"] = "verified_state_hash_match"
            elif isinstance(state_hash, str) and state_hash:
                problems.append("handoff_state_stale")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            problems.append("coordination_state_unreadable")
    else:
        details["handoff_state_current"] = None
    details["problems"] = problems
    fatal = any(problem.endswith("_unreadable") for problem in problems)
    state = "healthy" if not problems else "blocked" if fatal else "degraded"
    return _section(
        state,
        "Environment discovery and coordination handoff are readable and current."
        if not problems
        else f"Environment or handoff has {len(problems)} diagnostic problem(s).",
        details=details,
        remediation="Refresh environment discovery and regenerate the coordination handoff.",
        deep_link="px://doctor/environment-handoff",
    )


def _provider_probe(root: Path) -> dict[str, object]:
    try:
        adapters = load_provider_registry(root)
        budgets = load_budget_policy(root)
        bypass = scan_direct_provider_routes(root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return _section(
            "blocked",
            "Provider or budget authority is invalid.",
            details={"error_class": type(error).__name__},
            remediation="Repair provider registry, budget policy, or gateway bypasses.",
            deep_link="px://health/providers",
        )
    adapter_rows = adapters["adapters"]
    budget_rows = budgets["budgets"]
    ready = [
        row for row in adapter_rows if row["admitted"] and row["status"] == "ready"
    ]
    enabled = [row for row in budget_rows if row["enabled"]]
    violations = list(bypass.get("violations", ()))
    state = "blocked" if violations else "healthy" if ready and enabled else "degraded"
    return _section(
        state,
        (
            "Provider gateway, admission, and budgets are ready."
            if state == "healthy"
            else "Provider execution remains default-deny or has gateway bypass findings."
        ),
        details={
            "adapter_count": len(adapter_rows),
            "ready_adapter_count": len(ready),
            "budget_count": len(budget_rows),
            "enabled_budget_count": len(enabled),
            "gateway_bypass_count": len(violations),
            "default_deny": not bool(ready and enabled),
        },
        remediation="Admit an exact adapter and enabled budget, then clear gateway bypass findings.",
        deep_link="px://health/providers",
    )


def _coverage_probe(
    root: Path,
    health_snapshot: Path | Mapping[str, object] | None,
    max_age_seconds: int,
) -> dict[str, object]:
    registry = validate_route_registry(root)
    report = reconcile_operation_coverage(
        root,
        health_snapshot=health_snapshot,
        max_age_seconds=max_age_seconds,
    )
    state = (
        "blocked"
        if not registry.get("valid") or not report.get("valid")
        else "healthy"
        if report.get("certifiable")
        else "degraded"
    )
    return _section(
        state,
        (
            "Every declared route has current, evidence-bound coverage."
            if report.get("certifiable")
            else f"{len(report.get('blockers', ()))} route coverage blocker(s) remain."
        ),
        details={
            "route_count": report.get("route_count", 0),
            "classified_route_count": report.get("classified_route_count", 0),
            "tiers": report.get("tiers", {}),
            "certifiable": report.get("certifiable", False),
            "blind_spots": report.get("blind_spots", []),
            "blockers": report.get("blockers", []),
            "errors": report.get("errors", []),
            "health_snapshot_sha256": report.get("health_snapshot_sha256"),
        },
        remediation="Supply fresh observer health receipts and close declared Tier D blind spots.",
        deep_link="px://doctor/coverage",
    )


def _integrity_probe(root: Path) -> dict[str, object]:
    checks: dict[str, dict[str, object]] = {}
    operations = (
        ("contracts", validate_contract_corpus),
        ("health_registry", validate_health_registry),
        ("route_registry", validate_route_registry),
        ("source_coverage", validate_source_coverage),
    )
    for name, operation in operations:
        try:
            result = operation(root)
            checks[name] = {
                "valid": bool(result.get("valid")),
                "errors": list(result.get("errors", ())),
            }
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            checks[name] = {
                "valid": False,
                "errors": [f"{type(error).__name__}: bounded integrity probe failed"],
            }
    try:
        state_classes = load_state_classifications(root)
        checks["state_authority"] = {
            "valid": bool(state_classes),
            "errors": [] if state_classes else ["state authority registry is empty"],
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        checks["state_authority"] = {
            "valid": False,
            "errors": [f"{type(error).__name__}: state authority probe failed"],
        }
    try:
        from .test_profiles import group_status, section_status

        sections = section_status(root)
        groups = group_status(root)
        checks["current_section_gates"] = {
            "valid": bool(sections.get("valid")),
            "errors": [
                f"stale section: {row['section']}"
                for row in sections.get("sections", ())
                if not row.get("current")
            ],
        }
        release_groups = {
            row["group"]: row
            for row in groups.get("groups", ())
            if row.get("group") in {"release-audit", "structural-adversarial", "derived-integrity"}
        }
        checks["canonical_release_and_structural_gates"] = {
            "valid": len(release_groups) == 3 and all(row.get("current") for row in release_groups.values()),
            "errors": [
                f"stale or missing release gate: {name}"
                for name in ("release-audit", "structural-adversarial", "derived-integrity")
                if not release_groups.get(name, {}).get("current")
            ],
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        checks["canonical_release_and_structural_gates"] = {
            "valid": False,
            "errors": [f"{type(error).__name__}: release gate status unavailable"],
        }
    errors = [
        f"{name}: {error}"
        for name, check in checks.items()
        for error in check["errors"]
    ]
    valid = all(check["valid"] for check in checks.values())
    return _section(
        "healthy" if valid else "blocked",
        "Bounded control-plane and current release-gate integrity checks passed."
        if valid
        else f"Control-plane integrity has {len(errors)} error(s).",
        details={
            "valid": valid,
            "scope": "bounded_control_plane_plus_current_release_gate_status; not a substitute for certification",
            "checks": checks,
            "errors": errors,
        },
        remediation="Run runtime validation and repair the named integrity categories.",
        deep_link="px://health/runtime",
    )


def _transaction_probe(root: Path) -> dict[str, object]:
    known_wal_roots = tuple(
        candidate
        for candidate in (
            root / ".engineering-bootstrap" / "operations" / "wal",
            root / ".engineering-bootstrap" / "provider-budget" / "wal",
            root / ".engineering-bootstrap" / "resource-lifecycle" / "wal",
            root / ".engineering-bootstrap" / "coordination" / "wal",
            root / ".engineering-bootstrap" / "diagnostics" / "wal",
        )
        if candidate.is_dir()
    )
    recovery = RecoveryCoordinator(
        RecoveryConfiguration(
            root,
            wal_targets=tuple((path, root) for path in known_wal_roots),
        )
    ).reconcile(apply=False)
    recovery_state = str(recovery["status"])
    state = recovery_state if recovery_state in STATES else "blocked"
    if state == "healthy" and not known_wal_roots:
        state = "degraded"
    return _section(
        state,
        (
            recovery["human_summary"]
            if known_wal_roots
            else "Recovery checks passed; no active transaction WAL was discovered."
        ),
        details={
            "wal_configured_count": len(known_wal_roots),
            "wal_roots": [
                path.relative_to(root).as_posix() for path in known_wal_roots
            ],
            "recovery": recovery,
        },
        remediation="Inspect retained WAL transactions and run recovery doctor before resuming writes.",
        deep_link="px://doctor/transactions",
    )


def _runtime_extension_probe(
    root: Path,
    integrity: Mapping[str, object],
    health_claims: Sequence[Mapping[str, object]] | None,
) -> tuple[dict[str, object], dict[str, object]]:
    python = runtime_python_status(root)
    runtime_state = (
        "healthy"
        if python["supported"] and integrity.get("state") == "healthy"
        else "blocked"
        if not python["supported"]
        else "degraded"
    )
    runtime = _section(
        runtime_state,
        "Runtime control plane is supported and passed integrity checks."
        if runtime_state == "healthy"
        else "Runtime support or integrity is not release-ready.",
        details={"python_support": python},
        remediation="Use a supported Python runtime and clear runtime validation failures.",
        deep_link="px://health/runtime",
    )
    extension_claim = None
    for claim in health_claims or ():
        if claim.get("surface_id") == "extension.activity-projection":
            extension_claim = claim
            break
    if extension_claim is None:
        extension = _section(
            "degraded",
            "No current extension-host health claim was supplied.",
            details={"health_claim_present": False, "authority": "unobserved"},
            remediation="Export a current extension listener-health claim and rerun PX Doctor.",
            deep_link="px://health/extension",
        )
    else:
        assessed = assess_health_report(
            root,
            [extension_claim],
            require_complete=False,
        )["records"][0]
        mapped = (
            "healthy"
            if assessed["state"] == "healthy"
            else "blocked"
            if assessed["state"] == "blocked"
            else "degraded"
        )
        extension = _section(
            mapped,
            f"Extension activity projection reports {assessed['state']}.",
            details={"health_claim_present": True, "record": assessed},
            remediation=assessed["remediation"]["summary"],
            deep_link=assessed["remediation"]["deep_link"],
        )
    return runtime, extension


def compose_doctor_report(
    sections: Mapping[str, Mapping[str, object]], *, evaluated_at: str
) -> dict[str, object]:
    """Compose a strict report from already collected or fixture-backed sections."""
    required = {
        "coverage",
        "integrity",
        "transactions_wal",
        "providers_budgets",
        "git",
        "environment_handoff",
        "runtime",
        "extension",
    }
    if set(sections) != required:
        raise ValueError(
            f"doctor section mismatch: missing={sorted(required - set(sections))}, "
            f"unexpected={sorted(set(sections) - required)}"
        )
    normalized = {key: dict(value) for key, value in sections.items()}
    for name, value in normalized.items():
        if value.get("state") not in STATES:
            raise ValueError(f"{name} has an invalid state")
        if not isinstance(value.get("remediation"), Mapping):
            raise ValueError(f"{name} has no remediation")
        link = value["remediation"].get("deep_link")
        if not isinstance(link, str) or not link.startswith("px://"):
            raise ValueError(f"{name} remediation deep link is invalid")
    counts = Counter(str(value["state"]) for value in normalized.values())
    overall = next(state for state in PRECEDENCE if counts[state])
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "valid": True,
        "operable": overall != "blocked",
        "ready": overall == "healthy",
        "certification_ready": overall == "healthy",
        "overall_state": overall,
        "evaluated_at": evaluated_at,
        "summary": {state: counts[state] for state in STATES},
        "sections": normalized,
    }
    report["report_sha256"] = _sha(report)
    return report


def retain_doctor_receipt(
    root: Path, report: Mapping[str, object], receipt_dir: Path = DEFAULT_RECEIPT_DIR
) -> dict[str, object]:
    """Retain an immutable-named diagnostic receipt through the JSON WAL."""
    root = root.resolve()
    directory = receipt_dir if receipt_dir.is_absolute() else root / receipt_dir
    directory = directory.resolve()
    if not _inside(directory, root) or directory == root:
        raise ValueError("doctor receipt directory must remain below the project root")
    report_hash = str(report.get("report_sha256", ""))
    if len(report_hash) != 64:
        raise ValueError("doctor report hash is invalid")
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "created_at": str(report["evaluated_at"]),
        "report_sha256": report_hash,
        "overall_state": report["overall_state"],
        "report": dict(report),
    }
    receipt["receipt_sha256"] = _sha(receipt)
    target = directory / "receipts" / f"{report_hash}.json"
    wal = JsonWal(directory / "wal", root)
    transaction = wal.commit(
        (JsonArtifact("receipt", target, receipt),),
        transaction_id=f"px-doctor-{report_hash[:24]}",
    )
    return {
        "path": target.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "report_sha256": report_hash,
        "wal_transaction_id": transaction["transaction_id"],
    }


def run_px_doctor(
    root: Path,
    *,
    health_snapshot: Path | Mapping[str, object] | None = None,
    health_claims: Sequence[Mapping[str, object]] | None = None,
    max_age_seconds: int = 300,
    receipt_dir: Path | None = None,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    """Inspect the PX stack and optionally retain a hash-bound receipt."""
    root = root.resolve()
    timestamp = evaluated_at or _now()
    integrity = _integrity_probe(root)
    runtime, extension = _runtime_extension_probe(root, integrity, health_claims)
    sections = {
        "coverage": _coverage_probe(root, health_snapshot, max_age_seconds),
        "integrity": integrity,
        "transactions_wal": _transaction_probe(root),
        "providers_budgets": _provider_probe(root),
        "git": _git_probe(root),
        "environment_handoff": _environment_handoff_probe(
            root, evaluated_at=timestamp
        ),
        "runtime": runtime,
        "extension": extension,
    }
    report = compose_doctor_report(sections, evaluated_at=timestamp)
    if receipt_dir is not None:
        report["diagnostic_receipt"] = retain_doctor_receipt(root, report, receipt_dir)
    return report


def render_doctor_human(report: Mapping[str, object]) -> str:
    """Render the same machine report as a compact operator-readable view."""
    lines = [
        f"PX Doctor: {str(report['overall_state']).upper()}",
        f"Evaluated: {report['evaluated_at']}",
        "",
    ]
    sections = report["sections"]
    assert isinstance(sections, Mapping)
    for name, value in sections.items():
        assert isinstance(value, Mapping)
        remediation = value["remediation"]
        assert isinstance(remediation, Mapping)
        lines.extend(
            (
                f"[{str(value['state']).upper()}] {name.replace('_', ' ')}",
                f"  {value['summary']}",
                f"  Next: {remediation['summary']}",
                f"  Open: {remediation['deep_link']}",
            )
        )
    receipt = report.get("diagnostic_receipt")
    if isinstance(receipt, Mapping):
        lines.extend(("", f"Receipt: {receipt['path']} ({receipt['sha256']})"))
    return "\n".join(lines)
