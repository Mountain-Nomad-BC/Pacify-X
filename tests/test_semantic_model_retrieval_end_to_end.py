from pathlib import Path

from runtime.admitted_fabric_integrations import cognitive_query_read, semantic_code_inventory

ROOT = Path(__file__).parents[1]


def test_semantic_inventory_and_cognitive_retrieval_remain_non_authoritative_and_bounded():
    semantic = semantic_code_inventory()
    assert semantic["authoritative"] is False
    assert semantic["authority_granted"] is False
    result = cognitive_query_read(ROOT, "model routing retrieval", top_per_category=3)
    assert result.top_per_category == 3
    assert result.generation_id
    assert all(len(rows) <= 3 for rows in result.categories.values())
    for rows in result.categories.values():
        for row in rows:
            assert row.object_id
            assert row.revision
            assert row.evidence_refs
