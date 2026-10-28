from __future__ import annotations

import json
from pathlib import Path

import pytest

"""PX-GAP-0011: the admitted planning corpus and the v1 punch-card ledger.

Covers locked cards BASE-003 and BASE-004: archives are fingerprinted by
content, identical payloads collapse to one admitted requirement source, the
unique-payload variance from BASE-003's expectation is reported rather than
reconciled, and every card declares authority with a resolvable acyclic
dependency graph.
"""

from runtime.plan_registry import (
    CORPUS_SCHEMA,
    EXPECTED_UNIQUE_PAYLOADS,
    LEDGER_SCHEMA,
    PlanRegistryError,
    admit_corpus,
    apply_status,
    build_card_ledger,
    fingerprint_archive,
    load_cards,
    ready_cards,
    validate_ledger,
    write_corpus,
    write_card_ledger,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CARD_MANIFEST = REPO_ROOT / "registry/planning/rev1xx/be9857ee72e6a91d6bb70c8088a0d52749be84d3a68ad6e84b93e2a464f90ff3.json"


def _archive(root: Path, name: str, files: dict[str, str]) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return directory


def test_fingerprint_is_content_addressed_and_order_independent(tmp_path: Path) -> None:
    left = _archive(tmp_path / "a", "one", {"x.txt": "alpha", "y/z.txt": "beta"})
    right = _archive(tmp_path / "b", "two", {"y/z.txt": "beta", "x.txt": "alpha"})
    assert fingerprint_archive(left).payload_sha256 == fingerprint_archive(right).payload_sha256


def test_fingerprint_changes_with_content_and_with_layout(tmp_path: Path) -> None:
    base = _archive(tmp_path / "a", "one", {"x.txt": "alpha"})
    same = _archive(tmp_path / "b", "two", {"x.txt": "alpha"})
    other = _archive(tmp_path / "c", "three", {"x.txt": "alpha2"})
    moved = _archive(tmp_path / "d", "four", {"sub/x.txt": "alpha"})
    digest = fingerprint_archive(base).payload_sha256
    assert fingerprint_archive(same).payload_sha256 == digest
    assert fingerprint_archive(other).payload_sha256 != digest
    # Layout is part of identity, so a relocated identical payload is NOT
    # collapsed. That is the conservative direction.
    assert fingerprint_archive(moved).payload_sha256 != digest


def test_identical_payloads_collapse_to_one_admitted_requirement_source(tmp_path: Path) -> None:
    files = {"plan.md": "same payload"}
    _archive(tmp_path, "Original", files)
    _archive(tmp_path, "Original (1)", files)
    _archive(tmp_path, "Different", {"plan.md": "different payload"})
    report = admit_corpus(tmp_path)
    assert report["archive_count"] == 3
    assert report["unique_payload_count"] == 2
    assert report["duplicate_payload_count"] == 1
    duplicate = next(
        entry for entry in report["admitted_sources"] if entry["duplicate_copies"]
    )
    assert duplicate["admitted_source"] == "Original"
    assert duplicate["duplicate_copies"] == ["Original (1)"]
    # The duplicate is recorded as a copy of one source, never as a new source.
    assert len(report["admitted_sources"]) == report["unique_payload_count"]


def test_unique_payload_variance_is_reported_not_reconciled(tmp_path: Path) -> None:
    _archive(tmp_path, "Only", {"a.md": "one"})
    report = admit_corpus(tmp_path)
    assert report["expected_unique_payload_count"] == EXPECTED_UNIQUE_PAYLOADS
    assert report["unique_payload_matches_expectation"] is False
    assert report["unique_payload_count"] == 1


def test_corpus_artifact_is_digest_bound(tmp_path: Path) -> None:
    _archive(tmp_path, "Pack", {"a.md": "content"})
    target = write_corpus(tmp_path, tmp_path / "repo")
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body["schema_version"] == CORPUS_SCHEMA
    stored = body["artifact_sha256"]
    payload = {key: value for key, value in body.items() if key != "artifact_sha256"}
    import hashlib

    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert stored == expected


def test_every_real_card_declares_authority_and_is_never_ownerless() -> None:
    entries = load_cards(CARD_MANIFEST)
    assert len(entries) == 60
    # Ownerless is the union of BOTH authority fields being empty, not a missing
    # single `owner` key. An earlier parse assumed a single key and wrongly
    # reported all 60 cards as ownerless.
    for entry in entries:
        assert entry.existing_owners or entry.candidate_new_owners, entry.card_id


def test_ledger_is_acyclic_with_resolvable_dependencies_and_no_ownerless_cards() -> None:
    ledger = build_card_ledger(load_cards(CARD_MANIFEST))
    report = validate_ledger(ledger)
    assert report["valid"], report["problems"]
    assert ledger["ownerless_cards"] == []
    assert ledger["card_count"] == 60
    assert len(ledger["waves"]) == 12
    assert sorted(ledger["topological_order"]) == sorted(
        card["card_id"] for card in ledger["cards"]
    )


def test_topological_order_places_every_dependency_before_its_dependent() -> None:
    ledger = build_card_ledger(load_cards(CARD_MANIFEST))
    position = {card_id: index for index, card_id in enumerate(ledger["topological_order"])}
    for card in ledger["cards"]:
        for dependency in card["depends_on"]:
            assert position[dependency] < position[card["card_id"]], card["card_id"]


def test_unknown_dependency_fails_closed() -> None:
    entries = load_cards(CARD_MANIFEST)
    broken = [
        entry.__class__(**{**vars(entry), "depends_on": ("NOPE-999",)}) if entry.card_id == "SEM-001" else entry
        for entry in entries
    ]
    with pytest.raises(PlanRegistryError, match="unknown card NOPE-999"):
        build_card_ledger(broken)


def test_dependency_cycle_fails_closed() -> None:
    entries = load_cards(CARD_MANIFEST)
    left = entries[0]
    right = entries[1]
    mutated = [
        entry.__class__(
            **{
                **vars(entry),
                "depends_on": (right.card_id,) if entry.card_id == left.card_id else (left.card_id,),
            }
        )
        for entry in entries[:2]
    ] + entries[2:]
    with pytest.raises(PlanRegistryError, match="cycle|unknown card"):
        build_card_ledger(mutated)


def test_ownerless_card_fails_validation() -> None:
    entries = load_cards(CARD_MANIFEST)
    stripped = [
        entry.__class__(**{**vars(entry), "owner": "", "existing_owners": (), "candidate_new_owners": ()})
        for entry in entries
    ]
    ledger = build_card_ledger(stripped)
    assert ledger["ownerless_cards"]
    report = validate_ledger(ledger)
    assert report["valid"] is False
    assert any("ownerless" in problem for problem in report["problems"])


def test_only_baseline_entry_cards_are_dependency_ready() -> None:
    """With nothing implemented, only the entry cards have satisfied dependencies."""
    ledger = build_card_ledger(load_cards(CARD_MANIFEST))
    ready = ready_cards(ledger)
    assert "BASE-001" in ready
    assert "SEM-001" not in ready  # depends on BASE-004


def test_ledger_artifact_is_digest_bound_and_stable(tmp_path: Path) -> None:
    first = write_card_ledger(CARD_MANIFEST, tmp_path)
    second = write_card_ledger(CARD_MANIFEST, tmp_path)
    assert first.read_bytes() == second.read_bytes(), "ledger build must be deterministic"
    body = json.loads(first.read_text(encoding="utf-8"))
    assert body["schema_version"] == LEDGER_SCHEMA


def test_current_corpus_accounts_root_files_and_duplicate_sources(tmp_path):
    from runtime.plan_registry import inventory_current_corpus

    (tmp_path / "root.md").write_bytes(b"same requirement")
    _archive(tmp_path, "Pack", {"copy.md": "same requirement", "other.md": "different"})
    report = inventory_current_corpus(tmp_path)
    assert report["file_count"] == 3
    assert report["unique_content_count"] == 2
    assert report["byte_count"] == sum(row["bytes"] for row in report["files"])
    source = next(row for row in report["content_sources"] if len(row["paths"]) == 2)
    assert source["paths"] == ["Pack/copy.md", "root.md"]
    assert report["historical_expectations"] == "reference_only"
    assert report["admission_role"] == "candidate_inventory_only"


def test_unbound_partial_status_overlay_cannot_unblock_dependents(tmp_path: Path) -> None:
    ledger = build_card_ledger(load_cards(CARD_MANIFEST))
    assert ready_cards(ledger) == ["BASE-001"]
    status = tmp_path / "status.json"
    status.write_text(
        json.dumps(
            {
                "cards": {
                    "BASE-001": {"status": "narrowly_verified", "evidence": ["r"]},
                    "BASE-002": {"status": "narrowly_verified"},
                    "BASE-003": {"status": "narrowly_verified"},
                    "BASE-004": {"status": "narrowly_verified"},
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PlanRegistryError, match="status authority is required"):
        apply_status(ledger, status)
    assert ready_cards(ledger) == ["BASE-001"]



def test_unbound_overlay_with_unknown_cards_is_rejected(tmp_path: Path) -> None:
    ledger = build_card_ledger(load_cards(CARD_MANIFEST))
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"cards": {"NOPE-001": {"status": "closed"}}}), encoding="utf-8")
    with pytest.raises(PlanRegistryError, match="status authority is required"):
        apply_status(ledger, status)


def test_status_is_not_forgeable_by_regenerating_the_ledger(tmp_path: Path) -> None:
    """Status lives outside the generated ledger, so regeneration cannot erase it."""
    status = tmp_path / "status.json"
    status.write_text(
        json.dumps({"cards": {"BASE-001": {"status": "narrowly_verified"}}}), encoding="utf-8"
    )
    assert status.is_file()
    ledger = build_card_ledger(load_cards(CARD_MANIFEST))
    # A freshly generated ledger carries no status at all.
    assert all("status" not in card for card in ledger["cards"])

def test_current_corpus_admission_is_content_addressed_and_cli_reachable(tmp_path, capsys):
    from runtime.cli import main
    from runtime.plan_registry import admit_current_corpus

    reference = tmp_path / "references"
    _archive(reference, "Pack", {"plan.md": "fresh requirement"})
    root = tmp_path / "working"
    (root / "policies").mkdir(parents=True)
    (root / "policies/rev1xx-validation.json").write_bytes((REPO_ROOT / "policies/rev1xx-validation.json").read_bytes())
    result = admit_current_corpus(reference, root)
    data = (root / result["path"]).read_bytes()
    assert admit_current_corpus(reference, root) == result
    assert (root / result["path"]).read_bytes() == data
    assert main(["--root", str(root), "plan-corpus", "--reference-root", str(reference), "--admit"]) == 0
    assert json.loads(capsys.readouterr().out)["corpus_sha256"] == result["corpus_sha256"]
    (root / result["path"]).write_bytes(b"tampered")
    with pytest.raises(PlanRegistryError, match="bytes differ"):
        admit_current_corpus(reference, root)


def test_current_corpus_empty_input_and_capture_drift_fail_closed(tmp_path, monkeypatch):
    import runtime.plan_registry as owner

    with pytest.raises(PlanRegistryError, match="empty"):
        owner.inventory_current_corpus(tmp_path)
    reference = tmp_path / "references"
    _archive(reference, "Pack", {"plan.md": "fresh"})
    root = tmp_path / "working"
    (root / "policies").mkdir(parents=True)
    (root / "policies/rev1xx-validation.json").write_bytes((REPO_ROOT / "policies/rev1xx-validation.json").read_bytes())
    actual = owner.inventory_current_corpus
    calls = 0
    def changing(path):
        nonlocal calls
        calls += 1
        result = actual(path)
        if calls == 1:
            (reference / "Pack/plan.md").write_text("changed")
        return result
    monkeypatch.setattr(owner, "inventory_current_corpus", changing)
    with pytest.raises(PlanRegistryError, match="changed during"):
        owner.admit_current_corpus(reference, root)
    assert not (root / "registry").exists()


def _current_requirement_fixture(tmp_path):
    import hashlib
    root = tmp_path / "work"
    (root / "policies").mkdir(parents=True)
    (root / "registry").mkdir()
    (root / "policies/rev1xx-validation.json").write_bytes((REPO_ROOT / "policies/rev1xx-validation.json").read_bytes())
    (root / "registry/punch_card_ledger.json").write_bytes((REPO_ROOT / "registry/punch_card_ledger.json").read_bytes())
    sources = []
    for name in ["source-12b284fba674186ae3f3e50b077fe9b2368033c2e41ae519abee674ca3e20c59.json",
                 "source-73a977da37db116874e35247b26f90b499a90d74c7b592e988a3e27649c32429.json",
                 "requirement-routing.json"]:
        target = tmp_path / name
        target.write_bytes((REPO_ROOT / "registry/planning/rev1xx" / name).read_bytes())
        sources.append(target)
    return root, {"trace_path": sources[0], "candidate_path": sources[1], "routing_path": sources[2],
                  "trace_sha256": hashlib.sha256(sources[0].read_bytes()).hexdigest(),
                  "candidate_sha256": hashlib.sha256(sources[1].read_bytes()).hexdigest()}


def test_current_requirements_preserve_all_source_obligations_and_normal_cli(tmp_path, capsys):
    from runtime.plan_registry import admit_current_requirement_trace, requirement_report
    from runtime.cli import main
    root, arguments = _current_requirement_fixture(tmp_path)
    result = admit_current_requirement_trace(root, **arguments)
    assert result["requirements"] == 118 and result["candidates"] == 39 and result["external_findings"] == 79
    assert result["implementation_verified"] == 0
    assert admit_current_requirement_trace(root, **arguments) == result
    policy_path = root / "policies/rev1xx-validation.json"
    policy = json.loads(policy_path.read_text())
    policy["requirement_trace"] = {"path": result["path"], "sha256": result["sha256"]}
    policy_path.write_text(json.dumps(policy))
    report = requirement_report(root)
    assert report["valid"] and report["implementation_verified"] == 0
    assert main(["--root", str(root), "plan-requirements"]) == 0
    assert json.loads(capsys.readouterr().out)["requirements"] == 118
    body = json.loads((root / result["path"]).read_text())
    assert len({row["requirement_id"] for row in body["records"]}) == 118
    candidates = [row for row in body["records"] if "candidate_requirements" in row]
    assert len(candidates) == 39
    assert all(row["candidate_requirements"]["acceptance"] for row in candidates)
    assert all(row["implementation_status"] == "pending" and row["acceptance_evidence"] == [] for row in body["records"])
    assert "Git" in next(row for row in candidates if row["source_id"] == "P0-08")["owner_exception"]


@pytest.mark.parametrize("mutation", ["missing_assignment", "future_wave", "duplicate_source", "missing_intent", "missing_landing", "missing_candidate", "hash_mismatch"])
def test_current_requirement_admission_rejects_orphans_and_inconsistent_sources(tmp_path, mutation):
    import hashlib
    from runtime.plan_registry import admit_current_requirement_trace
    root, arguments = _current_requirement_fixture(tmp_path)
    trace = json.loads(arguments["trace_path"].read_text())
    routing = json.loads(arguments["routing_path"].read_text())
    matrix = json.loads(arguments["candidate_path"].read_text())
    first = trace["records"][0]
    if mutation == "missing_assignment": routing["bindings"].pop(first["source_id"])
    elif mutation == "future_wave": routing["bindings"][first["source_id"]] = ["OPT-001"]
    elif mutation == "duplicate_source": trace["records"][1] = first
    elif mutation == "missing_intent": first["title"] = ""
    elif mutation == "missing_landing": first["target_paths"] = []
    elif mutation == "missing_candidate": matrix["candidates"].pop()
    else: arguments["trace_sha256"] = "0" * 64
    for key, document in [("trace_path", trace), ("candidate_path", matrix), ("routing_path", routing)]:
        arguments[key].write_text(json.dumps(document))
    if mutation != "hash_mismatch": arguments["trace_sha256"] = hashlib.sha256(arguments["trace_path"].read_bytes()).hexdigest()
    arguments["candidate_sha256"] = hashlib.sha256(arguments["candidate_path"].read_bytes()).hexdigest()
    with pytest.raises(PlanRegistryError): admit_current_requirement_trace(root, **arguments)
    assert not list((root / "registry").rglob("requirements-*.json"))


def test_requirement_report_rejects_rehashed_completion_claims_and_source_tampering(tmp_path):
    import hashlib
    from runtime.plan_registry import admit_current_requirement_trace, requirement_report, _digest, _canonical
    root, arguments = _current_requirement_fixture(tmp_path)
    result = admit_current_requirement_trace(root, **arguments)
    path = root / result["path"]
    body = json.loads(path.read_text())
    body["records"][0]["implementation_status"] = "accepted"
    body.pop("trace_sha256")
    body["trace_sha256"] = _digest(body)
    path.write_text(_canonical(body) + "\n", encoding="utf-8")
    policy_path = root / "policies/rev1xx-validation.json"
    policy = json.loads(policy_path.read_text())
    policy["requirement_trace"] = {"path": result["path"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(PlanRegistryError, match="differs from admitted"):
        requirement_report(root)
    source = root / body["inputs"][0]["path"]
    source.write_bytes(b"{}")
    with pytest.raises(PlanRegistryError, match="source hash mismatch"):
        requirement_report(root)


def test_fresh_release_boundary_ignores_legacy_state_and_preserves_terminal_bytes(tmp_path):
    from runtime.release_campaign import clear_release_identity, release_campaign_status
    from runtime.release_campaign import STATE_PATH

    policy = {"schema_version": "px.validation-basis/1.0", "basis": "current_implementation",
              "authority": "OWNER-FRESH-VALIDATION-001", "campaign_id": "fresh-repair"}
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/rev1xx-validation.json").write_text(json.dumps(policy))
    legacy = tmp_path / STATE_PATH
    legacy.parent.mkdir(parents=True)
    terminal_bytes = b'{"state":"certified","campaign_id":"historic-release","unavailable_historical_details":true}'
    legacy.write_bytes(terminal_bytes)
    repair = legacy.parent / "repair-campaign.json"
    repair.write_text(json.dumps({"campaign_id": "fresh-repair", "phase": "repair"}))
    before = release_campaign_status(tmp_path)
    assert before["state"] == "missing" and before["valid"] is False
    current = clear_release_identity(tmp_path, campaign_id="fresh-release")
    assert current["valid"] and current["state"] == "cleared"
    assert current["path"] != STATE_PATH.as_posix()
    assert all(stage["status"] == "pending" for stage in current["stages"].values())
    assert legacy.read_bytes() == terminal_bytes
    assert clear_release_identity(tmp_path, campaign_id="fresh-release")["path"] == current["path"]


def test_fresh_release_boundary_rejects_unadmitted_policy(tmp_path):
    from runtime.release_campaign import release_campaign_status
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/rev1xx-validation.json").write_text(json.dumps({"basis": "current_implementation", "authority": "unadmitted"}))
    with pytest.raises(ValueError): release_campaign_status(tmp_path)


def test_fresh_repository_context_requires_current_custody_and_no_historical_artifacts(tmp_path):
    import hashlib
    from runtime.plan_registry import admit_current_requirement_trace
    from runtime.release_campaign import clear_release_identity
    from runtime.release_repository_context import validate_release_gate_repository_context
    from runtime.source_freeze import freeze_source

    root, arguments = _current_requirement_fixture(tmp_path)
    trace = admit_current_requirement_trace(root, **arguments)
    policy_path = root / "policies/rev1xx-validation.json"
    policy = json.loads(policy_path.read_text())
    policy["requirement_trace"] = {"path": trace["path"], "sha256": trace["sha256"]}
    policy_path.write_text(json.dumps(policy))
    processing = root / ".agentic_engineering_os_px/processing-order"
    processing.mkdir(parents=True)
    (processing / "repair-campaign.json").write_text(json.dumps({"campaign_id": policy["campaign_id"], "phase": "repair"}))
    clear_release_identity(root, campaign_id="fresh-context")
    capture = freeze_source(root, freeze_id="fresh-context", current_campaign=True)
    anchor_path = root / capture.receipt["receipt_path"]
    policy["source_anchor"] = {"path": capture.receipt["receipt_path"], "sha256": hashlib.sha256(anchor_path.read_bytes()).hexdigest()}
    policy_path.write_text(json.dumps(policy))
    report = validate_release_gate_repository_context(root)
    assert report["valid"], report["errors"]
    assert report["historical_prerequisites"] is False
    assert report["git_acceptance"] == {"state": "deferred_by_owner", "satisfied": False}
    assert ".git" not in report["required"]
    assert not (root / ".git").exists()
    assert not (root / "evidence/externalized-payload-index.json").exists()
    archive = root / capture.receipt["archive"]["path"]
    archive.write_bytes(archive.read_bytes() + b"tampered")
    invalid = validate_release_gate_repository_context(root)
    assert invalid["valid"] is False and any("archive hash differs" in error for error in invalid["errors"])


def test_fresh_release_mutation_rejects_other_repair_campaign(tmp_path):
    from runtime.release_campaign import clear_release_identity, release_state_relative
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/rev1xx-validation.json").write_text(json.dumps({
        "schema_version": "px.validation-basis/1.0", "basis": "current_implementation",
        "authority": "OWNER-FRESH-VALIDATION-001", "campaign_id": "current-owner"}))
    processing = tmp_path / ".agentic_engineering_os_px/processing-order"
    processing.mkdir(parents=True)
    (processing / "repair-campaign.json").write_text('{"campaign_id":"other-owner","phase":"repair"}')
    with pytest.raises(ValueError, match="does not match"):
        clear_release_identity(tmp_path, campaign_id="new-release")
    assert not (tmp_path / release_state_relative(tmp_path)).exists()


def _decision_fixture(tmp_path):
    import hashlib
    from runtime.plan_registry import admit_card_manifest, write_admitted_card_ledger
    root = tmp_path / "current"
    (root / "policies").mkdir(parents=True)
    (root / "policies/rev1xx-validation.json").write_text(json.dumps({
        "schema_version":"px.validation-basis/1.0", "basis":"current_implementation",
        "authority":"OWNER-FRESH-VALIDATION-001", "campaign_id":"decision-test"}))
    prior = hashlib.sha256(CARD_MANIFEST.read_bytes()).hexdigest()
    admit_card_manifest(CARD_MANIFEST, root, expected_sha256=prior)
    ledger = write_admitted_card_ledger(root, manifest_sha256=prior)
    old = ledger.read_bytes()
    changed = json.loads(CARD_MANIFEST.read_bytes())
    changed["cards"][0]["outcome"] += " Current explicit change."
    source = tmp_path / "new.json"
    source.write_text(json.dumps(changed), encoding="utf-8")
    new = hashlib.sha256(source.read_bytes()).hexdigest()
    admit_card_manifest(source, root, expected_sha256=new)
    adr = root / "docs/adr/current-decision.md"
    adr.parent.mkdir(parents=True)
    adr.write_text(f"# Current architecture decision\n\nPrior manifest: {prior}\nNew manifest: {new}\n\nChange the declared outcome; retained prior definitions remain reference only.\n", encoding="utf-8")
    return root, prior, new, ledger, old, source, adr


def test_current_foundation_probe_exercises_guards_without_changing_host_definitions(tmp_path):
    from runtime.plan_registry import _foundation_invariant_probe
    root, prior, _, ledger, before, _, _ = _decision_fixture(tmp_path)
    policy = json.loads((root / "policies/rev1xx-validation.json").read_text())
    result = _foundation_invariant_probe(root, root / "registry/planning/rev1xx" / (prior + ".json"), policy)
    assert result == {"decision_guard": True, "terminal_preservation": True, "release_isolation": True}
    assert ledger.read_bytes() == before
    assert not (root / ".git").exists()


def test_current_foundation_probe_detects_missing_decision_enforcement(tmp_path, monkeypatch):
    from runtime import plan_registry as plans
    root, prior, _, ledger, before, _, _ = _decision_fixture(tmp_path)
    policy = json.loads((root / "policies/rev1xx-validation.json").read_text())
    producer = plans.write_admitted_card_ledger
    calls = 0

    def unsafe_producer(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return producer(*args, **kwargs)
        return Path(args[0]) / plans.LEDGER_RELATIVE

    monkeypatch.setattr(plans, "write_admitted_card_ledger", unsafe_producer)
    with pytest.raises(PlanRegistryError, match="allowed an unapproved definition change"):
        plans._foundation_invariant_probe(root, root / "registry/planning/rev1xx" / (prior + ".json"), policy)
    assert ledger.read_bytes() == before


def test_architecture_definition_change_requires_admitted_adr_decision(tmp_path):
    from runtime.plan_registry import write_admitted_card_ledger
    root, _, new, ledger, old, _, _ = _decision_fixture(tmp_path)
    with pytest.raises(PlanRegistryError, match="admitted ADR/ledger decision"):
        write_admitted_card_ledger(root, manifest_sha256=new)
    assert ledger.read_bytes() == old
    assert not (root / "registry/planning/rev1xx/ledger-history").exists()


def test_current_architecture_decision_preserves_prior_and_survives_regeneration(tmp_path):
    import hashlib
    from runtime.plan_registry import admit_architecture_decision, write_admitted_card_ledger
    root, _, new, ledger, old, _, adr = _decision_fixture(tmp_path)
    binding = admit_architecture_decision(root, manifest_sha256=new,
        adr_path=adr.relative_to(root).as_posix(), rationale="Owner-authorized current outcome revision")
    write_admitted_card_ledger(root, manifest_sha256=new, decision=binding)
    body = json.loads(ledger.read_bytes())
    assert validate_ledger(body)["valid"]
    assert body["architecture_decision"] == binding
    assert (root / "registry/planning/rev1xx/ledger-history" / (hashlib.sha256(old).hexdigest()+".retained")).read_bytes() == old
    current = ledger.read_bytes()
    write_admitted_card_ledger(root, manifest_sha256=new)
    assert ledger.read_bytes() == current


def test_changed_adr_is_rejected_before_definition_publication(tmp_path):
    from runtime.plan_registry import admit_architecture_decision, write_admitted_card_ledger
    root, _, new, ledger, old, _, adr = _decision_fixture(tmp_path)
    binding = admit_architecture_decision(root, manifest_sha256=new,
        adr_path=adr.relative_to(root).as_posix(), rationale="Current change")
    adr.write_text(adr.read_text()+"\nChanged after admission.\n")
    with pytest.raises(PlanRegistryError, match="ADR bytes"):
        write_admitted_card_ledger(root, manifest_sha256=new, decision=binding)
    assert ledger.read_bytes() == old


def test_current_general_ledger_writer_cannot_bypass_decision_guard(tmp_path):
    root, _, _, ledger, old, source, _ = _decision_fixture(tmp_path)
    with pytest.raises(PlanRegistryError, match="admitted ADR/ledger decision"):
        write_card_ledger(source, root)
    assert ledger.read_bytes() == old


def test_same_admitted_definition_can_repair_corrupted_projection_without_new_decision(tmp_path):
    from runtime.plan_registry import write_admitted_card_ledger
    root, prior, _, ledger, old, _, _ = _decision_fixture(tmp_path)
    body = json.loads(old)
    body["card_count"] += 1
    ledger.write_text(json.dumps(body))
    write_admitted_card_ledger(root, manifest_sha256=prior)
    assert ledger.read_bytes() == old


@pytest.mark.parametrize("adr_path", ["../outside.md", "README.md", "docs/adr/missing.md"])
def test_decision_admission_requires_real_owned_adr(tmp_path, adr_path):
    from runtime.plan_registry import admit_architecture_decision
    root, _, new, ledger, old, _, _ = _decision_fixture(tmp_path)
    with pytest.raises((PlanRegistryError, OSError, ValueError)):
        admit_architecture_decision(root, manifest_sha256=new, adr_path=adr_path, rationale="Current change")
    assert ledger.read_bytes() == old


@pytest.mark.parametrize("terminal", ["certified", "failed", "active"])
def test_fresh_release_namespace_cannot_erase_terminal_state_from_other_repair(tmp_path, terminal):
    from runtime.release_campaign import clear_release_identity, release_state_relative, STAGES, _sha
    root, _, _, _, _, _, _ = _decision_fixture(tmp_path)
    processing = root / ".agentic_engineering_os_px/processing-order"
    processing.mkdir(parents=True)
    (processing / "repair-campaign.json").write_text(json.dumps({"campaign_id":"decision-test", "phase":"repair"}))
    clear_release_identity(root, campaign_id="invariant-reproduction")
    path = root / release_state_relative(root)
    body = json.loads(path.read_bytes())
    # A deliberately inconsistent namespace record tests rejection. These
    # simulated stage labels are never evidence of an actual build or install.
    body.update(state=terminal, apply_count=1, repair_campaign_id="other-repair")
    identity = {"schema_version":"px.release-identity-kernel/2.0",
                "campaign_id":body["campaign_id"], "repair_campaign_id":"other-repair"}
    identity["release_identity_sha256"] = _sha(identity)
    body["identity"] = identity
    body["stages"] = {name:{"status":("passed" if terminal=="certified" else "failed" if terminal=="failed" and index==0 else "pending"), "claim_id":None}
                      for index,name in enumerate(STAGES)}
    path.write_text(json.dumps(body), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        clear_release_identity(root, campaign_id="new-reproduction")
    assert path.read_bytes() == before
