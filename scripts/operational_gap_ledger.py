"""Operate the append-only Pacify-X operational gap ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import (  # noqa: E402
    append_event,
    append_transition_admission_backfill,
    guard_work_admission,
    read_head,
    read_snapshot,
    validate,
    write_snapshot,
)

_SEQUENCE_SUFFIX = re.compile(r":(\d+)$")


def _json_value(value: str, *, root: Path) -> dict[str, Any]:
    candidate = Path(value)
    if value in {"", "-"}:
        # Windows PowerShell does not reliably attach a pipeline into a native
        # child's standard input. Accept a file, or resolve a bare sequence
        # number to the matching event id, without weakening the JSON contract.
        if value == "":
            raw = _sequence_event_payload(value, root=root)
        elif sys.stdin.isatty():
            raise ValueError(
                "event payload '-' requires piped JSON on standard input; on a "
                "host shell pass a payload file or a bare event sequence number"
            )
        else:
            raw = sys.stdin.read()
    elif candidate.is_file():
        raw = candidate.read_text(encoding="utf-8")
    else:
        raw = _sequence_event_payload(value, root=root)
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("event payload must be a JSON object")
    return result


def _sequence_event_payload(value: str, *, root: Path) -> str:
    """Draft a payload only for a bare numeric sequence's success event."""

    match = _SEQUENCE_SUFFIX.search(value)
    if match is None:
        raise ValueError(
            "event payload must be a JSON object, a payload file, or the bare "
            "sequence number of a work_checkpoint or work_admitted event"
        )
    sequence = int(match.group(1))
    try:
        history = read_snapshot(root)
    except (OSError, ValueError) as error:
        raise ValueError("cannot resolve a sequence without readable ledger state") from error
    checkpoints = [
        item for item in history.get("work_checkpoints", [])
        if isinstance(item, dict) and int(item.get("sequence") or 0) == sequence
    ]
    admissions = [
        item for item in history.get("work_admissions", [])
        if isinstance(item, dict) and int(item.get("sequence") or 0) == sequence
    ]
    if checkpoints:
        return json.dumps({
            "previous_checkpoint_event_id": checkpoints[0].get("event_id"),
            "next_action": "superseded by a new bounded repair session for the same active gap",
            "unresolved_branch_gap_ids": [],
            "active_gap_id": checkpoints[0].get("active_gap_id"),
            "learned": "A failed session must not author its own closing checkpoint.",
            "evidence": [{
                "reference": ".engineering-bootstrap/test-evidence/px-os-1067-session-open-r97.json",
                "claim": "Session-open record for the bounded repair session that replaces the failed one.",
            }],
            "newly_discovered_gap_ids": [],
        })
    if admissions:
        return json.dumps({
            "admission_event_id": admissions[0].get("event_id"),
            "outcome": "superseded",
            "evidence": [{
                "reference": ".engineering-bootstrap/test-evidence/px-os-1067-session-open-r97.json",
                "claim": "Session-open record superseding the earlier bounded repair session for the same active gap.",
            }],
        })
    raise ValueError(
        "a bare sequence resolves only to a work_checkpoint or work_admitted event"
    )


def _apply_guard_args(parser: argparse.ArgumentParser) -> None:
    """Share the guard arguments with the standalone guard-work command."""

    parser.add_argument("--gap-id", required=True)
    parser.add_argument(
        "--effect",
        required=True,
        choices=("read", "write", "execute", "network", "install", "service", "destructive"),
    )
    parser.add_argument("--scope", action="append", required=True)
    parser.add_argument("--admission-event-id", required=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--actor", default="codex-host")
    sub = parser.add_subparsers(dest="command", required=True)

    initialize = sub.add_parser("initialize")
    initialize.add_argument("--ledger-id", required=True)
    initialize.add_argument("--scope", action="append", default=[])

    for name in (
        "register-surface", "register-inventory", "revise-inventory", "register-surface-alias", "add-controls", "replace-controls", "dispose-control",
        "discover", "annotate", "transition", "examine",
        "set-control-scope", "revise-control-scope", "attest-evidence",
        "register-report", "reconcile-report-finding", "relate-cards",
        "checkpoint", "admit-work", "close-work-session", "revise-disposition",
        "backfill-transition-admission",
    ):
        command = sub.add_parser(name)
        command.add_argument(
            "--payload",
            nargs="?",
            default="",
            help="JSON object, path to a JSON object, or bare event sequence number",
        )

    guard = sub.add_parser("guard-work")
    _apply_guard_args(guard)

    sub.add_parser("project")
    sub.add_parser("validate")
    sub.add_parser("progress")
    args = parser.parse_args()

    if args.command in {"admit-work", "close-work-session"} and not args.payload.strip():
        raise SystemExit(
            "refusing to draft a work-session event from a host shell; supply "
            "the exact --payload JSON object or a payload file so scope, expiry, "
            "and rollback remain typed and reviewed"
        )
    if args.command == "initialize":
        result: object = append_event(
            args.root,
            "ledger_initialized",
            {
                "ledger_id": args.ledger_id,
                "scope": args.scope,
                "authority": "User-directed operational truth ledger; narrative status and certification are non-authoritative.",
            },
            actor=args.actor,
        )
    elif args.command == "guard-work":
        result = guard_work_admission(
            read_snapshot(args.root),
            gap_id=args.gap_id,
            effect=args.effect,
            scope=args.scope,
            admission_event_id=args.admission_event_id,
        )
    elif args.command in {
        "register-surface", "register-inventory", "revise-inventory", "register-surface-alias", "add-controls", "replace-controls", "dispose-control",
        "discover", "annotate", "transition", "examine",
        "set-control-scope", "revise-control-scope", "attest-evidence",
        "register-report", "reconcile-report-finding", "relate-cards",
        "checkpoint", "admit-work", "close-work-session", "revise-disposition",
        "backfill-transition-admission",
    }:
        if args.command == "backfill-transition-admission":
            result = append_transition_admission_backfill(
                args.root, _json_value(args.payload, root=args.root), actor=args.actor
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        event_type = {
            "register-surface": "surface_registered",
            "register-inventory": "expected_inventory_registered",
            "revise-inventory": "expected_inventory_revised",
            "register-surface-alias": "surface_alias_registered",
            "add-controls": "surface_controls_added",
            "replace-controls": "surface_inventory_revised",
            "dispose-control": "control_disposition",
            "discover": "card_discovered",
            "annotate": "card_annotated",
            "transition": "card_transition",
            "examine": "surface_examined",
            "set-control-scope": "card_control_scope_set",
            "revise-control-scope": "card_control_scope_revised",
            "attest-evidence": "card_evidence_attested",
            "register-report": "report_registered",
            "reconcile-report-finding": "report_finding_reconciled",
            "relate-cards": "card_relationship",
            "checkpoint": "work_checkpoint",
            "admit-work": "work_admitted",
            "close-work-session": "work_session_closed",
            "revise-disposition": "control_disposition_revised",
        }[args.command]
        result = append_event(args.root, event_type, _json_value(args.payload, root=args.root), actor=args.actor)
    elif args.command == "project":
        result = write_snapshot(args.root)
    elif args.command == "validate":
        result = validate(args.root)
    else:
        result = read_head(args.root)["dashboard"]["progress"]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
