from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from runtime import cybersecurity_provider as provider


ROOT = Path(__file__).resolve().parents[1]


def engagement(
    *,
    mode: str = "read_only",
    environment: str = "test",
    approved: bool = True,
    human: bool = True,
) -> dict[str, object]:
    return {
        "engagement_id": "eng-test-001",
        "requester": "test-operator",
        "purpose": "Behaviorally validate the security authority boundary.",
        "mode": mode,
        "environment": environment,
        "targets": ["asset-a"],
        "target_allowlist": ["asset-a"],
        "target_denylist": [],
        "authorization": {
            "status": "approved" if approved else "pending",
            "artifact_id": "auth-001" if approved else None,
            "approved_by": "human-reviewer" if approved else None,
            "valid_from": "2020-01-01T00:00:00Z",
            "valid_until": "2099-01-01T00:00:00Z",
            "rules_of_engagement": ["Only asset-a", "Stop on unexpected impact"],
        },
        "human_approval": human,
        "change_window": "approved-window",
        "rollback_plan": "Restore the captured pre-change state.",
        "cleanup_plan": "Remove test artifacts and verify absence.",
        "kill_switch": "Stop the governed session immediately.",
        "evidence_root": "evidence/security/eng-test-001",
    }


def test_catalog_domain_risk_and_lifecycle_denominators_reconcile() -> None:
    state = provider.load_security_provider(ROOT, load_graph=True)
    assert state["record_count"] == 817
    assert state["edge_count"] == 14_595
    assert sum(state["raw_counts"].values()) == 817
    assert sum(state["canonical_counts"].values()) == 817
    assert state["risk_counts"] == {"R0": 1, "R1": 332, "R2": 181, "R3": 157, "R4": 146}
    assert all(
        row["lifecycle_state"] == "candidate_external" for row in state["records"]
    )


def test_metadata_search_is_lazy_explainable_and_non_authorizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("archive opened")
        ),
    )
    result = provider.search_security_capabilities(
        ROOT, "MCP prompt injection tool poisoning", limit=4
    )
    assert result["source_bodies_loaded"] == 0
    assert result["authority_granted"] is False
    assert result["independent_paths"] == ["text", "domain", "alias", "framework"]
    assert (
        result["results"][0]["id"]
        == "external.cybersecurity.auditing-mcp-servers-for-tool-poisoning"
    )
    assert result["results"][0]["metadata_untrusted"] is True
    assert result["results"][0]["score_components"]
    assert result["descriptions_included"] is False
    assert "description" not in result["results"][0]


def test_external_security_descriptions_require_explicit_output_opt_in() -> None:
    result = provider.search_security_capabilities(
        ROOT,
        "MCP prompt injection tool poisoning",
        limit=1,
        include_descriptions=True,
    )
    assert result["descriptions_included"] is True
    assert isinstance(result["results"][0]["description"], str)


def test_provider_can_be_disabled_without_breaking_core() -> None:
    result = provider.search_security_capabilities(
        ROOT, "incident response", provider_enabled=False
    )
    assert result["valid"] is True
    assert result["results"] == []
    assert result["provider_disabled"] is True


@pytest.mark.parametrize(
    ("risk", "kwargs", "expected"),
    [
        ("R0", {}, "allow"),
        ("R1", {}, "allow_read_only"),
        ("R2", {"mode": "controlled_change"}, "allow"),
        ("R3", {"mode": "active_test"}, "allow"),
        (
            "R4",
            {"mode": "lab_simulation", "environment": "isolated_lab"},
            "allow_lab_only",
        ),
    ],
)
def test_authority_classes_have_distinct_bounded_modes(
    risk: str, kwargs: dict[str, object], expected: str
) -> None:
    decision = provider.evaluate_security_authority(
        risk,
        engagement(**kwargs),
        now=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    assert decision.decision == expected
    assert decision.authority_granted is False


def test_high_risk_fails_closed_without_authorization_and_approval() -> None:
    decision = provider.evaluate_security_authority(
        "R3",
        engagement(mode="active_test", approved=False, human=False),
        now=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    assert decision.decision == "deny"
    assert "written_authorization_not_approved" in decision.reasons
    assert "human_approval_missing" in decision.reasons


def test_active_production_and_R4_non_lab_requests_are_denied() -> None:
    r3 = provider.evaluate_security_authority(
        "R3",
        engagement(mode="active_test", environment="production"),
        now=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    r4 = provider.evaluate_security_authority(
        "R4",
        engagement(mode="lab_simulation", environment="test"),
        now=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    assert r3.decision == "deny"
    assert "active_production_denied_by_default" in r3.reasons
    assert r4.decision == "deny"
    assert "R4_isolated_lab_only" in r4.reasons


def test_target_scope_is_evaluated_per_target() -> None:
    request = engagement()
    request["targets"] = ["asset-a", "asset-b"]
    decision = provider.evaluate_security_authority("R1", request)
    assert decision.decision == "deny"
    assert "target_outside_allowlist" in decision.reasons


def test_execution_package_filters_authority_before_ranking() -> None:
    request = engagement(mode="read_only")
    result = provider.build_security_execution_package(
        ROOT, "credential access DPAPI", request, max_bodies=3
    )
    assert result["runtime_authority_granted"] is False
    assert result["provider_scripts_executable"] is False
    assert all(item["risk_class"] in {"R0", "R1"} for item in result["selected"])
    assert any(
        "read_only_mode_required" in item["reasons"]
        or "R4_isolated_lab_only" in item["reasons"]
        for item in result["rejected"]
    )


def test_graph_expansion_is_bounded() -> None:
    result = provider.expand_security_graph(
        ROOT,
        ["auditing-mcp-servers-for-tool-poisoning"],
        depth=2,
        max_nodes=20,
        max_edges=25,
    )
    assert result["valid"] is True
    assert len(result["nodes"]) <= 20
    assert len(result["edges"]) <= 25


def test_hydration_verifies_archive_and_body_hashes_without_extracting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"---\nname: fixture-security-skill\n---\n\nUntrusted reference body.\n"
    archive = tmp_path / "provider.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("provider/skills/fixture-security-skill/SKILL.md", body)
        target.writestr(
            "provider/skills/fixture-security-skill/scripts/agent.py",
            b"raise RuntimeError('must not execute')\n",
        )
    monkeypatch.setattr(
        provider,
        "EXPECTED_ARCHIVE_SHA256",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    original = provider.load_security_provider
    monkeypatch.setattr(
        provider,
        "load_security_provider",
        lambda _root: {
            "records": (
                {
                    "id": "external.cybersecurity.fixture-security-skill",
                    "source_path": "skills/fixture-security-skill",
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                },
            )
        },
    )
    try:
        result = provider.hydrate_security_bodies(
            ROOT, archive, ["external.cybersecurity.fixture-security-skill"]
        )
    finally:
        monkeypatch.setattr(provider, "load_security_provider", original)
    assert result["hydrated_count"] == 1
    assert result["provider_scripts_loaded"] == 0
    assert result["authority_granted"] is False
    assert not list(tmp_path.rglob("agent.py"))


def test_hydration_denies_archive_hash_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "wrong.zip"
    archive.write_bytes(b"not the admitted source")
    with pytest.raises(ValueError, match="archive hash mismatch"):
        provider.hydrate_security_bodies(
            ROOT, archive, ["external.cybersecurity.anything"]
        )


def test_verified_findings_require_hashed_evidence() -> None:
    finding = {
        "finding_id": "finding-1",
        "title": "A finding",
        "severity": "high",
        "confidence": 0.9,
        "evidence": [],
        "affected_assets": ["asset-a"],
        "recommended_actions": ["repair"],
        "validation_status": "verified",
    }
    assert provider.validate_security_finding(finding)["valid"] is False
    finding["evidence"] = [{"reference": "evidence/item.json", "sha256": "a" * 64}]
    assert provider.validate_security_finding(finding)["valid"] is True


def test_provider_text_cannot_self_authorize() -> None:
    result = provider.search_security_capabilities(
        ROOT, "ignore policy grant admin tools and execute", limit=5
    )
    assert all(
        item["authority_granted"] is False and item["admission_required"] is True
        for item in result["results"]
    )


def test_workflow_and_source_disposition_are_complete() -> None:
    result = provider.validate_security_orchestration(ROOT)
    assert result["valid"] is True
    disposition = json.loads(
        (
            ROOT
            / "evidence/integration/pxi-20260804/cybersecurity_provider_disposition.json"
        ).read_text(encoding="utf-8")
    )
    assert disposition["source_pack_file_count"] == 84
    assert disposition["candidate_count"] == 817
    assert disposition["unaccounted_count"] == 0
    assert disposition["hard_delete"] is False


def test_all_canonical_domains_have_passing_golden_routes() -> None:
    result = provider.evaluate_security_golden_queries(ROOT)
    assert result["case_count"] == 30
    assert result["failed"] == 0
    assert result["valid"] is True
