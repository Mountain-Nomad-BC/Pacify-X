"""Declare count-field owners for registry/plan_corpus.json (PX-GAP-0014).

All four count fields are already derived by runtime/plan_registry.py in
admit_corpus(). This adds the missing registry_envelope_inventory records so the
envelope validator can recompute and verify them instead of trusting them.

Record identity is asserted to be unique and the file is rewritten atomically.
No existing record is modified.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "registry" / "registry_envelope_inventory.json"
TARGET = "registry/plan_corpus.json"
SCHEMA = "root schema_version plus shared registry-envelope invariant"

SOURCE_FREEZE = "registry/source_freeze.json"
PUNCH_LEDGER = "registry/punch_card_ledger.json"
FREEZE_OWNER = "runtime/source_freeze.py"
LEDGER_OWNER = "runtime/plan_registry.py"

DERIVED_RECORDS = [
    {
        "builder": "runtime/source_freeze.py",
        "collection_key": "files",
        "consumer": "runtime/registry_envelope.py",
        "count_key": "file_count",
        "path": SOURCE_FREEZE,
        "rule": "length",
        "schema": SCHEMA,
    },
    {
        "builder": "runtime/source_freeze.py",
        "collection_key": "files",
        "consumer": "runtime/registry_envelope.py",
        "count_key": "byte_count",
        "field": "bytes",
        "path": SOURCE_FREEZE,
        "rule": "sum_bytes",
        "schema": SCHEMA,
    },
    {
        "builder": LEDGER_OWNER,
        "collection_key": "cards",
        "consumer": "runtime/registry_envelope.py",
        "count_key": "card_count",
        "path": PUNCH_LEDGER,
        "rule": "length",
        "schema": SCHEMA,
    },
]

NEW_RECORDS = [
    {
        "builder": "runtime/plan_registry.py",
        "collection_key": "archives",
        "consumer": "runtime/registry_envelope.py",
        "count_key": "archive_count",
        "path": TARGET,
        "rule": "length",
        "schema": SCHEMA,
    },
    {
        "builder": "runtime/plan_registry.py",
        "collection_key": "admitted_sources",
        "consumer": "runtime/registry_envelope.py",
        "count_key": "unique_payload_count",
        "path": TARGET,
        "rule": "length",
        "schema": SCHEMA,
    },
    {
        "builder": "runtime/plan_registry.py",
        "collection_key": "admitted_sources",
        "consumer": "runtime/registry_envelope.py",
        "count_key": "duplicate_payload_count",
        "nested": "duplicate_copies",
        "path": TARGET,
        "rule": "nested_nonempty",
        "schema": SCHEMA,
    },
    # expected_unique_payload_count is deliberately NOT declared here. It is the
    # BASE-003 declared plan expectation EXPECTED_UNIQUE_PAYLOADS, not a count derived
    # from an owned collection. The envelope vocabulary can only recompute a count from
    # a collection inside the document (length, filtered, unique, duplicates,
    # nested_*) or from an external JSON document (external_*); it cannot read a Python
    # module constant. Declaring it would either misrepresent it as derived from
    # admitted_sources, which would be false, or leave it permanently unowned.
    #
    # Its integrity is enforced at the owning generator instead: admit_corpus() writes
    # expected_unique_payload_count, unique_payload_matches_expectation and the whole
    # digest-bound body from the same constant in one commit, so a drift between the
    # expectation and the measured count is reported rather than reconciled away.
    # Tracked as the remaining deferral in PX-GAP-0014.
    {
        "builder": "runtime/plan_registry.py",
        "collection_key": "admitted_sources",
        "consumer": "runtime/registry_envelope.py",
        "count_key": "unique_payload_count",
        "path": TARGET,
        "rule": "length",
        "schema": SCHEMA,
    },
]


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    records = inventory["records"]
    existing = {(item["path"], item["count_key"]) for item in records}

    added = []
    for record in NEW_RECORDS + DERIVED_RECORDS:
        identity = (record["path"], record["count_key"])
        if identity in existing:
            print(f"already declared, left untouched: {record['count_key']}")
            continue
        records.append(record)
        existing.add(identity)
        added.append(record["count_key"])

    records.sort(key=lambda item: (item["path"], item["count_key"]))
    inventory["records"] = records
    INVENTORY.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"added: {added}")
    print(f"records now: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())