"""Read-only observations remain proposals and do not execute caller effects."""
import copy

from runtime.cancellation_scope import build_scope, resolve_control
from runtime.capability_semantics import build_capability_semantic_profile
from runtime.semantic_code_paths import resolve_project_path
from runtime.semantic_normalize import NormalizationLedger, canonicalize_identifier


def test_path_observation_does_not_create_proposed_destination(tmp_path):
    path = resolve_project_path(tmp_path, "new/output.json", must_exist=False)
    assert path == tmp_path / "new/output.json"
    assert not (tmp_path / "new").exists()


def test_taxonomy_experience_is_caller_local_until_an_explicit_writer(tmp_path):
    ledger = NormalizationLedger()
    concept, _ = canonicalize_identifier("verify_output_sha256", ledger)
    assert concept == "verification"
    assert ledger.to_json()["raw_to_canonical"]["verify_output_sha256"] == "verification"
    assert list(tmp_path.iterdir()) == []


def test_cancel_scope_returns_adoption_without_mutating_durable_member_states():
    scope = build_scope("scope", "project", "root", ["child"])
    states = {"root": "running", "child": "cancel_requested"}
    before = dict(states)
    proposal = resolve_control(scope, states)
    assert proposal["adopt"] == {"root": "cancelled", "child": "cancelled"}
    assert proposal["authority_granted"] is False
    assert states == before


def test_semantic_profile_declared_write_effect_does_not_execute_or_change_input(tmp_path):
    metadata = {"id": "publish-report", "body": "SKILL.md", "contract": "contract.json"}
    contract = {"id": "publish-report", "owner": "runtime/real_writer.py",
                "effects": ["write local"], "resources": [str(tmp_path / "output.json")]}
    original = copy.deepcopy((metadata, contract))
    profile = build_capability_semantic_profile(metadata, contract)
    assert profile.effects == ("write local",)
    assert (metadata, contract) == original
    assert not (tmp_path / "output.json").exists()
