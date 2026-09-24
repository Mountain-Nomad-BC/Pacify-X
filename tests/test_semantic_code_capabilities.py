from __future__ import annotations

from runtime.semantic_code_capabilities import OPERATIONS, operation_descriptor


def test_write_capability_is_explicit_and_high_risk_relative_to_reads():
    read = operation_descriptor("semantic.symbol.find")
    write = operation_descriptor("semantic.edit.apply")
    assert not read.mutation
    assert write.mutation
    assert read.risk == "R0"
    assert write.risk == "R3"
    assert len({item.operation for item in OPERATIONS}) == len(OPERATIONS)
