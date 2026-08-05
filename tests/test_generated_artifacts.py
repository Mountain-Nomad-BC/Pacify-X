from pathlib import Path
import json

from runtime.generated_artifacts import validate_generated_artifacts
from scripts.build_declared_suite_template_projections import (
    reconcile as template_reconcile,
)
from scripts.build_domain_tool_projections import reconcile as wrapper_reconcile
from scripts.build_profile_projections import reconcile as profile_reconcile


ROOT = Path(__file__).resolve().parents[1]


def test_all_generated_projections_match_one_canonical_owner():
    result = validate_generated_artifacts(ROOT)
    assert result["valid"], result["failed"]
    assert result["checks"]["domain_wrappers"]["projection_count"] == 7
    assert result["checks"]["declared_suite_templates"]["projection_count"] == 21
    assert len(result["checks"]["profile_projections"]["records"]) == 5
    commissioned = json.loads(
        (ROOT / ".engineering-bootstrap/project-registry.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["checks"]["commissioned_skill_registry"]["skill_count"] == len(
        commissioned["skills"]
    )


def test_one_projection_mutation_is_detected_without_rewriting(tmp_path):
    root = tmp_path / "product"
    import shutil

    shutil.copytree(ROOT / "templates", root / "templates")
    for owner in (
        "analyze-repository-intelligence",
        "engineer-verification-lab",
        "govern-operating-kernel",
        "govern-runtime-protocol-deployment",
        "manage-revocable-certification",
        "operate-memory-retrieval-observability",
        "secure-agent-supply-chain",
    ):
        target = root / ".agents/skills" / owner / "scripts/domain_tool.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            (ROOT / ".agents/skills" / owner / "scripts/domain_tool.py").read_bytes()
        )
    changed = (
        root / ".agents/skills/analyze-repository-intelligence/scripts/domain_tool.py"
    )
    changed.write_text(
        changed.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8"
    )
    result = wrapper_reconcile(root, check=True)
    assert not result["valid"]
    assert changed.relative_to(root).as_posix() in result["stale"]


def test_generation_is_byte_stable_when_inputs_do_not_change():
    before = [
        path.read_bytes()
        for path in sorted((ROOT / "templates/declared_suite").glob("pack-*.json"))
    ]
    assert template_reconcile(ROOT, check=True)["valid"]
    assert profile_reconcile(ROOT, check=True)["valid"]
    after = [
        path.read_bytes()
        for path in sorted((ROOT / "templates/declared_suite").glob("pack-*.json"))
    ]
    assert before == after
