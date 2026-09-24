import pytest

from runtime.semantic_memory_refs import extract_memory_references


def test_reference_scan_is_bounded():
    text = " ".join(f"pxmem://p/m{i}" for i in range(4))
    with pytest.raises(ValueError):
        extract_memory_references(text, max_references=3)


def test_reference_scan_rejects_nonpositive_and_boolean_budgets():
    for budget in (0, -1, True):
        with pytest.raises(ValueError):
            extract_memory_references("pxmem://p/m", max_references=budget)  # type: ignore[arg-type]
