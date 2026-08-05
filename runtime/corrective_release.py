"""Machine-enforced corrective-release coverage and readiness rules."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Any


LEDGER_PATH = Path("registry/corrective_release_ledger.json")
ALLOWED_STATUSES = {
    "open",
    "in_progress",
    "blocked",
    "passed",
    "rejected_with_evidence",
    "deferred_with_owner",
}
BLOCKING_PRIORITIES = {"P0", "P1"}
SOURCE_CARD_IDS = {
    "REL-010-A",
    "REL-010-B",
    "REG-010-A",
    "REG-010-B",
    "REL-010-C",
    "REL-010-D",
    "TST-010-A",
    "TST-010-B",
    "TST-010-C",
    "TST-010-D",
    "ENV-010-A",
    "ENV-010-B",
    "SEC-010-A",
    "GEN-010-A",
    "GEN-010-B",
    "CFG-010-A",
    "HYG-010-A",
    "HYG-010-B",
    "AUD-010-A",
    "SEC-010-B",
    "DOC-010-A",
    "OBS-010-A",
    "REL-010-E",
}

SUPPORTED_CLI_ACCEPTANCE_FORMS = {
    ("audit", "structure"),
    ("project-check", "--project", "."),
    ("release", "environment"),
    ("release", "finalize", "--release", "0.6.3"),
    ("release", "verify"),
    ("release", "verify", "--release", "0.6.3"),
    ("test-profile", "run", "fast"),
    ("test-profile", "run", "full"),
    ("test-profile", "run", "release"),
}


def _acceptance_command_errors(root: Path, identifier: str, command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError as error:
        return [f"{identifier}: malformed acceptance command: {error}"]
    if not tokens:
        return [f"{identifier}: empty acceptance command"]
    if tokens[0] == "engineering-bootstrap":
        if tuple(tokens[1:]) not in SUPPORTED_CLI_ACCEPTANCE_FORMS:
            return [
                f"{identifier}: acceptance command is not supported by the CLI: {command}"
            ]
        return []
    if tokens[:3] == ["python", "-m", "runtime.cli"]:
        if tuple(tokens[3:]) not in SUPPORTED_CLI_ACCEPTANCE_FORMS:
            return [
                f"{identifier}: runtime CLI acceptance command is unsupported: {command}"
            ]
        return []
    if tokens[:3] == ["python", "-m", "pytest"]:
        errors = []
        for token in tokens[3:]:
            candidate = token.split("::", 1)[0]
            if candidate.startswith("tests/") or candidate.startswith("tests\\"):
                if not (root / candidate).exists():
                    errors.append(
                        f"{identifier}: acceptance test target does not exist: {candidate}"
                    )
        return errors
    if tokens[0] == "python" and len(tokens) > 1 and tokens[1].endswith(".py"):
        return (
            []
            if (root / tokens[1]).is_file()
            else [f"{identifier}: acceptance script does not exist: {tokens[1]}"]
        )
    return [f"{identifier}: unsupported acceptance command form: {command}"]


def load_corrective_ledger(root: Path) -> dict[str, Any]:
    return json.loads((root.resolve() / LEDGER_PATH).read_text(encoding="utf-8"))


def validate_corrective_ledger(
    root: Path,
    *,
    require_blocking_passed: bool = False,
    allow_finalizer_in_progress: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    try:
        ledger = load_corrective_ledger(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "valid": False,
            "errors": [f"cannot load corrective ledger: {error}"],
            "cards": 0,
        }
    cards = ledger.get("cards")
    if not isinstance(cards, list):
        return {"valid": False, "errors": ["cards must be a list"], "cards": 0}
    identifiers = [str(card.get("id", "")) for card in cards if isinstance(card, dict)]
    if len(identifiers) != len(set(identifiers)):
        errors.append("corrective ledger contains duplicate card IDs")
    source_ids = set(identifiers) & SOURCE_CARD_IDS
    child_ids = set(identifiers) - SOURCE_CARD_IDS
    if source_ids != SOURCE_CARD_IDS:
        errors.append(
            f"source-card denominator mismatch: missing={sorted(SOURCE_CARD_IDS - source_ids)} extra={sorted(source_ids - SOURCE_CARD_IDS)}"
        )
    if ledger.get("source_card_count") != len(SOURCE_CARD_IDS):
        errors.append("source_card_count is not authoritative")
    if ledger.get("card_count") != len(cards):
        errors.append("card_count does not match cards")
    known = set(identifiers)
    for card in cards:
        if not isinstance(card, dict):
            errors.append("card record must be an object")
            continue
        identifier = str(card.get("id", ""))
        status = card.get("status")
        priority = card.get("priority")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{identifier}: invalid status {status!r}")
        if priority not in {"P0", "P1", "P2", "P3"}:
            errors.append(f"{identifier}: invalid priority {priority!r}")
        dependencies = card.get("dependencies")
        if not isinstance(dependencies, list) or any(
            dep not in known for dep in dependencies
        ):
            errors.append(f"{identifier}: unknown or malformed dependency")
        if not isinstance(card.get("owning_paths"), list) or not card["owning_paths"]:
            errors.append(f"{identifier}: owning_paths must be nonempty")
        else:
            for relative in card["owning_paths"]:
                owner_path = (root / str(relative)).resolve()
                if root not in owner_path.parents and owner_path != root:
                    errors.append(
                        f"{identifier}: owning path escapes product root: {relative}"
                    )
                elif not owner_path.exists() and not (
                    str(relative).startswith("evidence/")
                    and status in {"open", "in_progress"}
                ):
                    errors.append(
                        f"{identifier}: owning path does not exist: {relative}"
                    )
        commands = card.get("acceptance_commands")
        if not isinstance(commands, list) or not commands:
            errors.append(f"{identifier}: acceptance_commands must be nonempty")
        else:
            for command in commands:
                if not isinstance(command, str):
                    errors.append(f"{identifier}: acceptance command must be text")
                else:
                    errors.extend(_acceptance_command_errors(root, identifier, command))
        receipts = card.get("receipts")
        if not isinstance(receipts, list):
            errors.append(f"{identifier}: receipts must be a list")
            receipts = []
        if status in {"passed", "rejected_with_evidence"} and not receipts:
            errors.append(f"{identifier}: closed status requires receipts")
        for relative in receipts:
            path = (root / str(relative)).resolve()
            if root not in path.parents and path != root:
                errors.append(f"{identifier}: receipt escapes product root: {relative}")
            elif not path.is_file():
                errors.append(f"{identifier}: missing receipt: {relative}")
        if status == "deferred_with_owner":
            if (
                not card.get("owner")
                or not card.get("risk")
                or not card.get("rationale")
            ):
                errors.append(
                    f"{identifier}: deferral requires owner, risk, and rationale"
                )
        parent = card.get("parent")
        if identifier in child_ids and (not parent or parent not in known):
            errors.append(f"{identifier}: child finding requires a known parent")
        if require_blocking_passed and priority in BLOCKING_PRIORITIES:
            permitted = {"passed"}
            if allow_finalizer_in_progress and identifier in {
                "REL-010-E",
                "REL-011-FULL-REPAIR",
            }:
                permitted.add("in_progress")
            if status not in permitted:
                errors.append(f"{identifier}: blocking card is {status}, not passed")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "release": ledger.get("release"),
        "cards": len(cards),
        "source_cards": len(source_ids),
        "children": len(child_ids),
        "blocking_open": sum(
            1
            for card in cards
            if card.get("priority") in BLOCKING_PRIORITIES
            and card.get("status") != "passed"
        ),
        "errors": errors,
    }
