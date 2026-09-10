from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from runtime.contracts import validate_instance
from runtime.cli import main
from runtime.external_capability_provider import (
    apply_selective_stage,
    compare_session_parity,
    external_catalog_status,
    govern_hook_invocation,
    hydrate_external_metadata,
    load_external_catalog,
    normalize_session_snapshot,
    plan_selective_stage,
    rank_execution_routes,
    revoke_selective_stage,
    search_external_candidates,
    validate_external_capability_orchestration,
)


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("parameter,value", [("max_records", True), ("max_records", 21),
                                            ("max_records", 1.5), ("max_bytes", True),
                                            ("max_bytes", float("inf"))])
def test_hydration_limits_reject_before_catalog_access(monkeypatch, parameter, value) -> None:
    from runtime import external_capability_provider as provider
    monkeypatch.setattr(provider, "load_external_catalog", lambda _: pytest.fail("catalog accessed before bounds"))
    with pytest.raises(ValueError):
        hydrate_external_metadata(ROOT, ["one"], **{parameter: value})


def test_hydration_accounts_for_all_requested_ids_after_oversized_record(monkeypatch) -> None:
    from runtime import external_capability_provider as provider
    rows = [{"id": "large", "summary": "x" * 4096}, {"id": "small", "summary": "small"}]
    monkeypatch.setattr(provider, "load_external_catalog", lambda _: {"records": rows})
    result = hydrate_external_metadata(ROOT, ["large", "missing", "small"], max_bytes=512)
    assert result["valid"] is False
    assert result["missing"] == ["missing"]
    assert [r["id"] for r in result["records"]] == ["small"]
    assert {r["id"]: r["status"] for r in result["outcomes"]} == {
        "large": "oversized", "missing": "missing", "small": "returned"
    }


def test_metadata_projection_excludes_nested_unknown_payloads(monkeypatch) -> None:
    from runtime import external_capability_provider as provider
    row = {"id": "one", "summary": "metadata", "extra": {"body": "never return imported source"}}
    monkeypatch.setattr(provider, "load_external_catalog", lambda _: {"records": [row]})
    result = hydrate_external_metadata(ROOT, ["one"])
    assert "never return imported source" not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["candidate_duplicate", "bundle_duplicate", "unknown_dependency", "record_count_boolean",
                                     "unknown_kind", "unknown_disposition", "candidate_kind_mismatch"])
def test_catalog_rejects_ambiguous_denominators_and_unknown_references(monkeypatch, mutation) -> None:
    from runtime import external_capability_provider as provider
    paths = [provider.CATALOG_PATH, provider.CANDIDATE_PATH, provider.BUNDLE_PATH, provider.LICENSE_PATH]
    documents = {p: json.loads((ROOT / p).read_text(encoding="utf-8")) for p in paths}
    if mutation == "candidate_duplicate":
        d = documents[provider.CANDIDATE_PATH]
        d["capabilities"].append(dict(d["capabilities"][0]))
        d["capability_count"] += 1
    elif mutation == "bundle_duplicate":
        d = documents[provider.BUNDLE_PATH]
        d["packages"].append(dict(d["packages"][0]))
        d["package_count"] += 1
    elif mutation == "unknown_dependency":
        documents[provider.CATALOG_PATH]["records"][0]["dependencies"] = ["missing-contract-owner"]
    elif mutation == "record_count_boolean":
        documents[provider.CATALOG_PATH]["record_count"] = True
    elif mutation == "unknown_kind":
        documents[provider.CATALOG_PATH]["records"][0]["kind"] = "unknown"
    elif mutation == "unknown_disposition":
        documents[provider.CATALOG_PATH]["records"][0]["disposition"] = "active"
    else:
        documents[provider.CATALOG_PATH]["records"][0]["kind"] = "existing_pacify_skill"
    monkeypatch.setattr(provider, "load_json_object", lambda path, **kwargs: documents[path.relative_to(ROOT.resolve())])
    with pytest.raises(ValueError):
        load_external_catalog(ROOT)


@pytest.mark.parametrize("field,value", [("project_id", {"secret": "hidden"}),
                                        ("artifact_refs", "not-an-array"),
                                        ("branch", {"body": "hidden"}),
                                        ("extra", {"password": "hidden"})])
def test_session_snapshot_rejects_coercion_and_nested_payloads(field, value) -> None:
    payload = {"project_id": "project", "session_id": "session", "agent_id": "agent",
               "state": "active", "artifact_refs": [], "evidence_refs": []}
    with pytest.raises(ValueError):
        normalize_session_snapshot("adapter", {**payload, field: value})


def test_stage_preview_rejects_forged_path_identifier(tmp_path) -> None:
    from runtime.external_capability_provider import SelectiveStagePlan
    plan = SelectiveStagePlan("../../outside", "project", (), {}, (), ())
    with pytest.raises(ValueError, match="plan ID"):
        apply_selective_stage(tmp_path, plan, approval_evidence=["review"])


def commissioned_project(tmp_path: Path) -> Path:
    state = tmp_path / ".engineering-bootstrap/project-management/state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}\n", encoding="utf-8")
    return tmp_path


def bundle_ids() -> list[str]:
    payload = json.loads(
        (ROOT / "registry/external_skill_bundles.json").read_text(encoding="utf-8")
    )
    return [item["id"] for item in payload["packages"]]


def json_value(value: object) -> object:
    return json.loads(json.dumps(value))


def test_catalog_is_metadata_only_and_all_candidates_are_deferred() -> None:
    catalog = load_external_catalog(ROOT)
    status = external_catalog_status(ROOT)
    assert (
        catalog["record_count"],
        catalog["candidate_count"],
        catalog["bundle_count"],
    ) == (486, 30, 12)
    assert status["metadata_only"] is True
    assert status["canonical"] is False
    assert status["authority"] == "none"
    assert status["active_registry_mutation"] is False
    assert all(
        item["status"] in {"mapped_deferred", "reference_only"}
        for item in catalog["candidates"]
    )
    assert all(item["activation"] == "candidate_only" for item in catalog["candidates"])


def test_metadata_search_and_bounded_hydration_never_load_source_bodies() -> None:
    result = search_external_candidates(ROOT, "agent harness performance", limit=4)
    assert result["results"]
    assert all(
        item["metadata_only"] and item["admission_required"]
        for item in result["results"]
    )
    identifiers = [item["id"] for item in result["results"]]
    hydrated = hydrate_external_metadata(
        ROOT, identifiers, max_records=2, max_bytes=8_192
    )
    assert len(hydrated["records"]) <= 2
    assert hydrated["used_bytes"] <= 8_192
    assert hydrated["source_bodies_loaded"] == 0
    assert hydrated["authority_granted"] is False
    assert all(
        "body" not in item and "content" not in item and "raw_source" not in item
        for item in hydrated["records"]
    )


def test_selective_staging_is_deterministic_review_gated_and_project_local(
    tmp_path: Path,
) -> None:
    project = commissioned_project(tmp_path)
    selected = bundle_ids()
    first = plan_selective_stage(
        ROOT, project, project_id="project-one", bundle_ids=reversed(selected)
    )
    second = plan_selective_stage(
        ROOT, project, project_id="project-one", bundle_ids=selected
    )
    assert first == second
    assert not first.unresolved_dependencies
    assert not first.collisions
    validate_instance(
        json_value(asdict(first)),
        ROOT / "contracts/external_capabilities/selective-stage-plan.schema.json",
    )

    preview = apply_selective_stage(project, first, approval_evidence=["review-1"])
    assert preview["valid"] and preview["applied"] is False
    assert not (project / ".engineering-bootstrap/external-capabilities").exists()
    missing_review = apply_selective_stage(
        project, first, approval_evidence=[], apply=True
    )
    assert missing_review["valid"] is False

    applied = apply_selective_stage(
        project, first, approval_evidence=["review-1"], apply=True
    )
    receipt = project / applied["receipt"]
    assert applied["applied"] is True and receipt.is_file()
    assert not (project / "registry/skill_catalog.toml").exists()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["state"] == "staged_candidate"
    assert payload["authority_granted"] is False
    assert payload["active_registry_mutation"] is False

    revoked = revoke_selective_stage(
        project, first.plan_id, evidence=["review-2"], apply=True
    )
    assert revoked["applied"] is True
    assert receipt.is_file()
    assert (project / revoked["receipt"]).is_file()


def test_selective_stage_reports_collisions(tmp_path: Path) -> None:
    project = commissioned_project(tmp_path)
    identifier = bundle_ids()[0]
    (project / ".px/skills" / identifier).mkdir(parents=True)
    plan = plan_selective_stage(
        ROOT, project, project_id="project-one", bundle_ids=[identifier]
    )
    assert plan.collisions == (identifier,)
    result = apply_selective_stage(
        project, plan, approval_evidence=["review"], apply=True
    )
    assert result["valid"] is False
    assert result["applied"] is False


def test_hook_governance_denies_recursion_depth_and_missing_authority() -> None:
    profile = {
        "id": "bounded-check",
        "enabled": True,
        "events": ["before_write"],
        "required_authorities": ["write_workspace"],
        "max_depth": 1,
    }
    denied = govern_hook_invocation(
        profile,
        event="before_write",
        granted_authorities=[],
        invocation_chain=["bounded-check"],
    )
    assert set(denied.reason_codes) == {
        "authority_missing",
        "depth_limit",
        "reentrant_hook",
    }
    allowed = govern_hook_invocation(
        profile,
        event="before_write",
        granted_authorities=["write_workspace"],
    )
    assert allowed.allowed is True
    assert allowed.authority_granted is False
    validate_instance(
        json_value(asdict(allowed)),
        ROOT / "contracts/external_capabilities/hook-decision.schema.json",
    )


def test_session_adapter_rejects_sensitive_fields_and_proves_parity() -> None:
    payload = {
        "project_id": "project-one",
        "session_id": "session-one",
        "agent_id": "agent-one",
        "state": "active",
        "artifact_refs": ["artifact-b", "artifact-a"],
        "evidence_refs": ["evidence-one"],
    }
    left = normalize_session_snapshot("adapter-a", payload)
    right = normalize_session_snapshot("adapter-b", payload)
    assert compare_session_parity(left, right)["valid"] is True
    validate_instance(
        left, ROOT / "contracts/external_capabilities/session-snapshot.schema.json"
    )
    with pytest.raises(ValueError, match="sensitive"):
        normalize_session_snapshot("adapter-a", {**payload, "api_key": "do-not-copy"})


def test_route_economics_applies_quality_safety_authority_and_privacy_first() -> None:
    routes = [
        {
            "id": "unsafe-cheap",
            "quality": 0.99,
            "cost": 0.01,
            "latency_ms": 1,
            "authority_valid": True,
            "safety_valid": False,
            "privacy_classes": ["internal"],
        },
        {
            "id": "low-quality",
            "quality": 0.4,
            "cost": 0.01,
            "latency_ms": 1,
            "authority_valid": True,
            "safety_valid": True,
            "privacy_classes": ["internal"],
        },
        {
            "id": "privacy-mismatch",
            "quality": 0.99,
            "cost": 0.01,
            "latency_ms": 1,
            "authority_valid": True,
            "safety_valid": True,
            "privacy_classes": ["public"],
        },
        {
            "id": "safe",
            "quality": 0.9,
            "cost": 0.4,
            "latency_ms": 100,
            "authority_valid": True,
            "safety_valid": True,
            "privacy_classes": ["internal"],
        },
    ]
    result = rank_execution_routes(
        routes,
        minimum_quality=0.8,
        maximum_cost=1.0,
        maximum_latency_ms=1_000,
        privacy_class="internal",
    )
    assert result["selected"]["id"] == "safe"
    assert result["quality_precedes_economics"] is True
    reasons = {item["id"]: item["reasons"] for item in result["rejected"]}
    assert "safety_invalid" in reasons["unsafe-cheap"]
    assert "quality_below_minimum" in reasons["low-quality"]
    assert "privacy_incompatible" in reasons["privacy-mismatch"]
    validate_instance(
        result, ROOT / "contracts/external_capabilities/routing-economics.schema.json"
    )


def test_candidate_contract_and_workflow_are_executable() -> None:
    catalog = load_external_catalog(ROOT)
    validate_instance(
        catalog["candidates"][0],
        ROOT
        / "contracts/external_capabilities/external-capability-candidate.schema.json",
    )
    result = validate_external_capability_orchestration(ROOT)
    assert result["valid"], result["errors"]


def test_external_capability_cli_exposes_metadata_without_hydrating_bodies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--root", str(ROOT), "external-capability", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["record_count"] == 486
    assert status["active_registry_mutation"] is False
    assert (
        main(
            [
                "--root",
                str(ROOT),
                "external-capability",
                "search",
                "--query",
                "session fabric",
                "--limit",
                "2",
            ]
        )
        == 0
    )
    search = json.loads(capsys.readouterr().out)
    assert search["results"]
    assert all(item["metadata_only"] for item in search["results"])
