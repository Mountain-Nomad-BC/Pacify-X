"""Initialize missing control gaps and import exact attempted observations.

Discovery/disposition is first-initialization work.  Later runs may attach a
typed observation only when an explicit current-source walk attempted that
exact control.  Inventory enumeration never substitutes for examination.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import (
    CHAIN_STAGES,
    MAX_BATCH_EVENTS,
    append_events,
    control_disposition_sha256,
    read_snapshot,
)


INVENTORY = "registry/operational_surface_inventory.json"
LIVE_WALK = "evidence/operational-ui-walk-punch-ledger-20260816-r2/receipt.json"
ACTOR = "codex-primary:lossless-control-reconciliation"
SHA256_RE = re.compile(r"[a-f0-9]{64}")
COMPLETE_TERMINAL_DISPOSITIONS = {
    "operational", "interaction_complete", "observed_complete"
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ordinal(value: str) -> int:
    match = re.fullmatch(r"PX-(?:OS|GAP)-(\d+)", value)
    return int(match.group(1)) if match else 0


def _classification(kind: str) -> str:
    return {
        "editor": "editor",
        "persistence": "persistence",
        "reload_reopen": "revisioning",
        "failure_recovery": "recovery",
        "lifecycle": "runtime",
        "agent_operation": "runtime",
        "workflow_operation": "runtime",
        "skill_plugin_binding": "integration",
        "command": "integration",
    }.get(kind, "UI")


def _chain(control_id: str) -> dict[str, dict[str, object]]:
    detail = (
        f"{control_id} is present in the typed source inventory, but this stage "
        "has not been exercised against a host whose installed assets match the current source."
    )
    return {
        stage: {"state": "unknown", "detail": detail, "evidence": []}
        for stage in CHAIN_STAGES
    }


def _batches(entries: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    return [entries[index:index + MAX_BATCH_EVENTS] for index in range(0, len(entries), MAX_BATCH_EVENTS)]


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("walk receipt must remain inside the repository") from error
    return resolved


def _load_walk_receipt(root: Path, value: str | Path) -> tuple[dict[str, object], str]:
    target = _inside(root, root / value if not Path(value).is_absolute() else Path(value))
    receipt = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("walk receipt must be a JSON object")
    return receipt, target.relative_to(root).as_posix()


def _positive_current_source(receipt: dict[str, object]) -> bool:
    status = receipt.get("status_truth")
    source = status.get("source_identity") if isinstance(status, dict) else None
    state = str(source.get("state") or "") if isinstance(source, dict) else ""
    return receipt.get("host_source_mismatch") is False and state in {
        "match", "reported_match", "verified"
    }


def _observation_chain(record: dict[str, object], reference: str) -> dict[str, dict[str, object]]:
    raw_stages = record.get("stages")
    if not isinstance(raw_stages, list):
        raise ValueError("attempted control record must contain stages")
    by_stage = {
        str(item.get("stage")): item
        for item in raw_stages
        if isinstance(item, dict)
    }
    if set(by_stage) != set(CHAIN_STAGES):
        raise ValueError("attempted control record must contain every interaction stage exactly once")
    result: dict[str, dict[str, object]] = {}
    control_id = str(record.get("control_id") or "")
    for stage in CHAIN_STAGES:
        item = by_stage[stage]
        status = str(item.get("status") or "unknown")
        state = {
            "observed": "present",
            "present": "present",
            "partial": "partial",
            "not_applicable": "not_applicable",
            "not_observed": "missing",
        }.get(status, "unknown")
        detail = str(item.get("evidence") or item.get("reason") or status).strip()
        result[stage] = {
            "state": state,
            "detail": detail or f"Walker recorded {status} for {stage}.",
            "evidence": [f"{reference}#control={control_id}&stage={stage}"],
        }
    return result


def _typed_observation(
    receipt: dict[str, object], record: dict[str, object], reference: str,
    source_sha256: str,
) -> dict[str, object] | None:
    if record.get("attempted") is not True:
        return None
    chain = _observation_chain(record, reference)
    complete = all(
        item["state"] in {"present", "not_applicable"}
        for item in chain.values()
    )
    terminal = str(record.get("terminal_disposition") or "")
    outcome = "operational" if complete and terminal in COMPLETE_TERMINAL_DISPOSITIONS else "observed_only"
    return {
        "schema_version": "px.control-observation/1.0",
        "outcome": outcome,
        "authority": str(record.get("authority") or receipt.get("authority") or "current-source operational walk"),
        "observed_at": str(record.get("observed_at") or receipt.get("observed_at") or ""),
        "source_identity": {
            "kind": "px.current-source-control-manifest/1.0",
            "source_sha256": source_sha256,
            "current_source": True,
            "host_source_mismatch": False,
        },
        "rendered": bool(record.get("rendered")),
        "attempted": True,
        "interaction_chain": chain,
    }


def plan_observation_revisions(
    snapshot: dict[str, object], receipt: dict[str, object], reference: str,
) -> tuple[list[dict[str, object]], int]:
    if not _positive_current_source(receipt):
        raise ValueError("walk receipt lacks positive current-source host identity")
    chain = receipt.get("control_chains")
    if not isinstance(chain, dict) or chain.get("schema_version") != "px.operational-ui-control-chain/1.0":
        raise ValueError("walk receipt control-chain schema is invalid")
    inventory = chain.get("inventory")
    records = chain.get("controls")
    if not isinstance(inventory, dict) or not isinstance(records, list):
        raise ValueError("walk receipt control-chain denominator is missing")
    source_sha256 = str(inventory.get("sha256") or "").lower()
    if not SHA256_RE.fullmatch(source_sha256):
        raise ValueError("walk receipt current-source manifest hash is invalid")
    surfaces = snapshot.get("surfaces")
    if not isinstance(surfaces, dict):
        raise ValueError("ledger snapshot surfaces are missing")
    expected_count = sum(len(surface.get("known_controls", [])) for surface in surfaces.values())
    identifiers = [str(record.get("control_id") or "") for record in records if isinstance(record, dict)]
    if (
        len(records) != expected_count
        or inventory.get("control_count") != expected_count
        or len(set(identifiers)) != expected_count
        or any(not identifier for identifier in identifiers)
    ):
        raise ValueError("walk receipt does not match the complete ledger control denominator")
    events: list[dict[str, object]] = []
    attempted = 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("walk receipt control record is invalid")
        observation = _typed_observation(receipt, record, reference, source_sha256)
        if observation is None:
            continue
        attempted += 1
        surface_id = str(record.get("surface_id") or "")
        control_id = str(record.get("control_id") or "")
        surface = surfaces.get(surface_id)
        if not isinstance(surface, dict) or control_id not in surface.get("known_controls", []):
            raise ValueError(f"attempted control is absent from the ledger inventory: {surface_id}/{control_id}")
        current = surface.get("control_dispositions", {}).get(control_id)
        if not isinstance(current, dict):
            raise ValueError(f"attempted control lacks a predecessor disposition: {surface_id}/{control_id}")
        after = "operational" if observation["outcome"] == "operational" else "gap"
        gap_ids = [] if after == "operational" else list(current.get("gap_ids", []))
        if after == "gap" and not gap_ids:
            raise ValueError(f"incomplete attempted control has no retained gap: {surface_id}/{control_id}")
        if (
            current.get("disposition") == after
            and current.get("observation") == observation
            and list(current.get("gap_ids", [])) == gap_ids
        ):
            continue
        events.append({
            "event_type": "control_disposition_revised",
            "actor": ACTOR,
            "timestamp": _now(),
            "payload": {
                "surface_id": surface_id,
                "control_id": control_id,
                "from_disposition": str(current.get("disposition") or ""),
                "to_disposition": after,
                "previous_disposition_sha256": control_disposition_sha256(current),
                "gap_ids": gap_ids,
                "reason": "Attach the exact attempted current-source control observation without promoting incomplete chains.",
                "evidence": [{
                    "reference": reference,
                    "claim": f"The current-source walk attempted {control_id} and retained every chain-stage result.",
                }],
                "observation": observation,
            },
        })
    return events, attempted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--walk-receipt", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    snapshot = read_snapshot(root)
    maximum = max((_ordinal(gap_id) for gap_id in snapshot["cards"]), default=0)
    existing_by_control = {
        str(card.get("control_action")): gap_id
        for gap_id, card in snapshot["cards"].items()
        if card.get("feature") == "unverified-operational-control"
    }
    timestamp = _now()
    discovery_events: list[dict[str, object]] = []
    disposition_events: list[dict[str, object]] = []
    assigned: dict[tuple[str, str], str] = {}

    for surface_id in sorted(snapshot["surfaces"]):
        surface = snapshot["surfaces"][surface_id]
        for control_id in sorted(surface["known_controls"]):
            if control_id in surface["control_dispositions"]:
                continue
            record = surface["control_records"][control_id]
            gap_id = existing_by_control.get(control_id)
            if gap_id is None:
                maximum += 1
                gap_id = f"PX-OS-{maximum:03d}"
                refs = [str(value) for value in record["source_refs"]]
                discovery_events.append({
                    "event_type": "card_discovered",
                    "actor": ACTOR,
                    "timestamp": timestamp,
                    "payload": {
                        "gap_id": gap_id,
                        "parent_surface": surface_id,
                        "feature": "unverified-operational-control",
                        "control_action": control_id,
                        "discovery_source": INVENTORY,
                        "discovered_at": timestamp,
                        "discovered_by": ACTOR,
                        "source_refs": [{"path": ref.split(":", 1)[0], "symbols": [control_id, record["label"]]} for ref in refs],
                        "expected_behavior": (
                            f"{record['label']} completes every applicable interaction-chain stage in the exact current host, "
                            "with explicit evidence for non-applicable boundaries."
                        ),
                        "observed_behavior": (
                            "Only source inventory evidence exists. The available live walk used installed assets that differ "
                            "from current source, so no current operational behavior can be admitted."
                        ),
                        "interaction_chain": _chain(control_id),
                        "classification": _classification(str(record["kind"])),
                        "severity": "medium",
                        "operational_impact": (
                            "This exact control can render or remain declared without proof of validation, authorization, backend "
                            "effect, acknowledgement, persistence, reload, failure, and recovery behavior."
                        ),
                        "dependencies": ["PX-OS-085"],
                        "blockers": ["Exact current-source host identity is not available in the existing live-walk receipt."],
                        "assigned_owner": "unassigned",
                        "tests_required": [
                            f"Exercise {control_id} through every applicable interaction-chain stage in an isolated current-source host.",
                            "Record explicit skipped-stage authority for destructive, billable, installation, or externally owned effects.",
                        ],
                        "completion_evidence": [],
                        "next_action": "Re-exercise this exact control in the current-source operational walk and update every chain stage.",
                        "discovery_evidence": [{
                            "reference": INVENTORY,
                            "claim": f"The typed inventory declares {control_id} on {surface_id} as {record['kind']}.",
                        }, {
                            "reference": LIVE_WALK,
                            "claim": "The retained live walk reports host-assets-differ-from-source, so it cannot establish current-source operation.",
                        }],
                    },
                })
            assigned[(surface_id, control_id)] = gap_id

    # Discover first so every subsequent disposition references an admitted ID.
    if not args.check:
        for batch in _batches(discovery_events):
            append_events(root, batch)

    active = read_snapshot(root) if not args.check else snapshot
    for (surface_id, control_id), gap_id in assigned.items():
        if control_id in active["surfaces"][surface_id]["control_dispositions"]:
            continue
        disposition_events.append({
            "event_type": "control_disposition",
            "actor": ACTOR,
            "timestamp": timestamp,
            "payload": {
                "surface_id": surface_id,
                "control_id": control_id,
                "disposition": "gap",
                "gap_ids": [gap_id],
                "evidence": [{
                    "reference": LIVE_WALK,
                    "claim": "Current-source operation is unproven because the installed-host asset identity differs from source.",
                }, {
                    "reference": INVENTORY,
                    "claim": "The exact control remains retained in the typed inventory and is not skipped.",
                }],
            },
        })
    if not args.check:
        for batch in _batches(disposition_events):
            append_events(root, batch)

    observation_events: list[dict[str, object]] = []
    attempted_controls = 0
    if args.walk_receipt:
        active = read_snapshot(root) if not args.check else snapshot
        receipt, receipt_reference = _load_walk_receipt(root, args.walk_receipt)
        observation_events, attempted_controls = plan_observation_revisions(
            active, receipt, receipt_reference
        )
        if not args.check:
            for batch in _batches(observation_events):
                append_events(root, batch)

    print(json.dumps({
        "mode": "check" if args.check else "apply",
        "new_cards": len(discovery_events),
        "new_dispositions": len(disposition_events),
        "new_surface_examinations": 0,
        "attempted_controls_in_receipt": attempted_controls,
        "observation_revisions": len(observation_events),
        "operational_claims": sum(
            event["payload"]["to_disposition"] == "operational"
            for event in observation_events
        ),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
