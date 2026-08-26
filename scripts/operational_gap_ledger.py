"""Operate the append-only Pacify-X operational gap ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import (
    append_event,
    append_transition_admission_backfill,
    guard_work_admission,
    read_head,
    read_snapshot,
    validate,
    write_snapshot,
)


def _json_value(value: str) -> dict[str, Any]:
    candidate = Path(value)
    raw = sys.stdin.read() if value == "-" else candidate.read_text(encoding="utf-8") if candidate.is_file() else value
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("event payload must be a JSON object")
    return result


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
        command.add_argument("--payload", required=True, help="JSON object or path to a JSON object")

    guard = sub.add_parser("guard-work")
    guard.add_argument("--gap-id", required=True)
    guard.add_argument("--effect", required=True, choices=("read", "write", "execute", "network", "install", "service", "destructive"))
    guard.add_argument("--scope", action="append", required=True)
    guard.add_argument("--admission-event-id", required=True)

    sub.add_parser("project")
    sub.add_parser("validate")
    sub.add_parser("progress")
    args = parser.parse_args()

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
                args.root, _json_value(args.payload), actor=args.actor
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
        result = append_event(args.root, event_type, _json_value(args.payload), actor=args.actor)
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
