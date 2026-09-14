"""Causal checks for complete bounded startup metadata contracts."""

import hashlib
import json
from pathlib import Path

import pytest

from runtime.config import load_startup_config
from runtime.profiles import validate_profile, validate_profile_set
from runtime.world_state import (
    build_world_state,
    load_world_state_for_startup,
    validate_world_state,
)

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "old,new",
    [
        ("retry_requires_new_evidence = true", ""),
        ("retry_requires_new_evidence = true", "retry_requires_new_evidence = false"),
        ('default = "read_local"', 'default = "unknown-effect"'),
        ('approval_required = ["destructive"]', 'approval_required = "destructive"'),
        (
            'approval_required = ["destructive"]',
            'approval_required = ["destructive", "destructive"]',
        ),
        ("evidence_required = [", 'evidence_required = ["unknown-effect", '),
        ('id = "engineering-loop-bootstrap"', "id = 42"),
        ('version = "0.1.0"', 'version = ""'),
        ('mode = "proposal_first"', 'mode = ""'),
        (
            "[deferred_by_default]\nrepository_graph = true\nembeddings = true\nbrowser = true\nnetwork = true\ntool_installation = true\nservice_start = true\nfull_policy_text = true\nskill_packages = true",
            "[deferred_by_default]",
        ),
    ],
)
def test_startup_requires_complete_typed_policy(tmp_path, old, new):
    source = (ROOT / "bootstrap/startup.toml").read_text(encoding="utf-8")
    assert old in source
    target = tmp_path / "startup.toml"
    target.write_text(source.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        load_startup_config(target)


def test_startup_toml_is_bounded_before_decoding(tmp_path):
    target = tmp_path / "startup.toml"
    target.write_text(
        (ROOT / "bootstrap/startup.toml").read_text() + "\n#" + "x" * 70000
    )
    with pytest.raises(ValueError, match="budget|limit"):
        load_startup_config(target)


@pytest.mark.parametrize(
    "old,new",
    [
        ('local_models = "optional"', "local_models = false"),
        ('cloud_models = "optional"', 'cloud_models = "always-send"'),
        ('sensitive_data = "policy_gated"', 'sensitive_data = "public"'),
        ("max_agents = 2", "max_agents = 1000000000000"),
    ],
)
def test_profile_routing_values_are_validated(tmp_path, old, new):
    target = tmp_path / "profile.toml"
    target.write_text(
        (ROOT / "bootstrap/profiles/default.toml").read_text().replace(old, new)
    )
    assert validate_profile(target)["valid"] is False


def test_profile_is_acquired_once(tmp_path, monkeypatch):
    target = tmp_path / "profile.toml"
    target.write_bytes((ROOT / "bootstrap/profiles/default.toml").read_bytes())
    original = Path.open
    opened = []

    def counted(path, *args, **kwargs):
        if path == target:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    assert validate_profile(target)["valid"]
    assert len(opened) == 1


def test_profile_set_rejects_duplicate_declared_identity(tmp_path):
    for path in (ROOT / "bootstrap/profiles").glob("*.toml"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    (tmp_path / "duplicate.toml").write_bytes(
        (ROOT / "bootstrap/profiles/default.toml").read_bytes()
    )
    result = validate_profile_set(tmp_path)
    assert result["valid"] is False
    assert any("duplicate" in error for error in result["errors"])


def _seal(state):
    unsigned = {k: v for k, v in state.items() if k != "world_state_sha256"}
    state["world_state_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return state


@pytest.mark.parametrize(
    "field,value",
    [
        ("capability_count", True),
        ("model_count", -1),
        ("agent_count", float("nan")),
        ("health_state", "CERTIFIED"),
        ("stale_projection_ids", "graph"),
        ("release_campaign_id", {"credentials": "private body"}),
    ],
)
def test_world_state_rejects_resealed_invalid_metadata(tmp_path, field, value):
    state = build_world_state(tmp_path, source_revision="a" * 64)
    state[field] = value
    with pytest.raises(ValueError):
        validate_world_state(_seal(state), current_source_revision="a" * 64)


def test_world_state_rejects_nested_private_fields_even_when_resealed(tmp_path):
    state = build_world_state(tmp_path, source_revision="a" * 64)
    state["components"]["authority"]["prompt"] = "private body"
    with pytest.raises(ValueError):
        validate_world_state(_seal(state), current_source_revision="a" * 64)


def test_world_state_requires_external_revision_syntax(tmp_path):
    state = build_world_state(tmp_path, source_revision="a" * 64)
    state["source_revision"] = "not-a-revision"
    with pytest.raises(ValueError):
        validate_world_state(_seal(state), current_source_revision="not-a-revision")


def test_missing_world_state_sources_are_not_healthy_zero_evidence(tmp_path):
    state = build_world_state(tmp_path, source_revision="a" * 64)
    assert state["health_state"] == "UNVERIFIED"
    assert state["components"]["operations"]["state"] == "UNVERIFIED"
    assert state["open_blocker_count"] is None


def test_world_state_builder_rejects_malformed_source_instead_of_counting_it(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/agency_agent_registry.json").write_text(
        '{"agents":{"private":"body"}}'
    )
    with pytest.raises(ValueError):
        build_world_state(tmp_path, source_revision="a" * 64)


def test_world_state_loader_does_not_read_the_full_oversized_projection(
    tmp_path, monkeypatch
):
    (tmp_path / "registry").mkdir()
    path = tmp_path / "registry/px_world_state.json"
    path.write_text(" " * 70000 + "{}")
    original = Path.read_bytes

    def forbidden(target):
        if target == path:
            raise AssertionError("full projection read before byte cap")
        return original(target)

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    with pytest.raises(ValueError, match="budget|limit"):
        load_world_state_for_startup(tmp_path, current_source_revision="a" * 64)


def test_world_state_builder_handles_current_declared_metadata_in_an_owned_copy(
    tmp_path,
):
    from runtime.world_state import DETAIL_PATHS, MAX_WORLD_SOURCE_BYTES

    expected = {}
    for relative in DETAIL_PATHS.values():
        source = ROOT / relative
        if source.exists():
            assert source.stat().st_size <= MAX_WORLD_SOURCE_BYTES
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = source.read_bytes()
            target.write_bytes(raw)
            if relative == DETAIL_PATHS["agents"]:
                expected["agent_count"] = len(json.loads(raw)["agents"])
            elif relative == DETAIL_PATHS["models"]:
                expected["model_count"] = len(json.loads(raw)["models"])
    state = build_world_state(tmp_path, source_revision="a" * 64)
    assert validate_world_state(state, current_source_revision="a" * 64)["valid"]
    assert {key: state[key] for key in expected} == expected


def test_world_state_source_budget_precedes_body_acquisition(tmp_path, monkeypatch):
    import runtime.world_state as world

    (tmp_path / "registry").mkdir()
    path = tmp_path / "registry/models.json"
    path.write_text('{"models":[]}' + " " * 64)
    monkeypatch.setattr(world, "MAX_WORLD_SOURCE_BYTES", 32)
    original = Path.open

    def forbidden(target, *args, **kwargs):
        if target == path:
            raise AssertionError("oversized source was opened")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(ValueError, match="budget"):
        build_world_state(tmp_path, source_revision="a" * 64)


def test_world_state_does_not_suppress_malformed_json(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/models.json").write_text("{broken")
    with pytest.raises(ValueError):
        build_world_state(tmp_path, source_revision="a" * 64)


def test_world_state_rejects_duplicate_projection_ids_before_counting(tmp_path):
    (tmp_path / "registry").mkdir()
    rows = [
        {"projection_id": "same", "stale": True},
        {"projection_id": "same", "stale": False},
    ]
    (tmp_path / "registry/projection_staleness.json").write_text(
        json.dumps({"projections": rows})
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_world_state(tmp_path, source_revision="a" * 64)


@pytest.mark.parametrize(
    "text",
    ["resources = 42", "resources = []", "resources = {max_agents=true}", "not TOML"],
)
def test_malformed_profile_returns_structured_invalidity(tmp_path, text):
    path = tmp_path / "profile.toml"
    path.write_text(text)
    result = validate_profile(path)
    assert result["valid"] is False
    assert result["profile"] is None
    assert result["errors"]


def test_profile_closed_metadata_contract_rejects_machine_path_fields(tmp_path):
    path = tmp_path / "profile.toml"
    path.write_text(
        (ROOT / "bootstrap/profiles/default.toml").read_text()
        + '\nmodel_path="/Users/operator/private-model"\n'
    )
    assert validate_profile(path)["valid"] is False
