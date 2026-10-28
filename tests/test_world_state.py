import json

from runtime.world_state import (
    MAX_WORLD_STATE_BYTES,
    build_world_state,
    load_world_state_for_startup,
    validate_world_state,
)


def test_world_state_is_bounded_metadata_only_and_revision_bound(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / ".agentic_engineering_os_px/project-map").mkdir(parents=True)
    (tmp_path / ".agentic_engineering_os_px/project-map/map-receipt.json").write_text(
        '{"map_revision":"map"}', encoding="utf-8"
    )
    (tmp_path / "registry/projection_staleness.json").write_text(
        '{"projections":[{"projection_id":"graph","stale":true}]}', encoding="utf-8"
    )
    state = build_world_state(tmp_path, source_revision="a" * 64)
    assert state["detail_bodies_hydrated"] is False
    assert state["stale_projection_ids"] == ["graph"]
    assert validate_world_state(state, current_source_revision="a" * 64)["bytes"] < MAX_WORLD_STATE_BYTES


def test_world_state_rejects_stale_source_and_private_payload(tmp_path):
    (tmp_path / "registry").mkdir()
    state = build_world_state(tmp_path, source_revision="a" * 64)
    try:
        validate_world_state(state, current_source_revision="b" * 64)
    except ValueError as error:
        assert "stale_source" in str(error)
    else:
        raise AssertionError("stale world state accepted")


def test_startup_reads_projection_first_and_lazily_selects_stale_details(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/projection_staleness.json").write_text(
        '{"projections":[{"projection_id":"semantic","stale":true}]}', encoding="utf-8"
    )
    state = build_world_state(tmp_path, source_revision="a" * 64)
    (tmp_path / "registry/px_world_state.json").write_text(json.dumps(state), encoding="utf-8")
    decision = load_world_state_for_startup(tmp_path, current_source_revision="a" * 64)
    assert decision["hydrate"] == ["startup_core_metadata", "projection:semantic"]
    assert decision["world_state"]["detail_bodies_hydrated"] is False


def test_startup_fails_closed_on_stale_world_state(tmp_path):
    (tmp_path / "registry").mkdir()
    state = build_world_state(tmp_path, source_revision="a" * 64)
    (tmp_path / "registry/px_world_state.json").write_text(json.dumps(state), encoding="utf-8")
    try:
        load_world_state_for_startup(tmp_path, current_source_revision="b" * 64)
    except ValueError as error:
        assert "stale_source" in str(error)
    else:
        raise AssertionError("startup accepted stale world state")


def test_current_world_state_uses_fresh_release_pointer_and_rejects_legacy_locator(tmp_path):
    import pytest
    from runtime.release_campaign import release_state_relative, clear_release_identity
    from runtime.world_state import _digest

    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/rev1xx-validation.json").write_text(json.dumps({
        "schema_version": "px.validation-basis/1.0", "basis": "current_implementation",
        "authority": "OWNER-FRESH-VALIDATION-001", "campaign_id": "fresh-world"}))
    processing = tmp_path / ".agentic_engineering_os_px/processing-order"
    processing.mkdir(parents=True)
    (processing / "repair-campaign.json").write_text(json.dumps({"campaign_id": "fresh-world", "phase": "repair"}))
    (processing / "release-identity.json").write_text('{"state":"certified","campaign_id":"old-release"}')
    clear_release_identity(tmp_path, campaign_id="new-release")
    state = build_world_state(tmp_path, source_revision="a" * 64)
    assert state["release_campaign_id"] == "new-release" and state["release_state"] == "cleared"
    assert state["details"]["release"] == release_state_relative(tmp_path).as_posix()
    assert validate_world_state(state, current_source_revision="a" * 64, root=tmp_path)["valid"]
    state["details"]["release"] = ".agentic_engineering_os_px/processing-order/release-identity.json"
    state["world_state_sha256"] = _digest({k:v for k,v in state.items() if k != "world_state_sha256"})
    with pytest.raises(ValueError, match="canonical metadata paths"):
        validate_world_state(state, current_source_revision="a" * 64, root=tmp_path)
