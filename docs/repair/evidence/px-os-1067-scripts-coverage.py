"""PX-OS-1067 — decide which scripts producers the B7 ownership decision can cover.

The authorized ownership decision covers "durable runtime-state ownership". A `scripts/`
program that writes repository state is a writer of state in that model, so it can be
covered by the same custodian rule. A program whose output is the caller's chosen
location is a different contract (output-root grants), and stays unresolved.

Mapping is taken from the audit's own `static_disposition_class`, which was established by
source review — not re-derived here. Ambiguous classes are left unresolved.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-scripts-coverage.py
"""
from __future__ import annotations

import json
from pathlib import Path

EVIDENCE = Path(__file__).parent
AUDIT = EVIDENCE / "px-os-1067-script-producer-audit.json"

# Classes that describe a producer writing durable repository state under the B7 model.
DURABLE_STATE_CLASSES = {
    "self_owned_durable_state": (
        "Writes durable repository state; covered by the resource-ownership model."
    ),
    "recoverable_reclamation_candidate": (
        "Writes durable repository state with an owned-ephemeral reclamation; still a state "
        "writer under the same model."
    ),
    "delegated_publication": (
        "Delegates publication to the canonical owner; resolves through the existing live "
        "delegated-publication verdict."
    ),
}
# Classes that describe a destination chosen by the caller or by the environment.
GRANT_CLASSES = {
    "caller_directed_output": "Outputs to a caller-selected destination; needs an output-root grant.",
    "mixed_destination": "Writes both repository state and a caller destination; the caller class needs a grant.",
    "temporary_output": "Writes only to a temporary location; no durable destination to own.",
}
UNRESOLVED_CLASSES = {"unresolved_helper_mediated": "Effect is helper-mediated and not fully traced."}


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    rows = []
    for producer in audit["producers"]:
        static = producer.get("static_disposition_class")
        if static in DURABLE_STATE_CLASSES:
            coverage = "durable_state_writer"
            reason = DURABLE_STATE_CLASSES[static]
        elif static in GRANT_CLASSES:
            coverage = "needs_grant"
            reason = GRANT_CLASSES[static]
        else:
            coverage = "unresolved"
            reason = UNRESOLVED_CLASSES.get(static, f"Unknown class {static!r}")
        rows.append(
            {
                "path": producer["path"],
                "static_disposition_class": static,
                "coverage": coverage,
                "reason": reason,
                "source_sha256": producer.get("current_source_sha256"),
            }
        )

    totals: dict[str, int] = {}
    for row in rows:
        totals[row["coverage"]] = totals.get(row["coverage"], 0) + 1
    document = {
        "schema_version": "px.scripts-ownership-coverage/1.0",
        "gap_id": "PX-OS-1067",
        "priority": 4,
        "source_audit": AUDIT.name,
        "note": (
            "Coverage is a scope question, not a resolution. `durable_state_writer` says the "
            "resource-ownership model applies; it does not name an owner or grant a write."
        ),
        "producers": rows,
        "totals": totals,
    }
    (EVIDENCE / "px-os-1067-scripts-ownership-coverage.json").write_text(
        json.dumps(document, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
