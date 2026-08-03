"""Machine-enforced disposition ledger for the controlling 42-card audit."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXPECTED_IDS = {f"PC-{index:03d}" for index in range(1, 43)}


def validate_full_repair_ledger(
    root: Path,
    *,
    require_all_passed: bool = False,
    allowed_pending: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    root = root.resolve()
    path = root / "registry/full_repair_ledger.json"
    errors: list[str] = []
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [f"cannot load full-repair ledger: {error}"]}
    cards = ledger.get("cards")
    if not isinstance(cards, list):
        return {"valid": False, "errors": ["full-repair cards must be a list"]}
    identifiers = [str(item.get("id", "")) for item in cards if isinstance(item, dict)]
    if set(identifiers) != EXPECTED_IDS or len(identifiers) != len(EXPECTED_IDS):
        errors.append("full-repair card denominator must be exactly PC-001 through PC-042")
    if ledger.get("card_count") != len(cards):
        errors.append("full-repair card_count does not match cards")
    known = set(identifiers)
    allowed = set(map(str, ledger.get("allowed_statuses", ())))
    for card in cards:
        if not isinstance(card, dict):
            errors.append("full-repair card is not an object")
            continue
        identifier = str(card.get("id", ""))
        status = str(card.get("status", ""))
        if status not in allowed:
            errors.append(f"{identifier}: invalid status {status}")
        if require_all_passed and status != "passed" and identifier not in allowed_pending:
            errors.append(f"{identifier}: remains {status}")
        dependencies = card.get("dependencies")
        if not isinstance(dependencies, list) or any(item not in known or item == identifier for item in dependencies):
            errors.append(f"{identifier}: malformed dependency set")
        for field in ("owners", "tests"):
            values = card.get(field)
            if not isinstance(values, list) or not values:
                errors.append(f"{identifier}: {field} must be nonempty")
                continue
            for relative in values:
                candidate = (root / str(relative)).resolve()
                if candidate != root and root not in candidate.parents:
                    errors.append(f"{identifier}: {field} path escapes root: {relative}")
                elif not candidate.exists():
                    errors.append(f"{identifier}: {field} path is missing: {relative}")
        if status == "passed":
            receipts = card.get("receipts")
            if not isinstance(receipts, list) or not receipts:
                errors.append(f"{identifier}: passed card requires executed receipts")
    return {
        "schema_version": "1.0", "valid": not errors, "card_count": len(cards),
        "passed": sum(item.get("status") == "passed" for item in cards if isinstance(item, dict)),
        "in_progress": sum(item.get("status") == "in_progress" for item in cards if isinstance(item, dict)),
        "open": sum(item.get("status") == "open" for item in cards if isinstance(item, dict)),
        "allowed_pending": sorted(allowed_pending),
        "errors": errors,
    }
