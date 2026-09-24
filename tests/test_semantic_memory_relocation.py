from dataclasses import replace
import pytest

from runtime.semantic_memory_relocation import apply_memory_relocation, plan_memory_relocation
from tests.semantic_integration_test_support import memory_location, memory_record


def test_relocation_changes_location_not_memory_semantics():
    record = memory_record()
    current = memory_location(record)
    plan = plan_memory_relocation(record, current, to_tier="cold", to_locator="memory/cold/mem-1.json")
    preview_record, preview_location = apply_memory_relocation(record, current, plan, write=False)
    assert preview_record == record
    assert preview_location.storage_tier == "cold"
    assert preview_location.location_revision == current.location_revision
    written_record, written_location = apply_memory_relocation(record, current, plan, write=True)
    assert written_record == record
    assert written_location.location_revision == current.location_revision + 1
    stale = memory_location(record, locator="other")
    with pytest.raises(RuntimeError):
        apply_memory_relocation(record, stale, plan, write=True)


def test_relocation_plan_digest_is_verified_at_apply_time():
    record = memory_record()
    current = memory_location(record)
    plan = plan_memory_relocation(record, current, to_tier="cold", to_locator="cold/a")
    tampered = replace(plan, to_locator="cold/other")
    with pytest.raises(RuntimeError, match="digest"):
        apply_memory_relocation(record, current, tampered, write=True)


def test_relocation_rejects_noop_and_nonboolean_write():
    record = memory_record()
    current = memory_location(record)
    with pytest.raises(ValueError, match="already current"):
        plan_memory_relocation(record, current, to_tier=current.storage_tier, to_locator=current.storage_locator)
    plan = plan_memory_relocation(record, current, to_tier="warm", to_locator="warm/m")
    with pytest.raises(TypeError):
        apply_memory_relocation(record, current, plan, write=1)  # type: ignore[arg-type]
