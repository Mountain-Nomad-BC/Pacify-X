import json

from runtime.world_state import (
    MAX_WORLD_STATE_BYTES,
    build_world_state,
    load_world_state_for_startup,
    validate_world_state,
)


def test_world_state_is_bounded_metadata_only_and_revision_bound(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / ".engineering-bootstrap/project-map").mkdir(parents=True)
    (tmp_path / ".engineering-bootstrap/project-map/map-receipt.json").write_text(
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
