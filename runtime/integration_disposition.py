"""Deterministic canonical-owner inventory and source disposition planning.

The builders are read-only over both trees. They produce hash-bound evidence;
they never install, delete, quarantine, or execute incoming material.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any, Iterable, Mapping


CACHE_PARTS = {".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__"}
OVERLAY_MARKERS = {"overlay", "pacify-x-overlay", "pacify_x_overlay"}
CODE_SUFFIXES = {".py", ".ps1", ".sh", ".js", ".mjs", ".cjs", ".ts", ".rs", ".sql"}
REFERENCE_SUFFIXES = {".md", ".txt", ".pdf", ".png", ".svg", ".ico", ".icns"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _append(
    records: list[dict[str, object]],
    seen: set[tuple[str, str]],
    *,
    object_type: str,
    object_id: str,
    owner: str,
    source: str,
    lifecycle: str = "active",
    authority: str = "metadata_only",
    outcomes: Iterable[str] = (),
) -> None:
    key = (object_type, object_id)
    if key in seen:
        return
    seen.add(key)
    records.append(
        {
            "object_type": object_type,
            "object_id": object_id,
            "owner": owner,
            "source": source,
            "lifecycle": lifecycle,
            "authority": authority,
            "outcomes": sorted({str(value) for value in outcomes if str(value)}),
        }
    )


def _registry_items(payload: Mapping[str, object]) -> Iterable[Mapping[str, object]]:
    for value in payload.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item


def build_canonical_owner_index(root: Path) -> dict[str, object]:
    """Inventory current target owners without hydrating skills or agents."""
    root = root.resolve(strict=True)
    records: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    catalog_path = root / "registry" / "skill_catalog.toml"
    catalog = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    for item in catalog.get("skills", ()):
        skill_id = str(item["id"])
        contract_path = root / str(item.get("contract", ""))
        contract = _load_json(contract_path) if contract_path.is_file() else {}
        _append(
            records,
            seen,
            object_type="skill",
            object_id=skill_id,
            owner=str(item.get("path", f".px/skills/{skill_id}/SKILL.md")),
            source="registry/skill_catalog.toml",
            lifecycle=str(item.get("status", "candidate")),
            authority=str(contract.get("risk", "R1")),
            outcomes=contract.get("provides", ()),
        )

    ownership_path = root / "registry" / "contract_ownership.json"
    for item in _load_json(ownership_path).get("records", ()):
        _append(
            records,
            seen,
            object_type="contract",
            object_id=str(item["contract_id"]),
            owner=str(item["owner"]),
            source=str(item["path"]),
            authority=str(item.get("enforcement", "declared")),
            outcomes=(str(item.get("title", "")),),
        )

    registry_types = {
        "models.json": "model",
        "tools.json": "tool",
        "knowledge_sources.json": "knowledge",
        "capability_aliases.json": "alias",
        "declared_suite_formulas.json": "formula",
        "metacognitive_formulas.json": "formula",
        "scheduling_policies.json": "policy",
        "metacognitive_policies.json": "policy",
        "skill_orchestrations.json": "orchestration",
        "project_stream_orchestrations.json": "orchestration",
    }
    id_fields = (
        "id",
        "model_id",
        "tool_id",
        "source_id",
        "alias",
        "formula_id",
        "policy_id",
        "orchestration_id",
        "workflow_id",
    )
    for filename, object_type in registry_types.items():
        relative = f"registry/{filename}"
        path = root / relative
        if not path.is_file():
            continue
        for item in _registry_items(_load_json(path)):
            object_id = next(
                (str(item[field]) for field in id_fields if item.get(field)), ""
            )
            if not object_id:
                continue
            owner = str(item.get("owner") or item.get("handler") or relative)
            outcomes = (
                item.get("outcomes")
                or item.get("provides")
                or item.get("capabilities")
                or ()
            )
            if isinstance(outcomes, str):
                outcomes = (outcomes,)
            _append(
                records,
                seen,
                object_type=object_type,
                object_id=object_id,
                owner=owner,
                source=relative,
                lifecycle=str(item.get("status", "active")),
                authority=str(
                    item.get("risk") or item.get("authority") or "metadata_only"
                ),
                outcomes=outcomes if isinstance(outcomes, (list, tuple)) else (),
            )

    for path in sorted((root / "orchestration" / "workflows").rglob("*.yaml")):
        relative = path.relative_to(root).as_posix()
        _append(
            records,
            seen,
            object_type="workflow",
            object_id=path.stem,
            owner=relative,
            source=relative,
        )
    for folder, object_type in (
        ("scripts", "script"),
        ("validators", "validator"),
        ("policies", "policy"),
    ):
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            _append(
                records,
                seen,
                object_type=object_type,
                object_id=relative,
                owner=relative,
                source=relative,
            )

    records.sort(key=lambda item: (str(item["object_type"]), str(item["object_id"])))
    counts = dict(sorted(Counter(str(item["object_type"]) for item in records).items()))
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "generator": "pacify-x.integration-disposition/1.0.0",
        "record_count": len(records),
        "counts": counts,
        "records": records,
    }
    payload["index_sha256"] = _stable(payload)
    return payload


def _overlay_target(parts: tuple[str, ...]) -> str | None:
    for index, part in enumerate(parts):
        if part.casefold() in OVERLAY_MARKERS and index + 1 < len(parts):
            return "/".join(parts[index + 1 :])
    return None


def _planned_owner(
    parts: tuple[str, ...], suffix: str, *, source_alias: str = ""
) -> tuple[str, str, str]:
    package = parts[0].casefold()
    lowered = "/".join(part.casefold() for part in parts[1:])
    joined = "/".join(part.casefold() for part in parts)
    source_identity = f"{source_alias.casefold()}/{joined}"
    if any(part in CACHE_PARTS for part in parts):
        return (
            "derived-regenerate",
            "external quarantine custody",
            "generated cache is never installed",
        )
    if suffix in {".zip", ".car"}:
        return (
            "retain",
            "external source custody",
            "immutable upstream/reference archive",
        )
    if "audit_repair_pack" in source_identity:
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "repair instruction, installer, verifier, patch, manifest, or audit evidence retained after canonical clean-room integration",
        )
    if "cybersecurity" in package:
        if "/skills/" in f"/{lowered}" or lowered.startswith("upstream/"):
            return (
                "defer",
                "runtime/cybersecurity_provider.py",
                "external security provider candidate; no automatic activation",
            )
        if suffix in CODE_SUFFIXES or lowered.startswith(
            ("contracts/", "schemas/", "workflows/", "validators/", "registries/")
        ):
            return (
                "merge",
                "runtime/cybersecurity_provider.py",
                "governed provider, authorization, evidence, and fail-closed controls",
            )
        if lowered.startswith("licenses/"):
            return (
                "merge",
                "NOTICE",
                "Apache-2.0 attribution consolidated into the project notice without duplicating the license text",
            )
    if "candidate_compiler_resolver" in source_identity:
        if "/skills/" in f"/{joined}":
            return (
                "merge",
                ".px/skills/govern-candidate-resolution-pipeline",
                "candidate compilation and resolution procedures consolidated into one clean-room lazy skill",
            )
        if "/orchestration/" in f"/{joined}":
            return (
                "merge",
                "orchestration/workflows/completion-controls.yaml",
                "resolver stages consolidated into the canonical completion-control workflow",
            )
        if (
            suffix in CODE_SUFFIXES
            or "/contracts/" in f"/{joined}"
            or "/policies/" in f"/{joined}"
            or "/registry/" in f"/{joined}"
        ):
            return (
                "merge",
                "runtime/capability_routing.py",
                "membership invariants, independent scoring, package optimization, fold-in, and evidence controls merged into canonical owners",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "candidate compiler source guidance, examples, manifests, and validation retained as provenance",
        )
    if "multi_repo_completion" in source_identity:
        skill_name = (
            parts[-2].casefold()
            if len(parts) > 2 and parts[-1].casefold() == "skill.md"
            else ""
        )
        epistemic_terms = (
            "memory",
            "claim",
            "epistemic",
            "temporal",
            "observation",
            "skill-",
            "reflection",
            "notability",
            "context-efficiency",
            "rag-",
        )
        delivery_terms = (
            "cad",
            "geometry",
            "manufactur",
            "robot",
            "moveit",
            "media",
            "frame-selection",
            "provider-support",
        )
        if "/skills/" in f"/{joined}":
            if any(term in skill_name for term in delivery_terms):
                owner = ".px/skills/validate-physical-media-deliverables"
            elif any(term in skill_name for term in epistemic_terms):
                owner = ".px/skills/govern-epistemic-skill-evolution"
            else:
                owner = ".px/skills/govern-distributed-work-runtime"
            return (
                "merge",
                owner,
                "micro-skill semantics consolidated into a canonical clean-room owner to avoid duplicate discovery surfaces",
            )
        if "/workflows/" in f"/{joined}":
            return (
                "merge",
                "orchestration/workflows/completion-controls.yaml",
                "completion slices consolidated into executable canonical workflows",
            )
        if (
            suffix in CODE_SUFFIXES
            or "/contracts/" in f"/{joined}"
            or "/policies/" in f"/{joined}"
            or "/registry/" in f"/{joined}"
        ):
            return (
                "merge",
                "runtime/completion_controls.py",
                "project-scoped leases, epistemic evolution, artifact validation, and optional adapter controls implemented clean-room",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "multi-repository completion guidance, audit, examples, manifests, or validation retained as provenance",
        )
    if "openmanus_upgrade" in source_identity:
        if "/skills/" in f"/{joined}":
            return (
                "merge",
                ".px/skills/govern-distributed-work-runtime",
                "external task, MCP, sandbox, and job procedures consolidated without a second agent loop",
            )
        if "/orchestration/" in f"/{joined}":
            return (
                "merge",
                "orchestration/workflows/completion-controls.yaml",
                "external job and protocol boundaries consolidated into executable workflow ownership",
            )
        if (
            suffix in CODE_SUFFIXES
            or "/contracts/" in f"/{joined}"
            or "/policies/" in f"/{joined}"
            or "/registry/" in f"/{joined}"
        ):
            return (
                "merge",
                "runtime/completion_controls.py",
                "external job lifecycle and project-scoped runtime boundary independently implemented beside existing A2A and MCP owners",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "external-agent integration guidance, audit, examples, manifests, or validation retained as provenance",
        )
    if (
        "pacify_x_13_repo_integration_package" in source_identity
        or "pacify_x_change_conformance_codex_bundle" in source_identity
    ):
        if suffix in CODE_SUFFIXES or any(
            marker in f"/{joined}"
            for marker in (
                "/contracts/",
                "/orchestrations/",
                "/skills/",
                "/payload/",
                "/tests/",
            )
        ):
            return (
                "merge",
                "runtime/clean_room_capabilities.py",
                "overlapping conformance, shadow, lineage, reconciliation, and memory controls folded into existing canonical owners",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "integration plan, provenance, source analysis, manifest, or validation evidence retained",
        )
    if joined.endswith("ekap_engineering_research_engine_expansion.md"):
        return (
            "merge",
            ".px/skills/operate-engineering-research-engine",
            "mechanism-level research discovery, fingerprint, synthesis, drift, and promotion procedure implemented clean-room",
        )
    if package == "pacify-x-full-project-mapping-pack":
        if lowered.startswith("overlay/runtime/"):
            return (
                "merge",
                "runtime/project_intelligence.py",
                "project-map command behavior is owned by the canonical project intelligence and retrieval runtime",
            )
        if lowered.startswith("overlay/tools/"):
            return (
                "fragment",
                "runtime/project_map_retrieval.py",
                "bounded query and serialization mechanisms retained without a parallel CLI",
            )
        if lowered.startswith("overlay/contracts/"):
            return (
                "merge",
                "contracts/project-map.schema.json",
                "project-map schema reconciled into the canonical owned contract",
            )
        if lowered.startswith("overlay/skills/"):
            return (
                "merge",
                ".px/skills/map-project-intelligence",
                "project-map procedure merged into the canonical lazy skill",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "project mapping source evidence, tests, manifest, or integration guidance retained",
        )
    if (
        package in {"agency-agents-main", "pacify_x_agency_agents_upgrade"}
        and suffix == ".md"
    ):
        return (
            "defer",
            "runtime/agent_provider.py",
            "lazy agent candidate body; authority remains separate",
        )
    if package == "agency-agents-app-main":
        if suffix in CODE_SUFFIXES:
            return (
                "fragment",
                "runtime/agent_provider.py",
                "extract reconciliation, hashing, install, and adapter mechanisms only",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "reference evidence for agent provider behavior",
        )
    if package == "skills-main":
        return (
            "retain",
            "runtime/project_reasoning",
            "source corpus already compared semantically; retain as provenance",
        )
    if "transcript-analysis" in package:
        return (
            "merge",
            "runtime/transcript_analysis.py",
            "parameterize transcript lifecycle and remove host-specific paths",
        )
    if "tencent" in joined and "memory_upgrade" in joined:
        if "/runtime/memory_models.py" in f"/{joined}":
            return (
                "merge",
                "runtime/memory_fabric.py",
                "layer and scope metadata merged into the canonical memory record",
            )
        if "/runtime/" in f"/{joined}":
            return (
                "merge",
                "runtime/memory_intelligence.py",
                "bounded lifecycle mechanism merged around the canonical memory vault",
            )
        if "/contracts/memory_state_transition" in f"/{joined}":
            return (
                "merge",
                "runtime/memory_vault.py",
                "state transitions remain owned by the append-only vault lifecycle",
            )
        if "/contracts/" in f"/{joined}":
            return (
                "merge",
                "contracts/memory",
                "adapted into canonical memory lifecycle contracts",
            )
        if "/orchestrations/" in f"/{joined}":
            return (
                "merge",
                "orchestration/workflows/layered-memory-lifecycle.yaml",
                "consolidated into one executable canonical workflow",
            )
        if "/skills/skill-memory-promotion" in f"/{joined}":
            return (
                "merge",
                "runtime/process_memory.py",
                "skill promotion remains owned by the existing skill foundry",
            )
        if "/skills/" in f"/{joined}":
            return (
                "merge",
                ".px/skills/govern-memory-fabric",
                "merged into existing discoverable memory and retrieval skills without duplicates",
            )
        if "/tests/" in f"/{joined}":
            return (
                "merge",
                "tests/test_memory_intelligence.py",
                "adapted behavioral and negative tests",
            )
        if "/knowledge/" in f"/{joined}" or "/registry/" in f"/{joined}":
            return (
                "merge",
                ".px/skills/govern-memory-fabric/references/layered-memory-lifecycle.md",
                "policy semantics merged into lazy-loaded operational guidance and runtime gates",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "source audit, attribution, and validation evidence retained in the intake disposition ledger",
        )
    if "brain_expansion" in package:
        if suffix in CODE_SUFFIXES or lowered.startswith(("contracts/", "registry/")):
            return (
                "merge",
                "runtime/cognitive_core",
                "target-aware cognitive integration and deterministic index rebuild",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "cognitive source evidence",
        )
    if "external-capability-intake" in source_identity:
        external_relative = (
            lowered if "external-capability-intake" in package else joined
        )
        external_parts = tuple(external_relative.split("/"))
        if external_relative.startswith("source_material/"):
            return (
                "defer",
                "runtime/external_capability_provider.py",
                "untrusted provider material remains non-canonical",
            )
        if external_relative.startswith(".agents/"):
            skill = (
                "/".join(external_parts[:3])
                if len(external_parts) >= 3
                else ".px/skills"
            )
            return (
                "merge",
                skill,
                "sanitized candidate wrapper registered with deferred lifecycle",
            )
        if external_relative.startswith("orchestration/"):
            return (
                "merge",
                "orchestration/workflows/external-capability-intake.yaml",
                "consolidated into one executable validator workflow",
            )
        if external_relative.startswith("registry/"):
            return (
                "merge",
                "registry/external_capability_catalog.json",
                "metadata-first candidate registry projection",
            )
        if external_relative.startswith("runtime/"):
            return (
                "merge",
                "runtime/external_capability_provider.py",
                "bounded external intake mechanism",
            )
        if external_relative.startswith("scripts/"):
            return (
                "fragment",
                "scripts/build_external_candidate_registry.py",
                "bounded registry, query, and validation mechanisms retained without source execution",
            )
        if external_relative.startswith("tests/"):
            return (
                "merge",
                "tests/test_external_capability_provider.py",
                "behavioral and negative controls adapted into canonical tests",
            )
        if external_relative.startswith("licenses/"):
            return (
                "merge",
                "LICENSES",
                "license and attribution material preserved in the distribution",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "source audit, inventory, and implementation guidance retained as provenance",
        )
    if "engineering-reasoning-skills-expansion" in source_identity:
        if joined == "install.py" or joined.endswith("/install.py"):
            return (
                "fragment",
                "runtime/project_reasoning",
                "dry-run and collision-checking semantics retained without overlay installation",
            )
        if joined.startswith("tests/") or "/tests/" in f"/{joined}":
            return (
                "merge",
                "tests/test_project_reasoning.py",
                "behavioral and negative reasoning tests adapted into canonical coverage",
            )
        if "source_attribution/" in joined:
            return (
                "merge",
                "LICENSES",
                "MIT license and attribution preserved in the distribution",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "reasoning source comparison and implementation guidance retained as provenance",
        )
    if "n8n_supabase_capability_pack" in source_identity.casefold():
        service_relative = (
            lowered if "n8n_supabase_capability_pack" in package else joined
        )
        if service_relative.startswith("pacify-x-overlay/"):
            service_relative = service_relative.removeprefix("pacify-x-overlay/")
        if service_relative.startswith(".px/skills/"):
            skill_id = service_relative.split("/")[2]
            return (
                "merge",
                f".px/skills/{skill_id}",
                "clean-room product skill admitted lazily with explicit effects and policy boundaries",
            )
        if service_relative.startswith("knowledge/"):
            return (
                "merge",
                ".px/skills/route-n8n-supabase-stack/references/knowledge",
                "product knowledge moved behind lazy router references",
            )
        if service_relative.startswith("orchestration/"):
            return (
                "merge",
                "orchestration/workflows/service-capability-operations.yaml",
                "candidate workflows reconciled into one validated canonical workflow document",
            )
        if service_relative.startswith("registry/skill_packages/"):
            return (
                "merge",
                "registry/skill_packages",
                "candidate manifests rebuilt with canonical lifecycle, effects, hashes, tests, and evidence",
            )
        if service_relative.startswith("registry/golden"):
            return (
                "merge",
                "registry/service_capability_golden_queries.json",
                "golden routing cases admitted as executable regression evidence",
            )
        if service_relative.startswith("registry/"):
            return (
                "merge",
                "registry/service_capability_catalog.json",
                "candidate metadata reconciled into canonical service capability registries",
            )
        if service_relative.startswith("templates/"):
            return (
                "merge",
                "templates/service_capabilities",
                "safe examples retained under an explicitly non-turnkey template namespace",
            )
        if service_relative.startswith("scripts/"):
            return (
                "fragment",
                "runtime/service_capability_provider.py",
                "validation, collision, and lazy-routing behavior retained without overlay mutation",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "source provenance, audit, coverage, or validation evidence retained",
        )
    if (
        "knowledge_refinery" in source_identity
        or "knowledge-refinery" in source_identity
    ):
        if suffix in CODE_SUFFIXES:
            owner = (
                "tests/test_knowledge_refinery.py"
                if "/tests/" in f"/{joined}"
                else "runtime/knowledge_refinery.py"
            )
            return (
                "merge",
                owner,
                "knowledge admission, novelty, graph, retrieval, calibration, and staging behavior reconciled into canonical runtime",
            )
        if "/contracts/" in f"/{joined}":
            return (
                "merge",
                "contracts/knowledge_refinery",
                "source schemas adapted into canonical owned contracts",
            )
        if "/orchestrations/" in f"/{joined}":
            return (
                "merge",
                "orchestration/workflows/knowledge-refinery.yaml",
                "source workflows consolidated into one executable canonical workflow",
            )
        if "/skills/" in f"/{joined}":
            return (
                "merge",
                ".px/skills/govern-knowledge-refinery",
                "source procedures consolidated into one discoverable canonical skill",
            )
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "knowledge-refinery source evidence, configuration, examples, license, or validation record",
        )
    if suffix in CODE_SUFFIXES:
        return "merge", "runtime/capability_routing.py", "reviewed executable mechanism"
    if suffix in REFERENCE_SUFFIXES or suffix in {
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
    }:
        return (
            "retain",
            "evidence/integration/pxi-20260804",
            "reference, registry, manifest, or validation evidence",
        )
    return "reject", "none", "non-capability packaging or binary asset"


def build_source_disposition(
    root: Path,
    source_root: Path,
    *,
    source_alias: str,
    expected_tree_sha256: str | None = None,
) -> dict[str, object]:
    """Account for every incoming regular file and propose its canonical fate."""
    root = root.resolve(strict=True)
    source_root = source_root.resolve(strict=True)
    records: list[dict[str, object]] = []
    inventory: list[tuple[str, int, str]] = []
    for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
        relative = path.relative_to(source_root).as_posix()
        digest = _sha(path)
        size = path.stat().st_size
        inventory.append((relative, size, digest))
        parts = tuple(relative.split("/"))
        source_identity = f"{source_alias.casefold()}/{relative.casefold()}"
        target = (
            None
            if "n8n_supabase_capability_pack" in source_identity
            or "pacify-x-full-project-mapping-pack" in source_identity
            else _overlay_target(parts)
        )
        if any(part in CACHE_PARTS for part in parts):
            disposition, owner, rationale = _planned_owner(
                parts, path.suffix.casefold(), source_alias=source_alias
            )
            target = None
        elif target:
            target_path = root / target
            if target_path.is_file() and _sha(target_path) == digest:
                disposition, owner, rationale = (
                    "retain",
                    target,
                    "exact target duplicate; canonical target retained",
                )
            elif target_path.exists():
                disposition, owner, rationale = (
                    "merge",
                    target,
                    "target exists; semantic merge and target tests required",
                )
            else:
                disposition, owner, rationale = (
                    "admit",
                    target,
                    "new overlay target pending admission and validation",
                )
        else:
            disposition, owner, rationale = _planned_owner(
                parts, path.suffix.casefold(), source_alias=source_alias
            )
        records.append(
            {
                "source_path": relative,
                "bytes": size,
                "sha256": digest,
                "disposition": disposition,
                "canonical_owner": owner,
                "target_path": target,
                "rationale": rationale,
            }
        )
    inventory_sha256 = _stable(inventory)
    counts = dict(sorted(Counter(str(item["disposition"]) for item in records).items()))
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "generator": "pacify-x.integration-disposition/1.0.0",
        "source_alias": source_alias,
        "expected_tree_sha256": expected_tree_sha256,
        "inventory_sha256": inventory_sha256,
        "file_count": len(records),
        "byte_count": sum(int(item["bytes"]) for item in records),
        "unaccounted_count": 0,
        "disposition_counts": counts,
        "records": records,
    }
    payload["report_sha256"] = _stable(payload)
    return payload


def validate_source_disposition(report: Mapping[str, object]) -> dict[str, object]:
    records = report.get("records")
    errors: list[str] = []
    if not isinstance(records, list):
        return {"valid": False, "errors": ["records must be a list"]}
    paths = [
        str(item.get("source_path", "")) for item in records if isinstance(item, dict)
    ]
    if len(paths) != len(records) or len(set(paths)) != len(paths):
        errors.append("source paths must be non-empty and unique")
    allowed = {
        "admit",
        "merge",
        "retain",
        "replace",
        "fragment",
        "defer",
        "quarantine",
        "reject",
        "derived-regenerate",
    }
    for item in records:
        if not isinstance(item, dict):
            errors.append("record must be an object")
            continue
        if item.get("disposition") not in allowed:
            errors.append(f"invalid disposition: {item.get('source_path')}")
        if not item.get("canonical_owner") or not item.get("sha256"):
            errors.append(f"missing owner or hash: {item.get('source_path')}")
    if report.get("file_count") != len(records):
        errors.append("file_count mismatch")
    if report.get("unaccounted_count") != 0:
        errors.append("unaccounted source files remain")
    expected_hash = _stable(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    if report.get("report_sha256") != expected_hash:
        errors.append("report hash mismatch")
    return {"valid": not errors, "file_count": len(records), "errors": errors}
