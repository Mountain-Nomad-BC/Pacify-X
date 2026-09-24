from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib

from runtime.admitted_fabric_integrations import (
    cognitive_query_healthcheck,
    model_fabric_healthcheck,
    model_fabric_inventory,
    nsai_library_healthcheck,
    nsai_library_status,
    persistent_memory_healthcheck,
    retrieval_generation_healthcheck,
    semantic_code_healthcheck,
    semantic_code_inventory,
)
from runtime.integration_registry import validate_integrations
from runtime.structural_integrity import _skill_errors, _workflow_errors

ROOT = Path(__file__).parents[1]
NEW_SKILLS = {
    "govern-model-fabric",
    "operate-semantic-code-intelligence",
    "govern-retrieval-generations",
}
REJECTED_DUPLICATES = {
    "operate-local-model-pool",
    "diagnose-model-routing",
    "operate-nsai-knowledge-library",
}


def test_skill_reconciliation_admits_three_not_six():
    catalog = tomllib.loads((ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8"))
    ids = {row["id"] for row in catalog["skills"]}
    assert NEW_SKILLS <= ids
    assert not (REJECTED_DUPLICATES & ids)
    for skill_id in NEW_SKILLS:
        package = json.loads((ROOT / "registry/skill_packages" / f"{skill_id}.json").read_text())
        body = ROOT / package["body"]
        assert package["status"] == "active"
        assert package["body_sha256"] == hashlib.sha256(body.read_bytes()).hexdigest()
        assert (ROOT / ".px/skills" / skill_id / "agents/openai.yaml").is_file()


def test_integration_registry_is_valid_and_smoke_healthchecks_are_read_only():
    result = validate_integrations(ROOT, smoke=True)
    assert result["valid"], result["errors"]
    checks = [model_fabric_healthcheck(), semantic_code_healthcheck(), retrieval_generation_healthcheck(), persistent_memory_healthcheck(), nsai_library_healthcheck(), cognitive_query_healthcheck()]
    assert all(item["valid"] and item["authority_granted"] is False for item in checks)
    assert all(item["effects"] == ["read_local"] for item in checks)


def test_read_only_admission_facades_report_current_corpus_and_profiles():
    model = model_fabric_inventory(ROOT)
    assert model["authority_granted"] is False
    assert model["profiles"]
    assert any(row["lane"] == "control" for row in model["profiles"])
    semantic = semantic_code_inventory()
    assert semantic["authority_granted"] is False
    assert semantic["operations"]
    nsai = nsai_library_status(ROOT)
    assert nsai["valid"] is True
    assert nsai["object_count"] >= 74
    assert nsai["authority_granted"] is False


def test_workflows_bind_new_skills_and_checkpoint_generation_steps():
    reg = json.loads((ROOT / "registry/skill_orchestrations.json").read_text())
    flows = {row["id"]: row for row in reg["workflows"]}
    assert reg["count"] == len(reg["workflows"])
    assert flows["model-fabric-operations"]["steps"][0]["skill"] == "govern-model-fabric"
    assert any(row["skill"] == "operate-semantic-code-intelligence" for row in flows["semantic-code-intelligence"]["steps"])
    assert any(row["skill"] == "govern-retrieval-generations" for row in flows["retrieval-generation-governance"]["steps"])
    mem_ids = [row["id"] for row in flows["layered-memory-lifecycle"]["steps"]]
    assert mem_ids.index("checkpoint") < mem_ids.index("compact")
    assert "tier-and-publish" in mem_ids


def test_admission_relationships_are_structurally_closed():
    assert _skill_errors(ROOT) == []
    assert _workflow_errors(ROOT) == []
