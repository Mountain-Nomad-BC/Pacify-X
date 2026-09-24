from __future__ import annotations

from runtime.semantic_code_types import Position, TextRange, stable_id, stable_sha256


def test_stable_identifiers_and_hashes_are_order_independent_for_dicts():
    assert stable_sha256({"b": 2, "a": 1}) == stable_sha256({"a": 1, "b": 2})
    assert stable_id("sym", "a", 1) == stable_id("sym", "a", 1)


def test_positions_and_ranges_fail_closed():
    try:
        Position(-1, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("negative line accepted")
    try:
        TextRange(Position(2, 0), Position(1, 0))
    except ValueError:
        pass
    else:
        raise AssertionError("reversed range accepted")
