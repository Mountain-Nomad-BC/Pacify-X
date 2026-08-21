"""Build a fresh hash-bound health snapshot for active Tier A/B routes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


INSTALLED_LISTENER_RECEIPT = (
    "extension/evidence/installed-vsix-smoke.json"
    if sys.platform == "win32"
    else "extension/evidence/installed-vsix-smoke-linux.json"
)


ROUTES = (
    (
        "extension.vscode-listener",
        "observer",
        INSTALLED_LISTENER_RECEIPT,
    ),
    (
        "provider.remote-model",
        "mediator",
        "registry/provider_adapters.json",
    ),
    (
        "provider.local-model",
        "mediator",
        ".engineering-bootstrap/provider-budget/ledger.json",
    ),
    (
        "runtime.package-environment",
        "observer",
        ".engineering-bootstrap/environment/current.json",
    ),
)


def _receipt_health(root: Path, route_id: str, payload: object) -> tuple[str, str | None]:
    """Derive route health from receipt claims; receipt presence is not health."""
    if route_id == "provider.remote-model":
        adapters = payload.get("adapters", []) if isinstance(payload, dict) else []
        ready = any(
            isinstance(row, dict)
            and row.get("provider_id") == "openai"
            and row.get("admitted") is True
            and row.get("status") == "ready"
            for row in adapters
        )
        return ("healthy", None) if ready else ("unconfigured", "remote provider remains default-off")
    if route_id == "provider.local-model":
        try:
            adapters = json.loads((root / "registry/provider_adapters.json").read_text(encoding="utf-8"))["adapters"]
            budgets = json.loads((root / "registry/provider_budget_policy.json").read_text(encoding="utf-8"))["budgets"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return "unknown", "local provider authority is unreadable"
        adapter_ready = any(
            isinstance(row, dict)
            and row.get("provider_id") == "ollama"
            and row.get("admitted") is True
            and row.get("status") == "ready"
            for row in adapters
        )
        budget_ready = any(
            isinstance(row, dict)
            and row.get("provider_id") == "ollama"
            and row.get("enabled") is True
            for row in budgets
        )
        invocations = payload.get("invocations", {}) if isinstance(payload, dict) else {}
        exercised = any(
            isinstance(row, dict)
            and row.get("provider_id") == "ollama"
            and row.get("state") == "settled"
            and isinstance(row.get("settlement"), dict)
            and row["settlement"].get("outcome") == "success"
            and row["settlement"].get("policy_overrun") is False
            for row in invocations.values()
        ) if isinstance(invocations, dict) else False
        ready = adapter_ready and budget_ready and exercised
        return ("healthy", None) if ready else ("unconfigured", "local adapter, budget, or successful smoke is absent")
    if route_id == "runtime.package-environment":
        ready = (
            isinstance(payload, dict)
            and payload.get("schema_version") == "px.environment-capability-map/2.0"
            and isinstance(payload.get("snapshot_hash"), str)
            and payload.get("boundaries", {}).get("credential_values_persisted") is False
        )
        return ("healthy", None) if ready else ("unknown", "canonical environment inventory is invalid")
    if route_id != "extension.vscode-listener":
        return "unknown", "route health authority is unavailable"
    if not isinstance(payload, dict):
        return "unknown", "listener receipt is not an object"
    listener = payload.get("listener_health")
    if not isinstance(listener, dict):
        host = payload.get("host")
        listener = host.get("listener_health") if isinstance(host, dict) else None
    if not isinstance(listener, dict):
        return "unknown", "listener_health is absent"
    status = str(listener.get("status") or "unknown")
    coverage_complete = listener.get("coverage_complete") is True
    if status == "healthy" and coverage_complete:
        return "healthy", None
    if status == "degraded":
        return "degraded", "listener receipt reports degraded health"
    return "unknown", f"listener receipt reports {status} or incomplete coverage"


def _extension_health_claim(payload: object) -> dict[str, object]:
    """Project the exact installed-host receipt into the canonical health facts."""
    if not isinstance(payload, dict):
        raise ValueError("installed extension receipt is not an object")
    host = payload.get("host")
    process = payload.get("process_lifecycle")
    artifact = payload.get("artifact")
    if not all(isinstance(item, dict) for item in (host, process, artifact)):
        raise ValueError("installed extension receipt envelope is incomplete")
    assert isinstance(host, dict) and isinstance(process, dict) and isinstance(artifact, dict)
    listener = host.get("listener_health")
    if not isinstance(listener, dict):
        raise ValueError("installed extension listener health is absent")
    observed_at = str(process.get("finished_utc") or "")
    if not observed_at:
        raise ValueError("installed extension completion time is absent")
    configured = bool(artifact.get("name"))
    detected = bool(host.get("vscode_version"))
    connected = payload.get("engine_connected") is True
    authoritative = (
        connected
        and listener.get("canonical_bus_connected") is True
        and process.get("process_tree_closed_verified") is True
        and artifact.get("unchanged") is True
    )
    ready = (
        configured
        and detected
        and connected
        and authoritative
        and listener.get("status") == "healthy"
        and listener.get("coverage_complete") is True
        and int(listener.get("dropped_events") or 0) == 0
    )
    degradation = [] if ready else ["extension.listener-coverage-incomplete"]
    blockers = []
    if artifact.get("unchanged") is not True:
        blockers.append("extension.artifact-mutated")
    if process.get("process_tree_closed_verified") is not True:
        blockers.append("extension.host-process-unclosed")
    return {
        "surface_id": "extension.activity-projection",
        "lifecycle": {
            "configured": configured,
            "detected": detected,
            "connected": connected,
            "authoritative": authoritative,
            "ready": ready,
        },
        "observed_at": observed_at,
        "last_success": observed_at if ready else None,
        "last_failure": None,
        "degradation": degradation,
        "blockers": blockers,
    }


def build(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    observed_at = datetime.now(timezone.utc).isoformat()
    states = []
    for route_id, kind, relative in ROUTES:
        receipt = root / relative
        if not receipt.is_file():
            raise FileNotFoundError(f"health receipt missing: {relative}")
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = None
        health, limitation = _receipt_health(root, route_id, payload)
        states.append(
            {
                "route_id": route_id,
                "kind": kind,
                "health": health,
                "observed_at": observed_at,
                "receipt_path": relative,
                "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                "limitation": limitation,
            }
        )
    return {
        "schema_version": "px.operation-coverage-health/1.0",
        "route_states": states,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage-output", type=Path)
    parser.add_argument("--health-claims-output", type=Path)
    parser.add_argument(
        "--evidence-dir", type=Path, default=Path("evidence/punch-cards")
    )
    parser.add_argument("--max-age-seconds", type=int, default=600)
    args = parser.parse_args()
    payload = build(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    result: dict[str, object] = {
        "valid": True,
        "route_states": len(payload["route_states"]),
        "output": output.as_posix(),
    }
    if args.health_claims_output is not None:
        installed = args.root / INSTALLED_LISTENER_RECEIPT
        installed_payload = json.loads(installed.read_text(encoding="utf-8"))
        claims_output = (
            args.health_claims_output
            if args.health_claims_output.is_absolute()
            else args.root / args.health_claims_output
        )
        claims_output.parent.mkdir(parents=True, exist_ok=True)
        claims_output.write_text(
            json.dumps({"claims": [_extension_health_claim(installed_payload)]}, indent=2)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        result["health_claims_output"] = claims_output.as_posix()
    if args.coverage_output is not None:
        from runtime.operation_coverage import reconcile_operation_coverage

        coverage = reconcile_operation_coverage(
            args.root,
            health_snapshot=output,
            evidence_dir=args.evidence_dir,
            max_age_seconds=max(1, args.max_age_seconds),
        )
        coverage_output = (
            args.coverage_output
            if args.coverage_output.is_absolute()
            else args.root / args.coverage_output
        )
        coverage_output.parent.mkdir(parents=True, exist_ok=True)
        coverage_output.write_text(
            json.dumps(coverage, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        result.update(
            {
                "valid": bool(coverage.get("valid")),
                "certifiable": bool(coverage.get("certifiable")),
                "coverage_output": coverage_output.as_posix(),
                "coverage_blockers": len(coverage.get("blockers", [])),
            }
        )
    print(json.dumps(result))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
