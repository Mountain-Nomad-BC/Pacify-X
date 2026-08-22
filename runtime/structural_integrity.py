"""Closed-world structural integrity audit for mature-framework drift."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import sys
import tomllib
from typing import Any

from .bounded_walk import WalkLimits, bounded_walk
from .repository_scope import is_external_environment_relative, is_project_source

from .version import VERSION


DUPLICATE_CLASSIFICATIONS = {
    "empty-package-markers": {
        "owner": "package-layout",
        "rationale": "Python package markers",
        "authoritative_source": "package layout",
        "regeneration_command": None,
        "equivalence_rule": "empty file",
    },
    "generated-domain-tool-projections": {
        "owner": "templates/generated/domain_tool.py",
        "rationale": "portable generated tool projection",
        "authoritative_source": "templates/generated/domain_tool.py",
        "regeneration_command": "template regeneration",
        "equivalence_rule": "byte-for-byte",
    },
    "generated-declared-suite-projections": {
        "owner": "templates/declared_suite",
        "rationale": "declared test-suite projections",
        "authoritative_source": "templates/declared_suite",
        "regeneration_command": "declared-suite generator",
        "equivalence_rule": "byte-for-byte",
    },
    "generated-profile-projections": {
        "owner": "bootstrap/profiles",
        "rationale": "portable bootstrap profile projection",
        "authoritative_source": "bootstrap/profiles",
        "regeneration_command": "commission profile projection",
        "equivalence_rule": "byte-for-byte",
    },
    "portable-skill-hash-helpers": {
        "owner": ".px/skills",
        "rationale": "portable skill-local helpers",
        "authoritative_source": "shared behavioral contract",
        "regeneration_command": None,
        "equivalence_rule": "behavioral parity",
    },
    "bounded-cli-boilerplate": {
        "owner": "scripts",
        "rationale": "small explicit command entrypoints",
        "authoritative_source": "each script",
        "regeneration_command": None,
        "equivalence_rule": "entrypoint behavior",
    },
    "digest-adapters": {
        "owner": "runtime",
        "rationale": "bounded digest adapters",
        "authoritative_source": "hash contract",
        "regeneration_command": None,
        "equivalence_rule": "behavioral parity",
    },
    "json-atomic-write": {
        "owner": "runtime",
        "rationale": "bounded JSON write helpers share identical write-through and failure semantics",
        "authoritative_source": "runtime workflow state ownership",
        "regeneration_command": None,
        "equivalence_rule": "behavioral parity",
    },
    "bounded-progress-envelope": {
        "owner": "runtime",
        "rationale": "bounded operational progress formatting and truncation logic is intentionally duplicated",
        "authoritative_source": "runtime operational progress contract",
        "regeneration_command": None,
        "equivalence_rule": "behavioral parity",
    },
    "ledger-authority-head-anchor": {
        "owner": "runtime/event_ledger.py",
        "rationale": "the current authority head is an exact recoverable projection of its immutable sequence anchor",
        "authoritative_source": ".engineering-bootstrap/commissioning-events",
        "regeneration_command": "append chained event",
        "equivalence_rule": "byte-for-byte",
    },
    "studio-operation-projections": {
        "owner": "registry/studio_operations.json",
        "rationale": "runtime and extension consume exact projections of the canonical Studio operation contract",
        "authoritative_source": "registry/studio_operations.json",
        "regeneration_command": "python scripts/reconcile_studio_operation_projections.py",
        "equivalence_rule": "byte-for-byte",
    },
    "global-skill-isolation-reconciliation-snapshots": {
        "owner": "runtime/global_skill_isolation.py",
        "rationale": "independent reconciliation campaigns retain matching pre-move and stability snapshots as evidence",
        "authoritative_source": ".px/global-skill-isolation",
        "regeneration_command": "python -m runtime.cli skill-host-isolation reconcile",
        "equivalence_rule": "byte-for-byte matching snapshot evidence",
    },
    "bounded-json-loaders": {
        "owner": "scripts",
        "rationale": "small evidence assemblers use the same fail-closed JSON object loader contract",
        "authoritative_source": "each bounded evidence assembler",
        "regeneration_command": None,
        "equivalence_rule": "behavioral parity",
    },
    "native-skill-manifest-aliases": {
        "owner": "runtime/native_skills.py",
        "rationale": "capability.json and skill.yaml are equivalent machine-readable views of one PX-native manifest",
        "authoritative_source": "runtime/native_skills.py",
        "regeneration_command": "python scripts/migrate_px_skills.py --apply",
        "equivalence_rule": "byte-for-byte canonical JSON, which is valid YAML",
    },
    "native-skill-surface-scaffolds": {
        "owner": "runtime/native_skills.py",
        "rationale": "empty native contracts, tests, and resources use explicit standardized descriptors",
        "authoritative_source": "runtime/native_skills.py",
        "regeneration_command": "python scripts/migrate_px_skills.py --apply",
        "equivalence_rule": "byte-for-byte by surface kind",
    },
    "native-skill-policy-projections": {
        "owner": "root policy registry",
        "rationale": "portable PX-native skill packages retain byte-identical local policy resources",
        "authoritative_source": "policies",
        "regeneration_command": "python scripts/migration/sync_skill_packaging.py",
        "equivalence_rule": "byte-for-byte",
    },
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_inactive_derived_path(path: Path, root: Path) -> bool:
    """Exclude retained custody and versioned map projections from source audits."""
    if not is_project_source(path, root):
        return True
    parts = path.relative_to(root).parts
    if (
        parts
        and parts[0] == ".engineering-bootstrap"
        and any(
            parts[index : index + 2] == ("wal", "committed")
            for index in range(1, len(parts) - 1)
        )
    ):
        return True
    return len(parts) >= 2 and parts[0] == ".engineering-bootstrap" and parts[1] in {
        "environment",
        "diagnostics",
        "project-map",
        "project-map-history",
        "project-map-lock-history",
        "quarantine",
    }


def _exclude_structural_path(relative: str) -> bool:
    if is_external_environment_relative(relative):
        return True
    parts = Path(relative).parts
    if not parts:
        return False
    if parts[0] == "evidence" or "__pycache__" in parts:
        return True
    if (
        parts[0] == ".engineering-bootstrap"
        and any(
            parts[index : index + 2] == ("wal", "committed")
            for index in range(1, len(parts) - 1)
        )
    ):
        return True
    return len(parts) >= 2 and parts[0] == ".engineering-bootstrap" and parts[1] in {
        "environment", "diagnostics", "project-map", "project-map-history",
        "project-map-lock-history", "quarantine",
    }


def _structural_files(root: Path) -> tuple[Path, ...]:
    walk = bounded_walk(
        root,
        limits=WalkLimits(max_files=100_000, max_depth=128, max_bytes=2 * 1024**3),
        symlink_policy="skip",
        exclude=_exclude_structural_path,
    )
    return tuple(entry.path for entry in walk.files)


def _cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    found: set[tuple[str, ...]] = set()

    def visit(node: str, active: list[str], active_set: set[str]) -> None:
        if node in active_set:
            start = active.index(node)
            cycle = active[start:] + [node]
            rotations = [
                tuple(cycle[index:-1] + cycle[:index] + [cycle[index]])
                for index in range(len(cycle) - 1)
            ]
            found.add(min(rotations))
            return
        if len(active) > len(edges) + 1:
            return
        for target in sorted(edges.get(node, ())):
            visit(target, [*active, node], {*active_set, node})

    for node in sorted(edges):
        visit(node, [], set())
    return [list(item) for item in sorted(found)]


def _import_cycles(root: Path) -> list[list[str]]:
    modules: dict[str, Path] = {}
    for folder in ("runtime", "builders"):
        for path in (root / folder).rglob("*.py"):
            relative = path.relative_to(root).with_suffix("")
            parts = list(relative.parts)
            if parts[-1] == "__init__":
                parts.pop()
            modules[".".join(parts)] = path
    edges: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=path.as_posix())
        package = name.rsplit(".", 1)[0] if "." in name else name
        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    prefix = base[: max(0, len(base) - node.level + 1)]
                    candidates.append(
                        ".".join([*prefix, node.module or ""]).rstrip(".")
                    )
                elif node.module:
                    candidates.append(node.module)
            for candidate in candidates:
                match = next(
                    (
                        module
                        for module in modules
                        if candidate == module or candidate.startswith(module + ".")
                    ),
                    None,
                )
                if match and match != name:
                    edges[name].add(match)
    return _cycles(edges)


def _classify_exact_group(paths: list[str]) -> str | None:
    path_set = set(paths)
    if (
        len(paths) == 2
        and all(path.startswith(".px/skills/") for path in paths)
        and {Path(path).name for path in paths} == {"capability.json", "skill.yaml"}
        and len({Path(path).parent for path in paths}) == 1
    ):
        return "native-skill-manifest-aliases"
    native_scaffold_suffixes = {
        "/contracts/manifest.json",
        "/resources/index.json",
        "/tests/validation.json",
    }
    if all(
        path.startswith(".px/skills/")
        and any(path.endswith(suffix) for suffix in native_scaffold_suffixes)
        for path in paths
    ):
        return "native-skill-surface-scaffolds"
    if (
        len(paths) == 2
        and sum(path.startswith("policies/") for path in paths) == 1
        and sum(
            path.startswith(".px/skills/") and "/policies/" in path
            for path in paths
        )
        == 1
        and len({Path(path).name for path in paths}) == 1
    ):
        return "native-skill-policy-projections"
    if all(path.endswith("/__init__.py") for path in paths):
        return "empty-package-markers"
    if "templates/generated/domain_tool.py" in path_set and all(
        path == "templates/generated/domain_tool.py"
        or path.endswith("/scripts/domain_tool.py")
        for path in paths
    ):
        return "generated-domain-tool-projections"
    if any(
        path.startswith("templates/declared_suite/authoritative-pack/")
        for path in paths
    ) and all(path.startswith("templates/declared_suite/") for path in paths):
        return "generated-declared-suite-projections"
    if (
        len(paths) == 2
        and any(path.startswith("bootstrap/profiles/") for path in paths)
        and any(path.startswith(".engineering-bootstrap/profiles/") for path in paths)
    ):
        return "generated-profile-projections"
    if path_set == {
        "extension/resources/studio-operations.json",
        "registry/studio_operations.json",
        "runtime/studio_operations.json",
    }:
        return "studio-operation-projections"
    if len(paths) >= 2 and all(
        path.startswith(".px/global-skill-isolation/reconcile-")
        and "-snapshot-" in path
        and path.endswith(".json")
        for path in paths
    ):
        return "global-skill-isolation-reconciliation-snapshots"
    if (
        len(paths) == 2
        and all(
            path.startswith(".engineering-bootstrap/.ledger-authority/")
            for path in paths
        )
        and any(path.endswith("/head.json") for path in paths)
        and any("/anchors/" in path for path in paths)
    ):
        return "ledger-authority-head-anchor"
    if len(paths) == 2 and set(Path(path).name for path in paths) == {
        "_write_json",
        "_atomic_json",
    }:
        return "json-atomic-write"
    return None


def _duplicate_files(root: Path, files: tuple[Path, ...] | None = None) -> tuple[list[dict[str, Any]], list[list[str]]]:
    groups: dict[str, list[str]] = {}
    extensions = {".py", ".json", ".yaml", ".yml", ".toml", ".md"}
    for path in files if files is not None else _structural_files(root):
        if (
            not path.is_file()
            or path.suffix.casefold() not in extensions
            or _is_inactive_derived_path(path, root)
            or any(part in {"evidence", "__pycache__"} for part in path.parts)
        ):
            continue
        groups.setdefault(_sha(path), []).append(path.relative_to(root).as_posix())
    reviewed = []
    unreviewed = []
    for digest, paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        paths.sort()
        classification = _classify_exact_group(paths)
        record = {
            "sha256": digest,
            "paths": paths,
            "classification": classification or "unreviewed",
            **(DUPLICATE_CLASSIFICATIONS.get(classification, {})),
        }
        reviewed.append(record)
        if classification is None:
            unreviewed.append(paths)
    return reviewed, unreviewed


def _stable_ast(value: object, *, function_root: bool = False) -> object:
    """Serialize semantic AST fields without interpreter-added metadata."""
    if isinstance(value, ast.AST):
        fields = []
        for name, child in ast.iter_fields(value):
            if name in {"type_comment", "type_params"}:
                continue
            if function_root and name == "name":
                child = "_"
            elif function_root and name == "decorator_list":
                child = []
            fields.append((name, _stable_ast(child)))
        return (type(value).__name__, tuple(fields))
    if isinstance(value, list):
        return tuple(_stable_ast(item) for item in value)
    return value


def _logic_duplicates(root: Path, files: tuple[Path, ...] | None = None) -> tuple[list[dict[str, Any]], list[list[str]]]:
    groups: dict[str, list[str]] = {}
    for path in files if files is not None else _structural_files(root):
        if path.suffix.casefold() != ".py":
            continue
        if "__pycache__" in path.parts or _is_inactive_derived_path(path, root):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if (
                not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                or len(node.body) < 3
            ):
                continue
            digest = hashlib.sha256(
                repr(_stable_ast(node, function_root=True)).encode()
            ).hexdigest()
            groups.setdefault(digest, []).append(
                f"{path.relative_to(root).as_posix()}:{node.lineno}:{node.name}"
            )
    records = []
    unreviewed = []
    for digest, locations in sorted(groups.items()):
        if len(locations) < 2:
            continue
        paths = [item.split(":", 1)[0] for item in locations]
        names = {item.rsplit(":", 1)[-1] for item in locations}
        if all(
            "/.px/skills/" in "/" + path and "/scripts/" in path for path in paths
        ) and names <= {"hash_file", "sha256_file", "_sha256"}:
            classification = "portable-skill-hash-helpers"
        elif names == {"main"} and all(path.startswith("scripts/") for path in paths):
            classification = "bounded-cli-boilerplate"
        elif names == {"_write_json", "_atomic_json"} and all(
            path in {"runtime/work_admission.py", "runtime/global_skill_isolation.py"}
            for path in paths
        ):
            classification = "json-atomic-write"
        elif names == {"_load"} and set(paths) == {
            "scripts/assemble_operational_control_evidence.py",
            "scripts/build_installed_probe_control_evidence.py",
        }:
            classification = "bounded-json-loaders"
        elif names == {"_bounded_operational_progress", "_bounded_progress"} and all(
            path.startswith("runtime/") for path in paths
        ):
            classification = "bounded-progress-envelope"
        elif names <= {
            "_sha",
            "_sha_file",
            "_digest",
            "file_hash",
            "hash_file",
            "_file_sha256",
            "_sha256",
            "sha256_file",
        }:
            classification = "digest-adapters"
        else:
            classification = "unreviewed"
            unreviewed.append(locations)
        records.append(
            {
                "signature_sha256": digest,
                "locations": locations,
                "classification": classification,
                **(DUPLICATE_CLASSIFICATIONS.get(classification, {})),
            }
        )
    return records, unreviewed


def _resolve_entrypoint(entrypoint: str) -> bool:
    if not entrypoint or ":" not in entrypoint:
        return False
    module_name, attributes = entrypoint.split(":", 1)
    try:
        value: Any = importlib.import_module(module_name)
        for attribute in attributes.split("."):
            value = getattr(value, attribute)
        return callable(value)
    except (ImportError, AttributeError):
        return False


def _workflow_errors(root: Path) -> list[str]:
    errors = []
    project_defs = {
        path.stem
        for path in (root / "orchestration/workflows/project_stream").glob("*.yaml")
    }
    registry = _json(root / "registry/project_stream_orchestrations.json")
    handlers = _json(root / "registry/project_stream_handlers.json")
    registry_ids = {
        str(item["orchestration_id"]) for item in registry["orchestrations"]
    }
    handler_ids = {
        str(item["orchestration_id"])
        for item in handlers["workflows"]
        if item.get("status") == "executable"
    }
    from .project_stream_orchestrator import BUILTIN_HANDLERS

    if not (project_defs == registry_ids == handler_ids == set(BUILTIN_HANDLERS)):
        errors.append(
            f"project-stream reachability mismatch: definitions={len(project_defs)} registry={len(registry_ids)} handlers={len(handler_ids)} runtime={len(BUILTIN_HANDLERS)}"
        )
    bindings = _json(root / "registry/workflow_execution_bindings.json")
    general_defs = {
        path.relative_to(root).as_posix()
        for path in (root / "orchestration/workflows").glob("*.yaml")
    }
    bound = {str(item["path"]): item for item in bindings["bindings"]}
    if bindings.get("count") != len(
        bindings.get("bindings", ())
    ) or general_defs != set(bound):
        errors.append("general orchestration definition/binding denominator mismatch")
    for path, item in bound.items():
        if not _resolve_entrypoint(str(item.get("entrypoint", ""))):
            errors.append(f"unexecutable orchestration binding: {path}")
    catalog = tomllib.loads(
        (root / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    skills = {
        str(item["id"])
        for item in catalog["skills"]
        if item.get("status") in {"active", "admitted"}
    }
    orchestrations = _json(root / "registry/skill_orchestrations.json")
    for workflow in orchestrations["workflows"]:
        step_ids = {str(item["id"]) for item in workflow["steps"]}
        edges = {
            str(item["id"]): set(map(str, item.get("depends_on", ())))
            for item in workflow["steps"]
        }
        for item in workflow["steps"]:
            if item.get("skill") not in skills:
                errors.append(
                    f"{workflow['id']}: undiscoverable/non-active skill {item.get('skill')}"
                )
            unknown = set(map(str, item.get("depends_on", ()))) - step_ids
            if unknown:
                errors.append(
                    f"{workflow['id']}: unknown step dependencies {sorted(unknown)}"
                )
        if _cycles(edges):
            errors.append(f"{workflow['id']}: circular step dependency")
    return errors


def _skill_errors(root: Path) -> list[str]:
    catalog = tomllib.loads(
        (root / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    catalog_ids = {str(item["id"]) for item in catalog["skills"]}
    directory_ids = {
        path.name for path in (root / ".px/skills").iterdir() if path.is_dir()
    }
    semantic_ids = {
        str(item["id"])
        for item in _json(root / "registry/semantic_capability_index.json")["records"]
        if item.get("kind") == "skill"
    }
    errors = []
    if catalog_ids != directory_ids:
        errors.append(
            f"skill catalog/directory mismatch: catalog-only={sorted(catalog_ids - directory_ids)} directory-only={sorted(directory_ids - catalog_ids)}"
        )
    if catalog_ids != semantic_ids:
        errors.append(
            f"skill discovery mismatch: absent-from-index={sorted(catalog_ids - semantic_ids)} orphan-index={sorted(semantic_ids - catalog_ids)}"
        )
    return errors


def _policy_errors(root: Path) -> list[str]:
    index = _json(root / "policies/policy_index.json")
    bodies = {str(item.get("body")) for item in index.get("policies", ())}
    files = {
        path.relative_to(root).as_posix()
        for path in (root / "policies").glob("*.json")
        if path.name not in {"policy_index.json", "imported_rule_index.json"}
    }
    errors = []
    if bodies != files:
        errors.append(
            f"policy index drift: unindexed={sorted(files - bodies)} missing={sorted(bodies - files)}"
        )
    startup = set(map(str, index.get("startup_policy_ids", ())))
    identifiers = {str(item.get("id")) for item in index.get("policies", ())}
    if not startup <= identifiers:
        errors.append(
            f"startup policy IDs are unknown: {sorted(startup - identifiers)}"
        )
    return errors


def _document_errors(root: Path, release_open: bool) -> list[str]:
    errors = []
    policy = _json(root / "registry/structural_integrity_policy.json")
    active_files = [root / item for item in policy["active_release_files"]]
    for path in active_files:
        if not path.is_file():
            errors.append(
                f"missing active release document: {path.relative_to(root).as_posix()}"
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in ("\ufffd", "â€”", "â†’", "Ã¢"):
            if marker in text:
                errors.append(
                    f"corrupted text in {path.relative_to(root).as_posix()}: {marker!r}"
                )
    if release_open:
        for path in active_files:
            if not path.is_file() or path.suffix.casefold() not in {
                ".md",
                ".py",
                ".toml",
            }:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            claim_surface = re.sub(r"[*_`]", "", text)
            for claim in policy["forbidden_active_claims_while_open"]:
                if claim in claim_surface:
                    errors.append(
                        f"stale deployment claim in {path.relative_to(root).as_posix()}: {claim}"
                    )
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(project["project"]["version"])
    cli_text = (root / "runtime/cli.py").read_text(encoding="utf-8")
    project_management_text = (root / "runtime/project_management.py").read_text(
        encoding="utf-8"
    )
    if (
        version != VERSION
        or "from .version import VERSION" not in cli_text
        or 'version=f"%(prog)s {VERSION}"' not in cli_text
    ):
        errors.append("CLI/package version drift")
    if (
        "from .version import VERSION" not in project_management_text
        or '"runtime_version": VERSION' not in project_management_text
    ):
        errors.append("commissioned-project runtime version drift")
    execution_plan = root / "EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md"
    if execution_plan.is_file():
        execution_text = execution_plan.read_text(encoding="utf-8", errors="replace")
        if (
            "`REL-006` is complete" in execution_text
            or "release-certification-0.5.0.json" in execution_text
        ):
            errors.append("execution-plan document is pinned to revoked release state")
    state = _json(root / ".engineering-bootstrap/project-management/state.json")
    lifecycle_next = state.get("lifecycle", {}).get("next_action")
    checkpoint_next = state.get("checkpoint", {}).get("next_safe_action")
    if lifecycle_next != checkpoint_next:
        errors.append("project-management lifecycle/checkpoint drift")
    if state.get("checkpoint", {}).get("runtime_version") != version:
        errors.append("project-management/package version drift")
    for obsolete in (
        "scripts/finalize_rel008_release.py",
        "scripts/finalize_rel009_release.py",
    ):
        if (root / obsolete).exists():
            errors.append(f"obsolete release mutator remains deployable: {obsolete}")
    for document in (root / "README.md", root / "START_HERE_FOR_AI.md"):
        if document.is_file():
            text = document.read_text(encoding="utf-8", errors="replace")
            if "README" in document.name and f"v{version}" not in text:
                errors.append("README/package version drift")
    readme = root / "README.md"
    if readme.is_file():
        readme_text = readme.read_text(encoding="utf-8", errors="replace")
        framework_scripts = len(tuple((root / "scripts").glob("*.py")))
        skill_scripts = len(tuple((root / ".px/skills").glob("*/scripts/*.py")))
        denominators = {
            "Runtime modules": len(tuple((root / "runtime").rglob("*.py"))),
            "Contracts": len(tuple((root / "contracts").rglob("*.json"))),
            "Registry artifacts": sum(
                1 for path in (root / "registry").rglob("*") if path.is_file()
            ),
            "Tool and support scripts": framework_scripts + skill_scripts,
        }
        for label, actual in denominators.items():
            match = re.search(rf"(?m)^\| {re.escape(label)} \| (\d+) \|", readme_text)
            if not match or int(match.group(1)) != actual:
                errors.append(f"README denominator drift: {label} expected {actual}")
    return errors


def _example_errors(root: Path) -> list[str]:
    errors = []
    top_level = {
        "validate",
        "doctor",
        "lifecycle",
        "contracts",
        "integrations",
        "graphs",
        "audit",
        "process",
        "research",
        "startup",
        "tooling",
        "classify",
        "select",
        "working-set",
        "hydrate",
        "commission",
        "intake",
        "source-intake",
        "profiles",
        "test-profile",
        "release",
        "brief",
        "tool-intake",
        "tools",
        "project-check",
        "specialties",
        "plan",
        "review-candidate",
        "authorize",
        "verify-outcome",
        "retry-decision",
        "workspace",
        "project",
        "memory",
        "workflow",
        "declared-suite",
        "metacognitive",
        "scheduling",
    }
    nested = {
        "workspace": {
            "init",
            "discover",
            "create-project",
            "status",
            "monitor",
            "rebuild",
        },
        "project": {
            "activate",
            "current",
            "release",
            "list",
            "show",
            "renew",
            "transition",
        },
        "workflow": {"list", "run"},
        "release": {"verify", "finalize", "manifest", "environment"},
        "test-profile": {"show", "run"},
        "tooling": {"assess"},
    }
    for path in (root / "README.md", root / "START_HERE_FOR_AI.md"):
        if not path.is_file():
            continue
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            stripped = line.strip()
            if not stripped.startswith("engineering-bootstrap "):
                continue
            normalized = re.sub(r"<[^>]+>", "fixture", stripped)
            try:
                arguments = shlex.split(normalized, posix=False)[1:]
                if not arguments or arguments[0] not in top_level:
                    raise ValueError("unknown top-level command")
                if arguments[0] in nested and (
                    len(arguments) < 2 or arguments[1] not in nested[arguments[0]]
                ):
                    raise ValueError("unknown nested command")
            except ValueError:
                errors.append(f"invalid documented CLI example: {path.name}:{line_no}")
    return errors


def _marker_result(root: Path) -> dict[str, Any]:
    path = (
        root
        / ".px/skills/audit-incomplete-implementations/scripts/audit_incomplete.py"
    )
    spec = importlib.util.spec_from_file_location("_pacify_incomplete_audit", path)
    if spec is None or spec.loader is None:
        return {"complete": False, "errors": [{"error": "audit_loader_missing"}]}
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module.audit(
        root, review_registry=root / "registry/incomplete_finding_reviews.json"
    )


def audit_structural_integrity(root: Path) -> dict[str, Any]:
    root = root.resolve()
    state = _json(root / ".engineering-bootstrap/project-management/state.json")
    release_open = state.get("lifecycle", {}).get("status") != "complete"
    structural_files = _structural_files(root)
    exact_groups, exact_unreviewed = _duplicate_files(root, structural_files)
    logic_groups, logic_unreviewed = _logic_duplicates(root, structural_files)
    reachability_expected = _json(root / "registry/artifact_reachability.json")
    from .artifact_reachability import build_artifact_reachability

    reachability_actual = build_artifact_reachability(root)
    reachability_errors = (
        []
        if reachability_expected == reachability_actual
        else ["artifact reachability inventory is stale"]
    )
    for record in reachability_expected.get("records", ()):
        if not (root / str(record.get("path", ""))).is_file():
            reachability_errors.append(f"missing owned artifact: {record.get('path')}")
        if not (root / str(record.get("owner", ""))).is_file():
            reachability_errors.append(f"missing artifact owner: {record.get('owner')}")
        if record.get("kind") == "orchestration" and not _resolve_entrypoint(
            str(record.get("entrypoint", ""))
        ):
            reachability_errors.append(
                f"unreachable orchestration: {record.get('path')}"
            )
    marker = _marker_result(root)
    from .contracts import validate_contract_corpus
    from .corrective_release import validate_corrective_ledger
    from .dependency_audit import validate_dependency_closure
    from .generated_artifacts import validate_generated_artifacts
    from .registry import validate_registry

    def checked(name: str, operation: Any) -> dict[str, Any]:
        try:
            return operation(root)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            tomllib.TOMLDecodeError,
        ) as error:
            return {
                "valid": False,
                "errors": [
                    f"{name} validation failed closed: {type(error).__name__}: {error}"
                ],
            }

    contract_result = checked("contract corpus", validate_contract_corpus)
    corrective_result = checked("corrective release", validate_corrective_ledger)
    dependency_result = checked("dependency closure", validate_dependency_closure)
    generated_result = checked("generated artifacts", validate_generated_artifacts)
    registry_result = checked("registry", validate_registry)
    categories = {
        "duplicate_files": []
        if not exact_unreviewed
        else [f"unreviewed exact duplicate group: {item}" for item in exact_unreviewed],
        "duplicate_logic": []
        if not logic_unreviewed
        else [f"unreviewed duplicate logic group: {item}" for item in logic_unreviewed],
        "reachability": reachability_errors,
        "skills": _skill_errors(root),
        "policies": _policy_errors(root),
        "orchestrations": _workflow_errors(root),
        "imports": [
            f"Python import cycle: {' -> '.join(item)}" for item in _import_cycles(root)
        ],
        "markers": []
        if marker.get("complete")
        else [
            f"incomplete marker audit failed: {marker.get('errors')} unreviewed={marker.get('unreviewed_count')}"
        ],
        "documentation": _document_errors(root, release_open),
        "examples": _example_errors(root),
        "contracts": list(contract_result.get("errors", ())),
        "dependencies": list(dependency_result.get("errors", ())),
        "generated_artifacts": list(
            generated_result.get("errors", generated_result.get("failed", ()))
        ),
        "registries": list(registry_result.get("errors", ())),
        "corrective_release": list(corrective_result.get("errors", ())),
    }
    errors = [
        f"{category}: {error}"
        for category, values in categories.items()
        for error in values
    ]
    required_items = _json(root / "registry/structural_integrity_policy.json")[
        "required_audit_items"
    ]
    audit_items = {
        item["id"]: {
            "passed": all(not categories[category] for category in item["categories"]),
            "categories": item["categories"],
        }
        for item in required_items
    }
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "release_open": release_open,
        "category_count": len(categories),
        "categories": {
            key: {"passed": not value, "errors": value}
            for key, value in categories.items()
        },
        "duplicate_file_groups": exact_groups,
        "duplicate_logic_groups": logic_groups,
        "marker_findings": marker.get("finding_count", 0),
        "reachability_records": reachability_expected.get("record_count", 0),
        "required_audit_item_count": len(audit_items),
        "audit_items": audit_items,
        "errors": errors,
    }
