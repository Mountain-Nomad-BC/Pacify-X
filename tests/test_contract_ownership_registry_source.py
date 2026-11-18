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
    isolated = tmp_path / "root"
    shutil.copytree(ROOT / "contracts", isolated / "contracts")
    assert not (isolated / REGISTRY).exists()

    rebuilt = build(isolated)
    assert rebuilt == build(ROOT)
    # Published output can lag source during repair. Independence means neither
    # absence nor a poisoned published owner can change the source-derived image.
    published = isolated / REGISTRY
    published.parent.mkdir(parents=True)
    poisoned = json.loads(json.dumps(rebuilt))
    for record in poisoned["records"]:
        record["owner"] = "runtime/foreign_owner.py"
        record["enforcement"] = "untrusted_published_label"
    published.write_text(json.dumps(poisoned), encoding="utf-8")
    assert build(isolated) == rebuilt
    assert b"\r\n" not in dump_result(rebuilt).encode("utf-8")


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
