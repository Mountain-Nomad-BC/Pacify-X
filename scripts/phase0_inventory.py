"""Phase 0 discovery: inventory canonical owners and their consumers (read-only).

Produces a machine-readable integration matrix fragment. Performs no edits.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OWNERS = {
    "execution_context": "runtime/execution_context.py",
    "execution_contract": "runtime/execution_contract.py",
    "cancellation_scope": "runtime/cancellation_scope.py",
    "scope_lease": "runtime/scope_lease.py",
    "effect_intent": "runtime/effect_intent.py",
    "member_execution": "runtime/member_execution.py",
    "model_group_preparation": "runtime/model_group_preparation.py",
    "model_convergence": "runtime/model_convergence.py",
    "model_branch_artifacts": "runtime/model_branch_artifacts.py",
    "source_boundary": "runtime/source_boundary.py",
    "repository_scope": "runtime/repository_scope.py",
    "workspace_manager": "runtime/workspace_manager.py",
    "operational_gap_ledger": "runtime/operational_gap_ledger.py",
    "mutation_queue": "runtime/mutation_queue.py",
    "tie_experience": "runtime/tie_experience.py",
    "data_inventory": "runtime/data_inventory.py",
    "provider_gateway": "runtime/provider_gateway.py",
    "agent_runtime": "runtime/agent_runtime.py",
    "studio_models": "runtime/studio_models.py",
    "cancellation_control": "runtime/studio_run_control.py",
    "process_supervisor": "runtime/process_supervisor.py",
    "trusted_evidence": "runtime/trusted_evidence.py",
    "extension_mcp_source": "extension/server/source.mjs",
    "atlas_generator": "docs/architecture/tools/build_atlas.py",
}

GREMLIN_PATTERNS = re.compile(r"gremlin|nanny|containment", re.I)


def module_name(relative: str) -> str:
    if relative.endswith(".py"):
        return relative[:-3].replace("/", ".")
    return relative


def consumers_of(name: str, relative: str) -> list[str]:
    """Find files that import or reference the owner."""
    stem = module_name(relative).split(".")[-1]
    hits = []
    for path in ROOT.rglob("*.py"):
        if str(path).endswith(relative):
            continue
        if any(part in {"node_modules", "__pycache__", ".venv", "site-packages"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(rf"\b{re.escape(stem)}\b", text) or f"from {module_name(relative)}" in text:
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(("runtime/", "extension/", "scripts/", "tests/", "docs/")):
                hits.append(rel)
    return sorted(hits)


def gremlin_scan() -> dict[str, object]:
    files = []
    content_hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {"node_modules", "__pycache__", ".venv", ".git"} for part in path.parts):
            continue
        if re.search(r"gremlin|nanny", path.name, re.I):
            files.append(path.relative_to(ROOT).as_posix())
    for path in ROOT.rglob("*.py"):
        if any(part in {"node_modules", "__pycache__", ".venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if GREMLIN_PATTERNS.search(line) and "re.I" not in line:
                content_hits.append({"path": path.relative_to(ROOT).as_posix(), "line": i,
                                     "text": line.strip()[:120]})
    return {"files": sorted(files), "content_hits": content_hits}


def main() -> int:
    matrix = []
    for name, relative in OWNERS.items():
        exists = (ROOT / relative).exists()
        matrix.append({
            "capability": name,
            "canonical_owner": relative,
            "present": exists,
            "consumers": consumers_of(name, relative) if exists else [],
        })
    result = {
        "schema_version": "px.phase0-integration-inventory/1.0",
        "owners": matrix,
        "gremlin": gremlin_scan(),
    }
    out = ROOT / ".agentic_engineering_os_px/test-evidence/implementation-first/phase0-inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in matrix:
        print(f"{row['capability']:26} present={row['present']} consumers={len(row['consumers'])}")
    print("gremlin files:", result["gremlin"]["files"])
    print("gremlin content hits:", len(result["gremlin"]["content_hits"]))
    print("written:", out.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())