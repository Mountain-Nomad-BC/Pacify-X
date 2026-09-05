from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

from runtime.primitive_authority import load_primitive_authority
from runtime.primitive_lint import (
    scan_duplicate_primitives,
    validate_primitive_exceptions,
)


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_owner_alone_is_not_flagged() -> None:
    result = scan_duplicate_primitives(
        ROOT, candidate_paths=[ROOT / "runtime/capability_routing.py"]
    )
    assert result["valid"], result["findings"]


def test_duplicate_and_dynamic_ambiguity_are_not_guessed_clean(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.py"
    duplicate.write_text(
        "def normalize_task(value):\n    return value\n\n"
        "candidate = getattr(object(), 'retrieve')\n",
        encoding="utf-8",
    )
    result = scan_duplicate_primitives(ROOT, candidate_paths=[duplicate])
    assert not result["valid"]
    assert {item["kind"] for item in result["findings"]} == {
        "duplicate_definition",
        "dynamic_ambiguity",
    }


def test_plain_alias_is_reported_but_not_a_second_owner(tmp_path: Path) -> None:
    alias = tmp_path / "alias.py"
    alias.write_text("alias = retrieve\n", encoding="utf-8")
    result = scan_duplicate_primitives(ROOT, candidate_paths=[alias])
    assert result["valid"]
    assert result["aliases"]


def test_broad_or_expired_exception_is_rejected() -> None:
    registry = copy.deepcopy(load_primitive_authority(ROOT))
    record = registry["primitives"][0]
    record["declared_bypasses"] = ["PX-EXCEPTION-001"]
    record["bypass_exceptions"] = [
        {
            "exception_id": "PX-EXCEPTION-001",
            "rationale": "test",
            "expires_utc": "2020-01-01T00:00:00Z",
            "owner": {
                "language": "python",
                "module": "runtime.any",
                "path": "runtime/*.py",
                "symbol": "*",
            },
        }
    ]
    report = validate_primitive_exceptions(
        registry, now_utc=datetime(2026, 9, 5, tzinfo=timezone.utc)
    )
    assert not report["valid"]
    assert any("broad" in error for error in report["errors"])
    assert any("expired" in error for error in report["errors"])
