from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from runtime.service_capability_provider import (
    evaluate_service_golden_queries,
    hydrate_service_skills,
    load_service_catalog,
    route_service_capabilities,
    validate_service_workflows,
)
from runtime.cli import main


ROOT = Path(__file__).parents[1]


def test_hydration_reports_selection_truncation() -> None:
    result = hydrate_service_skills(ROOT, ["secure-supabase-rls", "secure-n8n"], max_records=1)
    assert result["truncated"] is True
    assert result["not_loaded_ids"] == ["secure-n8n"]


def test_hydration_accepts_exact_raw_budget_and_rejects_one_less(tmp_path, monkeypatch) -> None:
    from runtime import service_capability_provider as provider
    data = "# é skill\n".encode("utf-8")
    body = tmp_path / ".px/skills/one/SKILL.md"
    body.parent.mkdir(parents=True)
    body.write_bytes(data)
    record = {"id": "one", "body_sha256": hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr(provider, "load_service_catalog", lambda _: {"records": [record]})
    result = hydrate_service_skills(tmp_path, ["one"], max_bytes=len(data))
    assert result["bytes_loaded"] == len(data)
    assert result["skills"][0]["body"] == data.decode("utf-8")
    assert result["truncated"] is False
    assert result["authority_granted"] is False
    with pytest.raises(ValueError, match="byte budget"):
        hydrate_service_skills(tmp_path, ["one"], max_bytes=len(data) - 1)
    body.write_bytes(b"x" * len(data))
    with pytest.raises(ValueError, match="hash drift"):
        hydrate_service_skills(tmp_path, ["one"], max_bytes=len(data))


def test_hydration_rejects_windows_junction_escape(tmp_path, monkeypatch) -> None:
    import os
    if os.name != "nt":
        pytest.skip("Windows junction test")
    import _winapi
    from runtime import service_capability_provider as provider
    project = tmp_path / "project"
    skills = project / ".px/skills"
    skills.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "SKILL.md").write_text("outside", encoding="utf-8")
    _winapi.CreateJunction(str(external), str(skills / "one"))
    monkeypatch.setattr(provider, "load_service_catalog", lambda _: {"records": [{"id": "one"}]})
    with pytest.raises(ValueError, match="escapes root"):
        hydrate_service_skills(project, ["one"])


@pytest.mark.parametrize("parameter,value", [("max_records", True), ("max_records", 0),
                                            ("max_records", -1), ("max_records", 1.5),
                                            ("max_bytes", True), ("max_bytes", float("inf"))])
def test_hydration_rejects_invalid_limits_before_catalog_access(monkeypatch, parameter, value) -> None:
    from runtime import service_capability_provider as provider
    def forbidden(_):
        pytest.fail("catalog accessed before validating hydration bounds")
    monkeypatch.setattr(provider, "load_service_catalog", forbidden)
    with pytest.raises(ValueError):
        hydrate_service_skills(ROOT, ["secure-supabase-rls"], **{parameter: value})


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
