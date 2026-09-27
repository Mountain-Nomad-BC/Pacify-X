from pathlib import Path
import hashlib
import json

from runtime.generated_artifacts import _validate_python_surface_map, validate_generated_artifacts
from scripts.build_declared_suite_template_projections import (
    reconcile as template_reconcile,
)
from scripts.build_domain_tool_projections import reconcile as wrapper_reconcile
from scripts.build_profile_projections import reconcile as profile_reconcile


ROOT = Path(__file__).resolve().parents[1]


def test_python_surface_projection_detects_changed_and_new_source(tmp_path):
    source = tmp_path / "runtime/stable.py"
    source.parent.mkdir()
    source.write_bytes(b"value = 1\n")
    registry = tmp_path / "registry"
    registry.mkdir()
    ownership = registry / "python_surface_ownership.json"
    ownership.write_text(json.dumps({
        "map_current": True,
        "records": [{"path": "runtime/stable.py", "bytes": len(source.read_bytes()),
                     "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
    }), encoding="utf-8")
    assert _validate_python_surface_map(tmp_path)["valid"]

    source.write_bytes(b"value = 2\n")
    assert not _validate_python_surface_map(tmp_path)["valid"]
    source.write_bytes(b"value = 1\n")
    (source.parent / "new.py").write_bytes(b"pass\n")
    assert not _validate_python_surface_map(tmp_path)["valid"]


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
    assert result["checks"]["native_skill_packages"]["valid"]
    assert result["checks"]["provider_route_index"]["index_current"]
    assert result["checks"]["semantic_capability_index"]["valid"]
    assert result["checks"]["skill_packaging_projection"]["valid"]
    assert result["checks"]["test_group_index"]["valid"]


def test_artifact_reachability_excludes_live_receipt_projection_cycle():
    from runtime.artifact_reachability import build_artifact_reachability
    from runtime.repository_scope import is_external_environment_relative

    paths = {row["path"] for row in build_artifact_reachability(ROOT)["records"]}
    assert not any(is_external_environment_relative(path) for path in paths)
    assert "registry/current_evidence_index.json" not in paths
    assert "registry/completion_status.json" not in paths
    assert "registry/test_group_index.json" not in paths
    assert "registry/operational_gap_ledger.head.json" not in paths
    assert "registry/operational_gap_ledger.snapshot.json" not in paths
    assert "registry/px_world_state.json" not in paths


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
        target = root / ".px/skills" / owner / "scripts/domain_tool.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            (ROOT / ".px/skills" / owner / "scripts/domain_tool.py").read_bytes()
        )
    changed = (
        root / ".px/skills/analyze-repository-intelligence/scripts/domain_tool.py"
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
