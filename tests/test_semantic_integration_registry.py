from runtime.semantic_integration_registry import integration_inventory


def test_inventory_is_candidate_not_authority_and_tracks_installed_waves():
    inventory = integration_inventory()
    assert inventory["authoritative"] is False
    assert inventory["admission_required"] is True
    assert inventory["waves_required"] == inventory["installed_waves"]
    assert inventory["installed_waves"] == ["wave1", "wave2", "wave3", "wave4"]
    assert "semantic.knowledge.fuse" in inventory["operations"]
