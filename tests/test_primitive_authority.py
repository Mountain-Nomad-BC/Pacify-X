from __future__ import annotations

import copy
from pathlib import Path

import pytest

from runtime.primitive_authority import (
    REQUIRED_PRIMITIVES,
    load_primitive_authority,
    resolve_primitive_owner,
    validate_primitive_authority,
)


ROOT = Path(__file__).resolve().parents[1]


def test_live_primitive_authority_is_complete_and_resolvable() -> None:
    report = validate_primitive_authority(ROOT)
    assert report["valid"], report["errors"]
    assert report["primitive_count"] == len(REQUIRED_PRIMITIVES) == 13
    for primitive in REQUIRED_PRIMITIVES:
        owner = resolve_primitive_owner(ROOT, primitive)
        assert owner["path"].startswith("runtime/")
        assert owner["symbol"]


def test_missing_primitive_is_rejected() -> None:
    payload = load_primitive_authority(ROOT)
    payload["primitives"].pop()
    payload["primitive_count"] -= 1
    report = validate_primitive_authority(ROOT, payload)
    assert not report["valid"]
    assert any("missing required primitives" in error for error in report["errors"])


def test_two_canonical_owners_are_rejected() -> None:
    payload = load_primitive_authority(ROOT)
    payload["primitives"].append(copy.deepcopy(payload["primitives"][0]))
    payload["primitive_count"] += 1
    report = validate_primitive_authority(ROOT, payload)
    assert not report["valid"]
    assert any("duplicate canonical owner" in error for error in report["errors"])


def test_unknown_owner_symbol_is_rejected() -> None:
    payload = load_primitive_authority(ROOT)
    payload["primitives"][0]["canonical_owner"]["symbol"] = "not_a_live_symbol"
    report = validate_primitive_authority(ROOT, payload)
    assert not report["valid"]
    assert any("unknown owner symbol" in error for error in report["errors"])


def test_bypass_without_matching_exception_is_rejected() -> None:
    payload = load_primitive_authority(ROOT)
    payload["primitives"][0]["declared_bypasses"] = ["PX-BYPASS-001"]
    report = validate_primitive_authority(ROOT, payload)
    assert not report["valid"]
    assert any("undeclared or stale bypass" in error for error in report["errors"])


def test_unknown_primitive_resolution_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown primitive"):
        resolve_primitive_owner(ROOT, "not_a_primitive")
