"""Initialize missing control gaps and import exact attempted observations.

Discovery/disposition is first-initialization work.  Later runs may attach a
typed observation only when an explicit current-source walk attempted that
exact control.  Inventory enumeration never substitutes for examination.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
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
    "operational",
    "interaction_complete",
    "observed_complete",
    "installed_operational_interaction_complete",
    "reversible_ui_interaction_observed",
}
CARD_COMPLETION_STATES = {"closed", "operationally_verified", "superseded"}
CARD_PRIMARY_STATES = (
    "discovered", "reproduced", "scoped", "approved", "implementing",
    "implemented", "narrowly_verified", "integrated",
    "operationally_verified", "closed",
)


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


def _controls_sha256(control_ids: list[str]) -> str:
    encoded = json.dumps(
        control_ids, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def plan_expected_inventory_revision(
    snapshot: dict[str, object],
    inventory: dict[str, object],
    reference: str,
    source_sha256: str,
) -> list[dict[str, object]]:
    """Predecessor-bind the ledger's expected denominator to canonical inventory bytes."""
    current = snapshot.get("expected_inventory")
    rows = inventory.get("surfaces")
    inventory_id = str(inventory.get("inventory_id") or "")
    if current is not None and not isinstance(current, dict):
        raise ValueError("ledger expected inventory is invalid")
    if not inventory_id or not isinstance(rows, list) or not rows:
        raise ValueError("typed inventory authority is incomplete")
    if not SHA256_RE.fullmatch(source_sha256):
        raise ValueError("typed inventory source SHA-256 is invalid")
    expected_rows = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("typed inventory surface is invalid")
        surface_id = str(row.get("surface_id") or "")
        control_count = row.get("expected_control_count")
        controls_sha256 = str(row.get("expected_controls_sha256") or "")
        if (
            not surface_id
            or not isinstance(control_count, int)
            or control_count < 0
            or not SHA256_RE.fullmatch(controls_sha256)
        ):
            raise ValueError(f"typed inventory denominator is invalid: {surface_id}")
        expected_rows.append({
            "surface_id": surface_id,
            "expected_control_count": control_count,
            "expected_controls_sha256": controls_sha256,
        })
    if len({row["surface_id"] for row in expected_rows}) != len(expected_rows):
        raise ValueError("typed inventory contains duplicate surfaces")
    if isinstance(current, dict) and all((
        current.get("inventory_id") == inventory_id,
        current.get("source") == reference,
        current.get("source_sha256") == source_sha256,
        current.get("surfaces") == expected_rows,
    )):
        return []
    payload: dict[str, object] = {
        "inventory_id": inventory_id,
        "source": reference,
        "source_sha256": source_sha256,
        "surfaces": expected_rows,
        "evidence": [{
            "reference": reference,
            "claim": (
                f"Canonical typed inventory {inventory_id} declares "
                f"{sum(row['expected_control_count'] for row in expected_rows)} controls "
                f"across {len(expected_rows)} surfaces."
            ),
        }],
    }
    event_type = "expected_inventory_registered"
    if isinstance(current, dict):
        payload["previous_source_sha256"] = str(current.get("source_sha256") or "")
        event_type = "expected_inventory_revised"
    return [{
        "event_type": event_type,
        "actor": ACTOR,
        "timestamp": _now(),
        "payload": payload,
    }]


def plan_inventory_revisions(
    snapshot: dict[str, object], inventory: dict[str, object], reference: str,
) -> list[dict[str, object]]:
    """Bind the append-only ledger denominator to the current typed inventory.

    Removed controls are retained by ``surface_inventory_revised`` as explicit
    retirement records.  The planner never treats disappearance as successful
    operation and never changes a card state.
    """
    surfaces = snapshot.get("surfaces")
    rows = inventory.get("surfaces")
    if not isinstance(surfaces, dict) or not isinstance(rows, list):
        raise ValueError("ledger or typed surface inventory is invalid")
    events: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("typed surface inventory row is invalid")
        surface_id = str(row.get("surface_id") or "")
        current = surfaces.get(surface_id)
        if not isinstance(current, dict):
            raise ValueError(f"typed inventory references unknown ledger surface: {surface_id}")
        controls = row.get("controls")
        source_files = row.get("source_files")
        if not isinstance(controls, list) or not controls or not isinstance(source_files, list) or not source_files:
            raise ValueError(f"typed inventory surface is incomplete: {surface_id}")
        control_ids = [str(item.get("control_id") or "") for item in controls if isinstance(item, dict)]
        if len(control_ids) != len(controls) or len(control_ids) != len(set(control_ids)) or any(not value for value in control_ids):
            raise ValueError(f"typed inventory controls are invalid: {surface_id}")
        if row.get("expected_control_count") != len(control_ids) or row.get("expected_controls_sha256") != _controls_sha256(control_ids):
            raise ValueError(f"typed inventory denominator is invalid: {surface_id}")
        current_ids = list(map(str, current.get("known_controls", [])))
        current_records = current.get("control_records", {})
        if current_ids == control_ids and current_records == {item["control_id"]: item for item in controls}:
            continue
        removed = sorted(set(current_ids) - set(control_ids))
        events.append({
            "event_type": "surface_inventory_revised",
            "actor": ACTOR,
            "timestamp": _now(),
            "payload": {
                "surface_id": surface_id,
                "previous_controls_sha256": _controls_sha256(current_ids),
                "controls": controls,
                "retired_controls": [
                    {
                        "control_id": control_id,
                        "reason": "The current canonical typed inventory no longer declares this control.",
                        "replacement_control_ids": [],
                    }
                    for control_id in removed
                ],
                "source_files": source_files,
                "reason": "Predecessor-bind the operational ledger to the current canonical typed control denominator.",
                "evidence": [{
                    "reference": reference,
                    "claim": f"The canonical typed inventory declares the complete current control set for {surface_id}.",
                }],
            },
        })
    return events


def _simulate_inventory_revisions(
    snapshot: dict[str, object], events: list[dict[str, object]],
) -> dict[str, object]:
    active = copy.deepcopy(snapshot)
    for event in events:
        payload = event["payload"]
        surface = active["surfaces"][payload["surface_id"]]
        controls = payload["controls"]
        surface["known_controls"] = [item["control_id"] for item in controls]
        surface["control_records"] = {item["control_id"]: item for item in controls}
        surface["control_dispositions"] = {
            control_id: disposition
            for control_id, disposition in surface.get("control_dispositions", {}).items()
            if control_id in surface["control_records"]
        }
    return active


def plan_operational_card_reconciliations(
    snapshot: dict[str, object], evidence_reference: str,
) -> tuple[list[dict[str, object]], list[str]]:
    """Advance only cards whose full historical control scope is current and operational."""
    cards = snapshot.get("cards")
    surfaces = snapshot.get("surfaces")
    if not isinstance(cards, dict) or not isinstance(surfaces, dict):
        raise ValueError("ledger cards or surfaces are missing")
    bindings: dict[str, dict[tuple[str, str], dict[str, object]]] = {}
    for surface_id, surface in surfaces.items():
        if not isinstance(surface, dict):
            continue
        for control_id, disposition in surface.get("control_dispositions", {}).items():
            if not isinstance(disposition, dict):
                continue
            for row in [disposition, *disposition.get("history", [])]:
                if not isinstance(row, dict):
                    continue
                for gap_id in row.get("gap_ids", []):
                    bindings.setdefault(str(gap_id), {})[(str(surface_id), str(control_id))] = disposition

    events: list[dict[str, object]] = []
    selected: list[str] = []
    for gap_id, controls in sorted(bindings.items()):
        card = cards.get(gap_id)
        if (
            not isinstance(card, dict)
            or card.get("current_state") in CARD_COMPLETION_STATES
            or card.get("classification") in {"host-owned", "intentionally-unsupported", "out-of-scope"}
            or not controls
            or any(
                disposition.get("disposition") != "operational"
                or not isinstance(disposition.get("observation"), dict)
                or disposition["observation"].get("outcome") != "operational"
                for disposition in controls.values()
            )
        ):
            continue
        chain: dict[str, dict[str, object]] = {}
        for stage in CHAIN_STAGES:
            items = [disposition["observation"]["interaction_chain"][stage] for disposition in controls.values()]
            if any(item.get("state") not in {"present", "not_applicable"} or not item.get("evidence") for item in items):
                break
            present = [item for item in items if item["state"] == "present"]
            chain[stage] = {
                "state": "present" if present else "not_applicable",
                "detail": (
                    f"Every current typed control historically bound to {gap_id} has direct operational evidence for {stage}."
                    if present else
                    f"Every current typed control historically bound to {gap_id} marks {stage} not applicable with evidence."
                ),
                "evidence": list(dict.fromkeys(
                    str(reference)
                    for item in (present or items)
                    for reference in item["evidence"]
                )),
            }
        if set(chain) != set(CHAIN_STAGES):
            continue
        selected.append(gap_id)
        evidence = [{
            "reference": evidence_reference,
            "claim": f"Every current typed control historically bound to {gap_id} has a complete exact operational interaction chain.",
        }]
        events.append({
            "event_type": "card_annotated", "actor": ACTOR, "timestamp": _now(),
            "payload": {
                "gap_id": gap_id,
                "note": "Reconciled the card interaction chain only from complete current typed-control observations.",
                "evidence": evidence,
                "patch": {
                    "interaction_chain": chain,
                    "completion_evidence": [evidence_reference],
                    "next_action": "Retain operational evidence and reopen on contrary current-source or installed-host behavior.",
                },
            },
        })
        state = str(card.get("current_state") or "")
        start = CARD_PRIMARY_STATES.index(state)
        target = CARD_PRIMARY_STATES.index("operationally_verified")
        for next_state in CARD_PRIMARY_STATES[start + 1:target + 1]:
            payload: dict[str, object] = {
                "gap_id": gap_id, "from_state": state, "to_state": next_state,
                "reason": "Advance only on complete exact operational observations for every current typed control in this card's historical scope.",
                "evidence": evidence,
            }
            if next_state == "implemented":
                payload["implementation_evidence"] = evidence
            elif next_state == "narrowly_verified":
                payload["verification"] = {"tests_run": ["exact current installed-host control probe"], "results": evidence}
            elif next_state == "integrated":
                payload["integration_evidence"] = evidence
            elif next_state == "operationally_verified":
                payload["operational_evidence"] = evidence
            events.append({"event_type": "card_transition", "actor": ACTOR, "timestamp": _now(), "payload": payload})
            state = next_state
    return events, selected


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
    attempted = record.get("attempted") is True
    observed = record.get("observed") is True
    if not attempted and not observed:
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
        "attempted": attempted,
        "observed": observed,
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
    examined = 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("walk receipt control record is invalid")
        observation = _typed_observation(receipt, record, reference, source_sha256)
        if observation is None:
            continue
        examined += 1
        surface_id = str(record.get("surface_id") or "")
        control_id = str(record.get("control_id") or "")
        surface = surfaces.get(surface_id)
        if not isinstance(surface, dict) or control_id not in surface.get("known_controls", []):
            raise ValueError(f"examined control is absent from the ledger inventory: {surface_id}/{control_id}")
        current = surface.get("control_dispositions", {}).get(control_id)
        if not isinstance(current, dict):
            raise ValueError(f"examined control lacks a predecessor disposition: {surface_id}/{control_id}")
        after = "operational" if observation["outcome"] == "operational" else "gap"
        # A later bounded or authority-limited observation is not contrary
        # evidence and must not erase a stronger current operational proof.
        # Actual operational failures remain represented by predecessor-bound
        # gap dispositions and therefore continue through the fail-closed path.
        if after == "gap" and current.get("disposition") == "operational":
            continue
        gap_ids = [] if after == "operational" else list(current.get("gap_ids", []))
        if after == "gap" and not gap_ids:
            raise ValueError(f"incomplete examined control has no retained gap: {surface_id}/{control_id}")
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
                "reason": "Attach the exact directly examined current-source control observation without promoting incomplete chains.",
                "evidence": [{
                    "reference": reference,
                    "claim": f"The current-source walk directly examined {control_id} and retained every chain-stage result.",
                }],
                "observation": observation,
            },
        })
    return events, examined


def _simulate_observation_revisions(
    snapshot: dict[str, object], events: list[dict[str, object]],
) -> dict[str, object]:
    """Apply planned observation revisions to a dry-run projection.

    The simulation retains each predecessor disposition in history because
    card reconciliation binds a card to every control that has ever named it.
    It intentionally consumes only events produced by
    ``plan_observation_revisions``; authoritative replay remains owned by the
    operational-gap ledger.
    """
    active = copy.deepcopy(snapshot)
    for event in events:
        payload = event["payload"]
        surface = active["surfaces"][payload["surface_id"]]
        current = surface["control_dispositions"][payload["control_id"]]
        prior_history = list(current.get("history", []))
        prior_history.append({
            "disposition": current["disposition"],
            "gap_ids": list(current["gap_ids"]),
            "evidence": list(current["evidence"]),
            "timestamp": current["timestamp"],
            "actor": current["actor"],
            "revision_reason": payload["reason"],
        })
        observation = copy.deepcopy(payload["observation"])
        surface["control_dispositions"][payload["control_id"]] = {
            "disposition": payload["to_disposition"],
            "gap_ids": list(payload["gap_ids"]),
            "evidence": copy.deepcopy(payload["evidence"]),
            "observation": observation,
            "proof_status": "current_typed" if observation else "legacy_unbound",
            "timestamp": event["timestamp"],
            "actor": event["actor"],
            "history": prior_history,
        }
    return active


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--walk-receipt", type=Path)
    parser.add_argument("--reconcile-cards", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    snapshot = read_snapshot(root)
    inventory_bytes = (root / INVENTORY).read_bytes()
    inventory = json.loads(inventory_bytes)
    expected_inventory_events = plan_expected_inventory_revision(
        snapshot, inventory, INVENTORY, hashlib.sha256(inventory_bytes).hexdigest()
    )
    inventory_events = plan_inventory_revisions(snapshot, inventory, INVENTORY)
    if not args.check:
        for batch in _batches([*expected_inventory_events, *inventory_events]):
            append_events(root, batch)
        snapshot = read_snapshot(root)
    else:
        snapshot = _simulate_inventory_revisions(snapshot, inventory_events)
    receipt: dict[str, object] | None = None
    receipt_reference = LIVE_WALK
    if args.walk_receipt:
        receipt, receipt_reference = _load_walk_receipt(root, args.walk_receipt)
    proof_reference = receipt_reference if receipt is not None else LIVE_WALK
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
                            "The typed source inventory declares this control, but no exact attempted observation has yet been "
                            "attached to its predecessor-bound disposition."
                        ),
                        "interaction_chain": _chain(control_id),
                        "classification": _classification(str(record["kind"])),
                        "severity": "medium",
                        "operational_impact": (
                            "This exact control can render or remain declared without proof of validation, authorization, backend "
                            "effect, acknowledgement, persistence, reload, failure, and recovery behavior."
                        ),
                        "dependencies": ["PX-OS-085"],
                        "blockers": ["An exact attempted current-source observation has not yet completed every applicable stage."],
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
                            "reference": proof_reference,
                            "claim": "The retained walk is the selected host observation authority; a typed attempted observation must still be attached before promotion.",
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
                    "reference": proof_reference,
                    "claim": "Operation remains a gap until an exact attempted observation completes every applicable chain stage.",
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
    examined_controls = 0
    attempted_controls = 0
    if receipt is not None:
        receipt_records = receipt.get("control_chains", {}).get("controls", [])
        if isinstance(receipt_records, list):
            attempted_controls = sum(
                isinstance(record, dict) and record.get("attempted") is True
                for record in receipt_records
            )
        active = read_snapshot(root) if not args.check else json.loads(json.dumps(snapshot))
        if args.check:
            # Dry-run the exact post-initialization state so --check can validate
            # a receipt that attempts controls first discovered by this run.
            for event in disposition_events:
                payload = event["payload"]
                active["surfaces"][payload["surface_id"]]["control_dispositions"][payload["control_id"]] = {
                    "disposition": "gap",
                    "gap_ids": list(payload["gap_ids"]),
                    "evidence": list(payload["evidence"]),
                    "observation": None,
                    "proof_status": "legacy_unbound",
                    "timestamp": timestamp,
                    "actor": ACTOR,
                    "history": [],
                }
        observation_events, examined_controls = plan_observation_revisions(
            active, receipt, receipt_reference
        )
        if not args.check:
            for batch in _batches(observation_events):
                append_events(root, batch)
        else:
            active = _simulate_observation_revisions(active, observation_events)

    card_events: list[dict[str, object]] = []
    reconciled_cards: list[str] = []
    if args.reconcile_cards:
        active = read_snapshot(root) if not args.check else active
        card_events, reconciled_cards = plan_operational_card_reconciliations(
            active, receipt_reference
        )
        if not args.check:
            for batch in _batches(card_events):
                append_events(root, batch)

    print(json.dumps({
        "expected_inventory_revision_events": len(expected_inventory_events),
        "inventory_revision_events": len(inventory_events),
        "mode": "check" if args.check else "apply",
        "new_cards": len(discovery_events),
        "new_dispositions": len(disposition_events),
        "new_surface_examinations": 0,
        "observed_or_attempted_controls_in_receipt": examined_controls,
        "attempted_controls_in_receipt": attempted_controls,
        "observation_revisions": len(observation_events),
        "operational_claims": sum(
            event["payload"]["to_disposition"] == "operational"
            for event in observation_events
        ),
        "reconciled_operational_cards": reconciled_cards,
        "card_reconciliation_events": len(card_events),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
