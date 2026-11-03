"""Canonical producer census — the single source of truth for PX-OS-1067 counting.

Six figures were reported across this campaign (379, 378, 377, 374 and two different resolved
counts) because each session counted over a slightly different population with an implicit
definition. This module fixes the definitions and makes them executable, so a census can be
reproduced rather than quoted.

DEFINITIONS (normative)

* **effect record** — one discovered filesystem/process/network effect site.
* **producer** — one distinct path with at least one effect record of any kind. A file with only a
  process effect is a producer here; the custody registry separately requires a mutation to care.
* **mutating producer** — one distinct path with at least one `filesystem_mutation` record.
  This is the population the custody gate and the producer registry are about.
* **resolved** — the registry returns a current, source-backed classification.
* **unresolved** — the registry returns None.
* **gate finding** — one entry in `validate_effect_surfaces()["errors"]`.

The distinction that caused the drift: earlier censuses sometimes counted *all* producers and
sometimes only *mutating* producers, and sometimes classified over a population that included
producers HEAD-era discovery had proposed. This module always reports both and never mixes them.

Run:  .venv-repair\\Scripts\\python.exe -m runtime.producer_census
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "px.producer-census/1.0"


def census(root: Path, producer_paths: list[str] | None = None) -> dict[str, Any]:
    """Compute the canonical census for `root`. Deterministic; no filesystem writes.

    `producer_paths` names a population discovered by an evidence probe. When given, the
    effect image is rebuilt from exactly those files using the same classifier, so a
    producer-scoped audit can be replayed without claiming it is a full repository scan.
    """
    from .effect_surface import (
        classify_source_file,
        discover_effect_surfaces,
        validate_effect_surfaces,
    )
    from .mutating_producer_registry import (
        build_registry,
        default_classification,
        discover_mutating_producers,
    )

    root = Path(root).resolve()
    records = (
        discover_effect_surfaces(root)
        if producer_paths is None
        else [
            record
            for relative in producer_paths
            for record in classify_source_file(
                (root / relative).read_text(encoding="utf-8-sig"), relative
            )
        ]
    )
    all_producers = sorted({str(record["path"]).replace("\\", "/") for record in records})
    mutating = discover_mutating_producers(root, records=records)

    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for path, effects in mutating.items():
        verdict = default_classification(root, path, effects, records=records)
        if verdict is None:
            unresolved.append(path)
        else:
            resolved[path] = verdict["reason"]

    built = build_registry(root, records=records)
    # validate_effect_surfaces rescans for the published ownership image, which pins exact
    # source locators; the producer registry check reuses this scan instead of rescanning
    # once per delegated producer, which made the census quadratic.
    gate = validate_effect_surfaces(root)

    def family(paths) -> dict[str, int]:
        counts: collections.Counter = collections.Counter()
        for path in paths:
            counts[path.split("/", 1)[0]] += 1
        return dict(sorted(counts.items()))

    ids: collections.Counter = collections.Counter(record.get("id") for record in records)
    duplicates = sorted(key for key, count in ids.items() if count > 1 and key is not None)

    return {
        "schema_version": SCHEMA_VERSION,
        "definitions": {
            "effect_record": "one discovered effect site",
            "producer": "path with at least one effect record of any kind",
            "mutating_producer": "path with at least one filesystem_mutation record",
            "resolved": "registry returns a current source-backed classification",
            "gate_finding": "one entry in validate_effect_surfaces()['errors']",
        },
        "effect_records": len(records),
        "producers_any_effect": len(all_producers),
        "mutating_producers": len(mutating),
        "resolved": len(resolved),
        "unresolved": len(unresolved),
        "resolved_by_reason": dict(sorted(collections.Counter(resolved.values()).items())),
        "unresolved_by_family": family(unresolved),
        "registry_classified": len(built["producers"]),
        "registry_unclassified": len(built["unclassified"]),
        "gate_valid": gate["valid"],
        "gate_findings": len(gate["errors"]),
        "duplicate_effect_ids": duplicates,
        "unresolved_paths": sorted(unresolved),
        # A retained, typed population lets a later pass re-audit exactly the producers that
        # an evidence artifact covered, without re-deriving that set from a mutable census.
        "producer_paths": all_producers,
        "mutating_producer_paths": sorted(mutating),
    }


def main() -> int:
    document = census(Path.cwd())
    print(json.dumps(document, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
