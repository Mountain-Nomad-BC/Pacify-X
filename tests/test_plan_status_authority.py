"""Untrusted JSON must never grant dependency authority."""
import copy
import hashlib
import json

import pytest

import runtime.plan_registry as plans


def sample_ledger():
    def card(name, dependencies):
        return plans.CardLedgerEntry(
            name, name, "W0", "runtime/source_freeze.py",
            ("runtime/source_freeze.py",), (), dependencies,
            ("snapshot is independently verified",), "Restore snapshot",
            "manifests/punch_cards.json", "D-001", "Preserved",
        )
    return plans.build_card_ledger([card("BASE-001", ()), card("MIG-001", ("BASE-001",))])


def fixture(tmp_path, status="accepted"):
    evidence = tmp_path / "proof.json"
    evidence.write_text(json.dumps({"verified": True}))
    base = sample_ledger()
    overlay = {
        "schema_version": "px.punch-card-status/2.0", "campaign_id": "campaign-test",
        "base_ledger_sha256": base["ledger_sha256"], "source_revision": "a" * 64,
        "generator": "test-owned-evaluator", "timestamp": "2026-10-02T12:00:00Z",
        "cards": {"BASE-001": {
            "prior_status": "partial_verified", "status": status,
            "owner_decision": "owner-event-1",
            "evidence": [{"path": "proof.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            "acceptance": [{"criterion": "snapshot is independently verified", "result": "PASS", "evidence": ["proof.json"]}],
        }},
    }
    path = tmp_path / "status.json"
    path.write_text(json.dumps(overlay))
    return base, overlay, path, evidence


def authority(tmp_path, *, evaluators=True, requested_status="accepted"):
    # This evaluator reads the real proof; it does not accept the overlay's PASS.
    def verified(paths):
        return len(paths) == 1 and json.loads(paths[0].read_text())["verified"] is True
    return plans.StatusAuthority(
        root=tmp_path, campaign_id="campaign-test", source_revision=lambda: "a" * 64,
        prior_statuses={"BASE-001": "partial_verified"},
        owner_decisions={"owner-event-1": plans.StatusOwnerDecision(
            card_id="BASE-001", requested_status=requested_status,
            campaign_id="campaign-test", source_revision="a" * 64,
            base_ledger_sha256=sample_ledger()["ledger_sha256"], authority="admitted-test-owner",
        )},
        evaluators={ ("BASE-001", "snapshot is independently verified"): verified } if evaluators else {},
    )


def test_legacy_partial_status_cannot_unlock_migration(tmp_path):
    base = sample_ledger()
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"cards": {"BASE-001": {"status": "narrowly_verified"}}}))
    with pytest.raises(plans.PlanRegistryError):
        plans.apply_status(base, path)


def test_valid_accepted_proof_unlocks_exact_dependent(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    view = plans.apply_status(base, path, authority=authority(tmp_path))
    assert plans.ready_cards(view) == ["MIG-001"]
    assert base == sample_ledger(), "overlay must not mutate canonical base truth"
    assert "dependency_ready_cards" not in base
    assert base["topologically_unblocked_by_graph_shape"] == ["BASE-001", "MIG-001"]


def test_partial_proof_never_unlocks_dependency(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path, status="narrowly_verified")
    view = plans.apply_status(base, path, authority=authority(tmp_path, requested_status="partial_verified"))
    assert "MIG-001" not in plans.ready_cards(view)
    assert view["cards"][0]["status"] == "partial_verified"


@pytest.mark.parametrize("mutation", [
    "schema", "campaign", "ledger", "revision", "closed", "owner", "prior",
    "transition", "omitted_criterion", "no_evidence", "bad_hash", "escape",
    "extra_criterion", "criterion_without_evidence", "unknown_card", "timestamp",
])
def test_forged_overlay_is_rejected(tmp_path, mutation):
    base, data, path, evidence = fixture(tmp_path)
    row = data["cards"]["BASE-001"]
    if mutation == "schema": data["schema_version"] = "garbage"
    elif mutation == "campaign": data["campaign_id"] = "another"
    elif mutation == "ledger": data["base_ledger_sha256"] = "0" * 64
    elif mutation == "revision": data["source_revision"] = "b" * 64
    elif mutation == "closed": row["status"] = "closed"
    elif mutation == "owner": row["owner_decision"] = "self-approved"
    elif mutation == "prior": row["prior_status"] = "planned"
    elif mutation == "transition": row["status"] = "planned"
    elif mutation == "omitted_criterion": row["acceptance"] = []
    elif mutation == "no_evidence": row["evidence"] = []
    elif mutation == "bad_hash": row["evidence"][0]["sha256"] = "0" * 64
    elif mutation == "escape": row["evidence"][0]["path"] = "../proof.json"
    elif mutation == "extra_criterion": row["acceptance"].append({"criterion": "invented", "result": "PASS", "evidence": ["proof.json"]})
    elif mutation == "criterion_without_evidence": row["acceptance"][0]["evidence"] = []
    elif mutation == "unknown_card": data["cards"]["NOPE"] = copy.deepcopy(row)
    elif mutation == "timestamp": data["timestamp"] = "yesterday"
    path.write_text(json.dumps(data))
    with pytest.raises(plans.PlanRegistryError):
        plans.apply_status(base, path, authority=authority(tmp_path))


def test_pass_assertion_cannot_replace_evaluator(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    with pytest.raises(plans.PlanRegistryError, match="evaluator"):
        plans.apply_status(base, path, authority=authority(tmp_path, evaluators=False))


def test_bad_underlying_proof_is_rejected_even_with_current_hash(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    evidence.write_text(json.dumps({"verified": False}))
    overlay["cards"]["BASE-001"]["evidence"][0]["sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    path.write_text(json.dumps(overlay))
    with pytest.raises(plans.PlanRegistryError, match="evaluation"):
        plans.apply_status(base, path, authority=authority(tmp_path))


def test_readiness_rechecks_evidence_and_overlay(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    view = plans.apply_status(base, path, authority=authority(tmp_path))
    evidence.unlink()
    with pytest.raises(plans.PlanRegistryError):
        plans.ready_cards(view)


def test_json_roundtrip_cannot_forge_a_trusted_status_view(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    view = plans.apply_status(base, path, authority=authority(tmp_path))
    untrusted = json.loads(json.dumps(view))
    with pytest.raises(plans.PlanRegistryError, match="status authority"):
        plans.ready_cards(untrusted)


def test_projection_mutation_is_rejected_even_with_recomputed_digest(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    view = plans.apply_status(base, path, authority=authority(tmp_path))
    view["cards"][0]["status"] = "blocked"
    payload = {k: v for k, v in view.items() if k != "ledger_sha256"}
    view["ledger_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(plans.PlanRegistryError):
        plans.ready_cards(view)


def test_evaluator_cannot_change_evidence_during_acceptance(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    context = authority(tmp_path)
    def mutate(paths):
        paths[0].write_text("changed")
        return True
    context.evaluators[("BASE-001", "snapshot is independently verified")] = mutate
    with pytest.raises(plans.PlanRegistryError, match="hash"):
        plans.apply_status(base, path, authority=context)


def test_source_change_during_evaluation_is_rejected(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    revisions = iter(["a" * 64, "b" * 64])
    context = authority(tmp_path)
    context = plans.StatusAuthority(
        root=context.root, campaign_id=context.campaign_id,
        source_revision=lambda: next(revisions), prior_statuses=context.prior_statuses,
        owner_decisions=context.owner_decisions, evaluators=context.evaluators,
    )
    with pytest.raises(plans.PlanRegistryError, match="revision changed"):
        plans.apply_status(base, path, authority=context)


def test_duplicate_json_fields_are_not_authority(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    text = json.dumps(overlay).replace('"campaign_id": "campaign-test"', '"campaign_id": "forged", "campaign_id": "campaign-test"')
    path.write_text(text)
    with pytest.raises(plans.PlanRegistryError, match="duplicate JSON"):
        plans.apply_status(base, path, authority=authority(tmp_path))


def test_admitted_blocking_gap_holds_otherwise_ready_card(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    context = authority(tmp_path)
    context = plans.StatusAuthority(
        root=context.root, campaign_id=context.campaign_id,
        source_revision=context.source_revision, prior_statuses=context.prior_statuses,
        owner_decisions=context.owner_decisions, evaluators=context.evaluators,
        blocking_cards=frozenset({"MIG-001"}),
    )
    view = plans.apply_status(base, path, authority=context)
    assert plans.ready_cards(view) == []


def test_status_overlay_outside_root_is_rejected(tmp_path):
    root = tmp_path / "governed"
    root.mkdir()
    base, overlay, path, evidence = fixture(root)
    external = tmp_path / "outside.json"
    external.write_bytes(path.read_bytes())
    with pytest.raises(plans.PlanRegistryError, match="outside"):
        plans.apply_status(base, external, authority=authority(root))


def test_empty_evidence_cannot_prove_acceptance(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    evidence.write_bytes(b"")
    overlay["cards"]["BASE-001"]["evidence"][0]["sha256"] = hashlib.sha256(b"").hexdigest()
    path.write_text(json.dumps(overlay))
    with pytest.raises(plans.PlanRegistryError, match="empty"):
        plans.apply_status(base, path, authority=authority(tmp_path))


def test_owner_decision_cannot_be_reused_for_another_revision(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    context = authority(tmp_path)
    context.owner_decisions["owner-event-1"] = plans.StatusOwnerDecision(
        card_id="BASE-001", requested_status="accepted", campaign_id="campaign-test",
        source_revision="b" * 64, base_ledger_sha256=base["ledger_sha256"], authority="admitted-test-owner",
    )
    with pytest.raises(plans.PlanRegistryError, match="owner decision"):
        plans.apply_status(base, path, authority=context)


def test_normal_cli_blocks_forged_status_without_mutating_source(tmp_path, capsys):
    from runtime.cli import main

    registry = tmp_path / "registry"
    registry.mkdir()
    ledger = registry / "punch_card_ledger.json"
    ledger.write_text(json.dumps(sample_ledger()))
    overlay = registry / "punch_card_status.json"
    overlay.write_text(json.dumps({"cards": {"BASE-001": {"status": "closed"}}}))
    before = {p.name: p.read_bytes() for p in registry.iterdir()}
    assert main(["--root", str(tmp_path), "plan-readiness"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] is False
    assert result["execution_ready"] == []
    assert result["accepted_card_count"] == 0
    assert before == {p.name: p.read_bytes() for p in registry.iterdir()}


def test_normal_cli_reports_only_unrecorded_entry_card(tmp_path, capsys):
    from runtime.cli import main

    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "punch_card_ledger.json").write_text(json.dumps(sample_ledger()))
    assert main(["--root", str(tmp_path), "plan-readiness"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["execution_ready"] == ["BASE-001"]
    assert result["accepted_card_count"] == 0


def test_runtime_report_accepts_only_admitted_host_proof(tmp_path):
    base, overlay, path, evidence = fixture(tmp_path)
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "punch_card_ledger.json").write_text(json.dumps(base))
    (registry / "punch_card_status.json").write_bytes(path.read_bytes())
    report = plans.readiness_report(tmp_path, authority=authority(tmp_path))
    assert report["valid"] is True
    assert report["execution_ready"] == ["MIG-001"]
    assert report["accepted_card_count"] == 1


def test_admitted_manifest_is_portable_and_rejects_changed_bytes(tmp_path):
    import hashlib

    source = tmp_path / "input.json"
    source.write_text(json.dumps({"cards": [{"id": "BASE-001", "title": "Preserve", "wave": "W0", "existing_owners": ["runtime/plan_registry.py"], "depends_on": [], "acceptance": ["verified snapshot"], "rollback": "restore snapshot"}]}))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    root = tmp_path / "working"
    admitted = plans.admit_card_manifest(source, root, expected_sha256=digest)
    assert plans.load_cards(source) == plans.load_cards(admitted)
    ledger_path = plans.write_admitted_card_ledger(root, manifest_sha256=digest)
    body = json.loads(ledger_path.read_text())
    assert plans.validate_ledger(body)["valid"] is True
    assert body["cards"][0]["source"] == "sha256:" + digest
    assert "status" not in body["cards"][0]
    admitted.write_text("{}")
    before = ledger_path.read_bytes()
    with pytest.raises(plans.PlanRegistryError, match="digest mismatch"):
        plans.write_admitted_card_ledger(root, manifest_sha256=digest)
    assert ledger_path.read_bytes() == before
    with pytest.raises(plans.PlanRegistryError, match="modified"):
        plans.admit_card_manifest(source, root, expected_sha256=digest)


def test_manifest_admission_rejects_unlocked_input(tmp_path):
    source = tmp_path / "input.json"
    source.write_text("{}")
    with pytest.raises(plans.PlanRegistryError, match="locked planning input"):
        plans.admit_card_manifest(source, tmp_path / "working", expected_sha256="0" * 64)
    assert not (tmp_path / "working").exists()


def deferral_fixture(tmp_path):
    base, overlay, path, proof = fixture(tmp_path, status="partial_verified")
    criterion = overlay["cards"]["BASE-001"]["acceptance"][0]["criterion"]
    overlay["cards"]["BASE-001"]["acceptance"][0]["result"] = "DEFERRED"
    path.write_text(json.dumps(overlay))
    context = authority(tmp_path, requested_status="partial_verified")
    context.criterion_deferrals[("BASE-001", criterion)] = plans.CriterionDeferral(
        "BASE-001", criterion, "campaign-test", "a" * 64,
        base["ledger_sha256"], "explicit fixture owner decision", "criterion reserved for later owner reconciliation",
    )
    context.additional_requirements["BASE-001"] = (
        lambda paths: len(paths) == 1 and json.loads(paths[0].read_text())["verified"] is True,
    )
    return base, overlay, path, proof, context


def test_owner_deferral_is_not_acceptance_but_current_checks_can_permit_campaign_order(tmp_path):
    base, overlay, path, proof, context = deferral_fixture(tmp_path)
    view = plans.apply_status(base, path, authority=context)
    assert view["cards"][0]["status"] == "partial_verified"
    assert view["campaign_conformant_cards"] == ["BASE-001"]
    assert view["owner_deferred_criteria"]["BASE-001"] == ["snapshot is independently verified"]
    assert plans.ready_cards(view) == ["MIG-001"]
    assert view["status_summary"].get("accepted", 0) == 0


def test_overlay_cannot_self_defer_criteria(tmp_path):
    base, overlay, path, proof, context = deferral_fixture(tmp_path)
    context.criterion_deferrals.clear()
    with pytest.raises(plans.PlanRegistryError, match="exact admitted owner authority"):
        plans.apply_status(base, path, authority=context)


def test_all_deferred_criteria_require_actual_current_requirement_checks(tmp_path):
    base, overlay, path, proof, context = deferral_fixture(tmp_path)
    context.additional_requirements.clear()
    with pytest.raises(plans.PlanRegistryError, match="independent current requirements"):
        plans.apply_status(base, path, authority=context)


def test_deferred_card_cannot_hide_failed_current_requirements(tmp_path):
    base, overlay, path, proof, context = deferral_fixture(tmp_path)
    proof.write_text('{"verified":false}')
    overlay["cards"]["BASE-001"]["evidence"][0]["sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
    path.write_text(json.dumps(overlay))
    with pytest.raises(plans.PlanRegistryError, match="independent current requirements"):
        plans.apply_status(base, path, authority=context)


def test_deferred_literal_criterion_prevents_full_acceptance(tmp_path):
    base, overlay, path, proof, context = deferral_fixture(tmp_path)
    overlay["cards"]["BASE-001"]["status"] = "accepted"
    path.write_text(json.dumps(overlay))
    context.owner_decisions["owner-event-1"] = authority(tmp_path).owner_decisions["owner-event-1"]
    with pytest.raises(plans.PlanRegistryError, match="every locked acceptance criterion"):
        plans.apply_status(base, path, authority=context)


@pytest.mark.parametrize("field,value", [("campaign_id", "other"), ("source_revision", "b" * 64), ("base_ledger_sha256", "c" * 64), ("criterion", "other criterion"), ("reason", "")])
def test_deferral_binding_must_match_exact_owner_scope(tmp_path, field, value):
    from dataclasses import replace
    base, overlay, path, proof, context = deferral_fixture(tmp_path)
    key = next(iter(context.criterion_deferrals))
    context.criterion_deferrals[key] = replace(context.criterion_deferrals[key], **{field: value})
    with pytest.raises(plans.PlanRegistryError, match="exact admitted owner authority"):
        plans.apply_status(base, path, authority=context)


def test_campaign_conformance_is_rechecked_on_read(tmp_path):
    base, overlay, path, proof, context = deferral_fixture(tmp_path)
    view = plans.apply_status(base, path, authority=context)
    proof.write_text('{"verified":false}')
    with pytest.raises(plans.PlanRegistryError):
        plans.ready_cards(view)


def test_a_blocked_accepted_parent_does_not_unlock_descendants(tmp_path):
    from dataclasses import replace
    base, overlay, path, proof = fixture(tmp_path)
    context = replace(authority(tmp_path), blocking_cards=frozenset({"BASE-001"}))
    view = plans.apply_status(base, path, authority=context)
    assert plans.ready_cards(view) == []
