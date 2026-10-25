"""Regression: the contract ownership registry must be derivable from source alone.

Before this test existed, ``build()`` silently copied the owner/enforcement/tests
of any contract it had no rule for out of ``registry/contract_ownership.json``.
That made the published registry self-justifying: it reproduced byte-for-byte
even when source authority was missing, and a stale record could never be
detected.  These tests fail if the fallback is reintroduced or if a contract is
added without an explicit ownership rule.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.build_contract_ownership_registry import build, dump_result

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "registry/contract_ownership.json"


def test_build_needs_no_published_registry(tmp_path: Path) -> None:
    committed = ROOT / REGISTRY
    assert committed.is_file(), "published registry is missing; cannot compare"
    isolated = tmp_path / "root"
    shutil.copytree(ROOT / "contracts", isolated / "contracts")
    assert not (isolated / REGISTRY).exists()

    rebuilt = build(isolated)
    committed_text = committed.read_text(encoding="utf-8")

    assert dump_result(rebuilt) == committed_text
    assert b"\r\n" not in committed.read_bytes()


def test_every_contract_has_an_explicit_rule() -> None:
    records = build(ROOT)["records"]
    on_disk = sorted(
        path.relative_to(ROOT).as_posix() for path in (ROOT / "contracts").rglob("*.json")
    )
    assert sorted(record["path"] for record in records) == on_disk
    for record in records:
        assert record["owner"], record["path"]
        assert record["producers"], record["path"]
        assert record["enforcement"], record["path"]
        assert len(record["tests"]) > 1, record["path"]


def test_unknown_contract_fails_closed(tmp_path: Path) -> None:
    isolated = tmp_path / "root"
    shutil.copytree(ROOT / "contracts", isolated / "contracts")
    rogue = isolated / "contracts" / "rogue-contract.schema.json"
    rogue.write_text(
        json.dumps({"$id": "urn:test:rogue", "title": "Rogue", "type": "object"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="contract has no ownership rule"):
        build(isolated)
