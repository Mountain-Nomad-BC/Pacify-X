from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.contracts import validate_instance
from runtime.cli import main
from runtime.project_reasoning import (
    audit_glossary,
    decision_frontier,
    find_cycles,
    inspect_python_module,
    validate_reasoning_orchestration,
)


ROOT = Path(__file__).parents[1]
SKILLS = (
    "architecture-deepening-audit",
    "context-handoff-package",
    "decision-wayfinding",
    "deep-module-design",
    "design-it-twice",
    "domain-language-maintenance",
    "dual-axis-code-review",
    "frontier-questioning",
    "guided-procedure-wizard",
    "intent-preserving-merge-resolution",
    "questionnaire-delegation",
    "tracer-bullet-planning",
)


def test_decision_frontier_is_deterministic_ranked_and_hash_bound() -> None:
    document = {
        "tickets": [
            {"id": "done", "status": "done"},
            {"id": "later", "blocked_by": ["ready"]},
            {"id": "ready", "blocked_by": ["done"], "impact": 10, "uncertainty": 3},
            {"id": "claimed", "claimed_by": "agent", "impact": 100},
        ]
    }
    first = decision_frontier(document)
    second = decision_frontier(document)
    assert first == second
    assert [item["id"] for item in first["frontier"]] == ["ready"]
    validate_instance(first, ROOT / "contracts/reasoning/decision-frontier.schema.json")


def test_decision_frontier_rejects_cycles_missing_blockers_and_duplicate_ids() -> None:
    cyclic = {
        "tickets": [{"id": "a", "blocked_by": ["b"]}, {"id": "b", "blocked_by": ["a"]}]
    }
    assert find_cycles(cyclic) == (("a", "b", "a"),)
    assert decision_frontier(cyclic)["valid"] is False
    with pytest.raises(ValueError, match="unknown blockers"):
        decision_frontier({"tickets": [{"id": "a", "blocked_by": ["missing"]}]})
    with pytest.raises(ValueError, match="unique"):
        decision_frontier({"tickets": [{"id": "a"}, {"id": "a"}]})


def test_glossary_audit_is_project_scoped_and_reports_canonical_terms(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "design.md"
    artifact.write_text("Inspect the bank of relays.\n", encoding="utf-8")
    glossary = {"terms": [{"canonical": "heating bank", "aliases": ["bank of relays"]}]}
    result = audit_glossary(glossary, [artifact], project_root=tmp_path)
    assert result["issue_count"] == 1
    assert result["issues"][0]["canonical"] == "heating bank"
    assert result["issues"][0]["line"] == 1
    validate_instance(result, ROOT / "contracts/reasoning/glossary-audit.schema.json")


def test_glossary_audit_rejects_paths_outside_project(tmp_path: Path) -> None:
    outside = ROOT / "README.md"
    with pytest.raises(ValueError, match="escapes project"):
        audit_glossary({"terms": []}, [outside], project_root=tmp_path)


def test_module_depth_audit_is_bounded_evidence_not_architecture_claim(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module.py"
    module.write_text(
        "def public(value):\n    adjusted = value + 1\n    return adjusted * 2\n",
        encoding="utf-8",
    )
    result = inspect_python_module(module, project_root=tmp_path)
    assert result["symbols"][0]["depth_proxy"] > 0
    assert "proxy only" in result["metric_boundary"]
    validate_instance(
        result, ROOT / "contracts/reasoning/module-depth-audit.schema.json"
    )


def test_module_depth_audit_rejects_external_paths_and_invalid_python(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="escapes project"):
        inspect_python_module(ROOT / "runtime/cli.py", project_root=tmp_path)
    invalid = tmp_path / "invalid.py"
    invalid.write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        inspect_python_module(invalid, project_root=tmp_path)


def test_all_reasoning_skills_are_lazy_discoverable_active_packages() -> None:
    catalog_text = (ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    for identifier in SKILLS:
        skill = ROOT / ".px/skills" / identifier
        manifest = json.loads(
            (ROOT / "registry/skill_packages" / f"{identifier}.json").read_text(
                encoding="utf-8"
            )
        )
        assert (skill / "SKILL.md").is_file()
        assert (skill / "agents/openai.yaml").is_file()
        assert manifest["status"] == "active"
        assert manifest["body"] == f".px/skills/{identifier}/SKILL.md"
        assert f'id = "{identifier}"' in catalog_text


def test_source_attribution_is_preserved() -> None:
    assert (ROOT / "LICENSES/mattpocock-skills-MIT.txt").is_file()
    assert (ROOT / "LICENSES/mattpocock-skills-MIT.txt").is_file()
    assert "mattpocock/skills" in (ROOT / "NOTICE").read_text(encoding="utf-8")


def test_reasoning_workflow_and_cli_are_executable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = validate_reasoning_orchestration(ROOT)
    assert workflow["valid"], workflow["errors"]
    decision_map = tmp_path / "decisions.json"
    decision_map.write_text(
        json.dumps({"tickets": [{"id": "next", "impact": 2}]}),
        encoding="utf-8",
    )
    assert (
        main(
            ["--root", str(ROOT), "reasoning", "frontier", "--input", str(decision_map)]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["frontier"][0]["id"] == "next"
