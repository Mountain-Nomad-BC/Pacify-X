"""Host registration must connect native checks, not trust status assertions."""
from pathlib import Path
import json

import pytest

from runtime import plan_registry as plans
from tests.test_plan_current_campaign import fixture


def test_current_foundation_has_a_production_registration_seam():
    assert callable(getattr(plans, "register_foundation_readiness", None)), (
        "current foundation checks are disconnected from normal readiness"
    )


def controlled_foundation(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    plans.begin_plan_campaign(root)
    reference = tmp_path / "references"
    reference.mkdir()
    ledger = json.loads((root / plans.LEDGER_RELATIVE).read_text())
    git = {
        "BASE-001": set(next(c for c in ledger["cards"] if c["card_id"] == "BASE-001")["acceptance"]),
        "BASE-002": {"decision receipt names v1 starting commit"},
    }
    calls = []

    def native_check(target, *, reference_root):
        assert target == root and reference_root == reference
        calls.append(target)
        return {
            "schema_version": "px.current-foundation-proof/1.0", "valid": True,
            "campaign_id": json.loads((root / "policies/rev1xx-validation.json").read_text())["campaign_id"],
            "validation_basis": "current_implementation", "historical_prerequisites": False,
            "base_ledger_sha256": ledger["ledger_sha256"],
            "criteria": {c["card_id"]: [{"criterion": text,
                "result": "DEFERRED" if text in git.get(c["card_id"], set()) else "PASS"}
                for text in c["acceptance"]] for c in ledger["cards"] if c["wave"] == "W0"},
            "current_replacements": {key: True for key in (
                "source_custody", "package_versions", "decision_guard", "terminal_preservation", "release_isolation")},
            "git_acceptance_satisfied": False, "acceptance_state_changed": False,
        }

    revision = ["a" * 64]
    monkeypatch.setattr(plans, "foundation_report", native_check)
    monkeypatch.setattr(plans, "_foundation_source_revision", lambda *args: revision[0])
    return root, reference, calls, revision


def test_registered_native_foundation_controls_normal_readiness(tmp_path, monkeypatch):
    root, reference, calls, _ = controlled_foundation(tmp_path, monkeypatch)
    result = plans.register_foundation_readiness(root, reference_root=reference,
        git_deferral_authority="owner-explicit-git-hold")
    assert result["valid"] and calls
    current = plans.readiness_report(root)
    assert current["valid"]
    assert current["execution_ready"] == ["SEM-001"]
    assert current["accepted_card_count"] == 2
    assert current["campaign_conformant_cards"] == ["BASE-001", "BASE-002"]
    assert set(current["owner_deferred_criteria"]) == {"BASE-001", "BASE-002"}


def test_status_json_cannot_accept_git_or_unimplemented_semantics(tmp_path, monkeypatch):
    root, reference, _, _ = controlled_foundation(tmp_path, monkeypatch)
    plans.register_foundation_readiness(root, reference_root=reference,
        git_deferral_authority="owner-explicit-git-hold")
    path = root / plans.CURRENT_STATUS_RELATIVE
    original = path.read_bytes()
    value = json.loads(original)
    value["cards"]["BASE-001"]["status"] = "accepted"
    path.write_text(json.dumps(value))
    assert not plans.readiness_report(root)["valid"]
    path.write_bytes(original)
    value = json.loads(original)
    value["cards"]["SEM-001"] = dict(value["cards"]["BASE-004"])
    path.write_text(json.dumps(value))
    assert not plans.readiness_report(root)["valid"]


def test_current_source_drift_blocks_registered_readiness(tmp_path, monkeypatch):
    root, reference, _, revision = controlled_foundation(tmp_path, monkeypatch)
    plans.register_foundation_readiness(root, reference_root=reference,
        git_deferral_authority="owner-explicit-git-hold")
    revision[0] = "b" * 64
    assert not plans.readiness_report(root)["valid"]


def test_native_foundation_failure_cannot_be_replaced_by_saved_proof(tmp_path, monkeypatch):
    root, reference, _, _ = controlled_foundation(tmp_path, monkeypatch)
    plans.register_foundation_readiness(root, reference_root=reference,
        git_deferral_authority="owner-explicit-git-hold")
    def failed(*args, **kwargs):
        raise plans.PlanRegistryError("actual current foundation invariant failed")
    monkeypatch.setattr(plans, "foundation_report", failed)
    assert not plans.readiness_report(root)["valid"]


def test_explicit_owner_git_deferral_is_required_before_writes(tmp_path, monkeypatch):
    root, reference, _, _ = controlled_foundation(tmp_path, monkeypatch)
    before = (root / plans.CURRENT_STATUS_RELATIVE).read_bytes()
    with pytest.raises(plans.PlanRegistryError):
        plans.register_foundation_readiness(root, reference_root=reference, git_deferral_authority="")
    assert (root / plans.CURRENT_STATUS_RELATIVE).read_bytes() == before


def test_repeat_registration_preserves_current_transition_bytes(tmp_path, monkeypatch):
    root, reference, _, _ = controlled_foundation(tmp_path, monkeypatch)
    plans.register_foundation_readiness(root, reference_root=reference,
        git_deferral_authority="owner-explicit-git-hold")
    before = (root / plans.CURRENT_STATUS_RELATIVE).read_bytes()
    result = plans.register_foundation_readiness(root, reference_root=reference,
        git_deferral_authority="owner-explicit-git-hold")
    assert result["idempotent"]
    assert (root / plans.CURRENT_STATUS_RELATIVE).read_bytes() == before


def test_non_git_criterion_cannot_inherit_a_git_exception(tmp_path, monkeypatch):
    root, reference, _, _ = controlled_foundation(tmp_path, monkeypatch)
    native = plans.foundation_report
    def wrong_exception(*args, **kwargs):
        result = native(*args, **kwargs)
        result["criteria"]["BASE-003"][0]["result"] = "DEFERRED"
        return result
    monkeypatch.setattr(plans, "foundation_report", wrong_exception)
    before = (root / plans.CURRENT_STATUS_RELATIVE).read_bytes()
    with pytest.raises(plans.PlanRegistryError, match="exact owner Git"):
        plans.register_foundation_readiness(root, reference_root=reference,
            git_deferral_authority="owner-explicit-git-hold")
    assert (root / plans.CURRENT_STATUS_RELATIVE).read_bytes() == before


def test_forged_saved_proof_cannot_replace_the_native_check(tmp_path, monkeypatch):
    root, reference, calls, _ = controlled_foundation(tmp_path, monkeypatch)
    plans.register_foundation_readiness(root, reference_root=reference,
        git_deferral_authority="owner-explicit-git-hold")
    policy_path = root / "policies/rev1xx-validation.json"
    policy = json.loads(policy_path.read_text())
    _, registration = plans._foundation_bound_object(root, policy[plans.FOUNDATION_BINDING])
    _, proof = plans._foundation_bound_object(root, registration["proof"])
    proof["current_replacements"]["source_custody"] = False
    registration["proof"] = plans._foundation_store(root, "proof", proof)
    policy[plans.FOUNDATION_BINDING] = plans._foundation_store(root, "authority", registration)
    policy_path.write_text(json.dumps(policy))
    before = len(calls)
    assert not plans.readiness_report(root)["valid"]
    assert len(calls) > before


def test_foundation_host_state_cannot_enter_the_authored_source_census():
    from runtime.source_boundary import classify_path, RUNTIME_STATE, AUTHORED
    for name in ("registry/planning/rev1xx/foundation/authority-current.json",
            "registry/planning/rev1xx/foundation/proof-current.json",
            "registry/planning/rev1xx/current-status.json",
            "registry/planning/rev1xx/status-history/current.json"):
        assert classify_path(name)["classification"] == RUNTIME_STATE
    assert classify_path("registry/planning/rev1xx/source-manifest.json")["classification"] == AUTHORED


def test_engine_identity_excludes_host_state_but_keeps_admitted_source(tmp_path):
    from runtime.engine_identity import build_engine_identity
    root = tmp_path / "engine"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime/core.py").write_text("# actual source\n")
    before = build_engine_identity(root)
    state = root / "registry/planning/rev1xx/foundation"
    state.mkdir(parents=True)
    (state / "authority-current.json").write_text('{"actual_host_state":true}')
    (state.parent / "current-status.json").write_text('{"cards":{}}')
    after = build_engine_identity(root)
    assert after["tree_sha256"] == before["tree_sha256"]
    assert after["file_total"] == before["file_total"]
    (state.parent / "source-manifest.json").write_text('{"actual_source":true}')
    assert build_engine_identity(root)["tree_sha256"] != before["tree_sha256"]
