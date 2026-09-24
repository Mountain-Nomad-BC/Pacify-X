from pathlib import Path

from runtime.admitted_fabric_integrations import nsai_library_status

ROOT = Path(__file__).parents[1]


def test_nsai_single_object_corpus_validates_and_matches_deterministic_index():
    value = nsai_library_status(ROOT)
    assert value["valid"] is True
    assert value["object_count"] == 74
    assert value["index_matches"] is True
    assert value["canonical_writes_performed"] is False
    assert value["authority_granted"] is False
    assert len(value["library_sha256"]) == 64
