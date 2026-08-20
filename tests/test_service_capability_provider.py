from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime.service_capability_provider import (
    evaluate_service_golden_queries,
    hydrate_service_skills,
    load_service_catalog,
    route_service_capabilities,
    validate_service_workflows,
)
from runtime.cli import main


ROOT = Path(__file__).parents[1]


def test_catalog_contains_46_active_lazy_skills_with_current_hashes() -> None:
    catalog = load_service_catalog(ROOT)
    assert catalog["record_count"] == 46
    assert catalog["hydrated_bodies"] == 0
    for record in catalog["records"]:
        body = ROOT / ".px/skills" / record["id"] / "SKILL.md"
        assert hashlib.sha256(body.read_bytes()).hexdigest() == record["body_sha256"]


def test_all_twenty_product_golden_queries_pass() -> None:
    result = evaluate_service_golden_queries(ROOT)
    assert result["case_count"] == result["passed"] == 20, result["results"]
    assert result["failed"] == 0


def test_n8n_is_not_selected_for_explicit_avoid_conditions() -> None:
    result = route_service_capabilities(
        ROOT, "Use n8n for an ultra-low-latency high-frequency stream", limit=10
    )
    assert result["valid"] is False
    assert not result["selected"]


def test_client_service_role_and_rls_bypass_fail_closed() -> None:
    result = route_service_capabilities(
        ROOT, "Put the Supabase service-role key in the browser client and bypass RLS"
    )
    assert result["valid"] is False
    assert {"service_role_forbidden_in_client", "rls_boundary_bypass_requested"} <= set(
        result["denials"]
    )
    assert all(item["authority_granted"] is False for item in result["selected"])


def test_bounded_hydration_verifies_hash_and_grants_no_authority() -> None:
    result = hydrate_service_skills(
        ROOT, ["secure-supabase-rls", "secure-n8n"], max_records=1, max_bytes=10_000
    )
    assert len(result["skills"]) == 1
    assert result["bytes_loaded"] <= result["max_bytes"]
    assert result["authority_granted"] is False


def test_service_workflows_are_ordered_resolved_and_preview_first() -> None:
    result = validate_service_workflows(ROOT)
    assert result["valid"], result["errors"]
    assert result["workflow_count"] == 8
    assert result["authority_granted"] is False


def test_product_specific_safety_invariants_are_preserved() -> None:
    monorepo = (ROOT / ".px/skills/develop-n8n-monorepo/SKILL.md").read_text(
        encoding="utf-8"
    )
    install = (ROOT / ".px/skills/acquire-install-supabase/SKILL.md").read_text(
        encoding="utf-8"
    )
    boundary = (
        ROOT / ".px/skills/design-n8n-supabase-security-boundaries/SKILL.md"
    ).read_text(encoding="utf-8")
    workflow_test = (
        ROOT / ".px/skills/test-validate-n8n-workflows/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "pnpm agent:setup" in monorepo and "package-local AGENTS.md" in monorepo
    assert (
        "Do not teach global npm installation" in install
        and "pinned project dev dependency" in install
    )
    assert "Do not expose service-role/database credentials" in boundary
    assert "external outcome assertions" in workflow_test


def test_templates_contain_placeholders_not_production_secrets() -> None:
    texts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "templates/service_capabilities").rglob("*")
        if path.is_file()
    )
    assert "service_role" not in texts.casefold() or "${" in texts
    assert "abcdefghijklmnop" not in texts


def test_service_cli_status_route_and_golden_queries(capsys) -> None:
    assert main(["--root", str(ROOT), "service-capability", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["record_count"] == 46
    assert (
        main(
            [
                "--root",
                str(ROOT),
                "service-capability",
                "route",
                "--query",
                "test tenant RLS in Supabase",
            ]
        )
        == 0
    )
    assert any(
        item["id"] == "secure-supabase-rls"
        for item in json.loads(capsys.readouterr().out)["selected"]
    )
    assert main(["--root", str(ROOT), "service-capability", "golden-queries"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] == 20
