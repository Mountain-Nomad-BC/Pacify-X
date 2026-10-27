"""Synchronize parent REPAIR_STATUS.json to the authoritative 105-card kit queue.

The queue CSV is the finding denominator. REPAIR_STATUS.json is the bootstrap
disposition ledger. Previously only a hand-maintained subset of five cards was
written back, so the remaining 100 rows carried no disposition at all and the
"105 individually auditable entries" requirement could not be checked. This
script rewrites each row from the kit so every finding has an explicit state,
while preserving reviewed_closed = 0 (a queue state of IMPLEMENTED or TESTED is
not an independent review and must never be read as closure).
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

QUEUE = Path(r"C:\Users\Ben\Downloads\PX_REPAIR_UNBLOCK_AND_COMPLETION_PLAN\tracking\ALL_105_REPAIR_QUEUE.csv")
QUE = QUEUE
STATUS = Path("docs/repair/REPAIR_STATUS.json")

STATE_MAP = {
    "OPEN": "OPEN",
    "IN_PROGRESS": "OPEN",
    "IMPLEMENTED_UNVERIFIED": "IMPLEMENTED_UNVERIFIED",
    "TARGETED_TESTED": "TARGETED_TESTED",
    "IMPLEMENTED": "IMPLEMENTED_UNVERIFIED",
    "TESTED": "TARGETED_TESTED",
    # Integration-tested is still below operating verification; it is recorded
    # as its own evidence level rather than promoted to a stronger state.
    "TESTED_INTEGRATION": "TARGETED_TESTED",
    # Cards the kit itself never dispositioned carry no implementation claim.
    "UNVERIFIED_CURRENT_REPO": "OPEN",
}

rows = list(csv.DictReader(QUE.open(encoding="utf-8-sig")))
document = json.loads(STATUS.read_text(encoding="utf-8"))
existing = {card["id"]: card for card in document["cards"]}

unknown = sorted({r["implementation_state"] for r in rows} - set(STATE_MAP))
if unknown:
    raise SystemExit(f"unmapped kit states: {unknown}")

cards = []
for row in rows:
    card_id = row["id"]
    state = STATE_MAP[row["implementation_state"]]
    prior = existing.get(card_id, {})
    card = {
        "id": card_id,
        "title": row["title"],
        "group": row["batch"],
        "state": state,
        "kit_state": row["implementation_state"],
        "inherited_state_unverified": "UNVERIFIED_CURRENT_REPO",
        "current_source": "bootstrap checkout",
        "evidence": prior.get("evidence", []),
        "reviewer": "UNASSIGNED",
        "closed": False,
        "next_action": prior.get(
            "next_action",
            "No current-source disposition recorded. Re-derive cause and acceptance "
            "from the kit card against this checkout before changing state.",
        ),
    }
    if prior.get("evidence"):
        card["evidence_note"] = "evidence retained from the prior disposition of this card"
    cards.append(card)

document["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
document["cards"] = cards
document["card_count"] = len(cards)
document["source_queue"] = "PX_REPAIR_UNBLOCK_AND_COMPLETION_PLAN/tracking/ALL_105_REPAIR_QUEUE.csv"
document["kit_state_counts"] = {
    state: sum(1 for c in cards if c["kit_state"] == state)
    for state in sorted({c["kit_state"] for c in cards})
}
document["reviewed_closed"] = 0
STATUS.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(document["kit_state_counts"], indent=1))
print("cards", len(cards), "reviewed_closed", document["reviewed_closed"])
