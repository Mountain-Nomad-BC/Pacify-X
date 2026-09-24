from runtime.admitted_fabric_integrations import persistent_memory_metadata


def test_external_persistent_memory_client_surface_is_read_advisory_until_px_admission():
    value = persistent_memory_metadata()
    assert value["authority_granted"] is False
    assert value["runtime_authority"] is False
    assert value["canonical_memory_authority"] is False
    assert value["mutation_capabilities_exposed"] == []
    assert value["private_repo_outside_px_root_required"] is True
