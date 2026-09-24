"""Read/advisory admission facades for the Wave-16 model/cognitive fabric.

These adapters expose already-owned PX capabilities through one lazy integration registry.
They intentionally do not grant mutation authority, launch models, promote generations,
or bypass project/lease/policy owners.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def model_fabric_inventory(root: Path) -> dict[str, Any]:
    from .model_profile import load_runtime_profiles
    profiles = load_runtime_profiles(Path(root))
    return {
        "schema_version": "px.model-fabric-inventory/1.0",
        "profiles": [
            {
                "profile_id": p.profile_id,
                "model_id": p.model_id,
                "lane": p.lane,
                "runtime": p.runtime,
                "state": p.state,
                "residency": p.residency,
                "profile_sha256": p.profile_sha256,
            }
            for p in profiles
        ],
        "authority_granted": False,
    }


def cognitive_query_read(root: Path, query: str, *, project_id: str = "", top_per_category: int = 3):
    from .cognitive_query import query_repository_index
    return query_repository_index(Path(root), query, project_id=project_id, top_per_category=top_per_category)


def semantic_code_inventory() -> dict[str, Any]:
    from .semantic_integration_registry import integration_inventory
    value = dict(integration_inventory())
    value["authority_granted"] = False
    return value


def retrieval_generation_status(state_root: Path) -> dict[str, Any]:
    from .retrieval_generation import RetrievalGenerationStore
    store = RetrievalGenerationStore(Path(state_root))
    return {
        "schema_version": "px.retrieval-generation-status/1.0",
        "active_generation": store.active_generation(),
        "authority_granted": False,
    }


def persistent_memory_metadata() -> dict[str, Any]:
    from .persistent_memory_provider import provider_metadata
    value = dict(provider_metadata())
    value["authority_granted"] = False
    return value


def nsai_library_status(root: Path) -> dict[str, Any]:
    from .nsai_knowledge import audit_nsai_library
    value = dict(audit_nsai_library(Path(root) / "knowledge" / "nsai", require_index_match=True))
    value["authority_granted"] = False
    return value


def _healthcheck(name: str) -> dict[str, Any]:
    return {"valid": True, "integration": name, "effects": ["read_local"], "authority_granted": False}


def model_fabric_healthcheck(): return _healthcheck("model-fabric-runtime")
def cognitive_query_healthcheck(): return _healthcheck("cognitive-query-runtime")
def semantic_code_healthcheck(): return _healthcheck("semantic-code-intelligence-runtime")
def retrieval_generation_healthcheck(): return _healthcheck("retrieval-generation-runtime")
def persistent_memory_healthcheck(): return _healthcheck("persistent-memory-provider")
def nsai_library_healthcheck(): return _healthcheck("nsai-knowledge-library")


def validate_persistent_memory_review(root: Path) -> dict[str, Any]:
    import json
    path = Path(root) / "orchestration" / "workflows" / "persistent-memory-review.yaml"
    if not path.is_file():
        return {"valid": False, "errors": ["workflow missing"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        workflows = payload.get("workflows", ())
        if len(workflows) != 1 or workflows[0].get("id") != "persistent-memory-review":
            raise ValueError("persistent-memory-review workflow identity mismatch")
        steps = workflows[0].get("steps", ())
        ids = [row.get("id") for row in steps if isinstance(row, dict)]
        required = ["validate-boundary", "list-memory", "review-preview", "graph-preview", "emit-advisory-evidence"]
        if ids != required:
            raise ValueError("persistent-memory-review step order mismatch")
        if any(row.get("skill") != "govern-persistent-memory" for row in steps):
            raise ValueError("persistent-memory-review must remain bound to govern-persistent-memory")
        if workflows[0].get("effects") != ["read_local"]:
            raise ValueError("persistent-memory-review must remain read-only")
        return {"valid": True, "errors": [], "authority_granted": False}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [str(error)], "authority_granted": False}


def vscode_model_client_status(root: Path) -> dict[str, Any]:
    from .model_profile import load_runtime_profiles
    from .provider_gateway import load_provider_registry
    profiles = load_runtime_profiles(Path(root))
    registry = load_provider_registry(Path(root))
    adapter = next((row for row in registry["adapters"] if row["adapter_id"] == "llama-cpp-stream"), None)
    return {"schema_version": "px.vscode-model-client-status/1.0", "certified_profile_count": sum(profile.is_certified for profile in profiles), "stream_adapter_admitted": bool(adapter and adapter.get("admitted") is True and adapter.get("status") == "ready"), "authority_granted": False}

def vscode_model_client_healthcheck(): return _healthcheck("vscode-model-client")
def mcp_model_fabric_bridge_healthcheck(): return _healthcheck("mcp-model-fabric-bridge")
