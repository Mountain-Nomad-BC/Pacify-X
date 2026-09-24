import pytest

from runtime.semantic_memory_refs import MemoryReference, extract_memory_references, parse_memory_reference


def test_stable_memory_reference_round_trip_and_extract():
    ref = MemoryReference("p1", "mem-1", 3)
    assert parse_memory_reference(ref.uri()) == ref
    refs = extract_memory_references(f"see {ref.uri()} and pxmem://p1/mem-2")
    assert [item.memory_id for item in refs] == ["mem-1", "mem-2"]
    assert parse_memory_reference(MemoryReference("project one", "mem-3").uri()).project_id == "project one"
    with pytest.raises(ValueError):
        parse_memory_reference("memory/hot/x")


def test_reference_parser_requires_canonical_percent_encoding():
    assert MemoryReference("p one", "m+1").uri() == "pxmem://p%20one/m%2B1"
    with pytest.raises(ValueError, match="canonically"):
        parse_memory_reference("pxmem://p%20one/%6d1")


def test_reference_revision_is_strict_positive_integer():
    with pytest.raises(ValueError):
        MemoryReference("p", "m", 0)
    with pytest.raises(ValueError):
        MemoryReference("p", "m", True)  # type: ignore[arg-type]


def test_extractor_never_accepts_valid_prefix_of_invalid_revision():
    assert extract_memory_references("broken pxmem://p/m@0 here") == ()
