"""Canonical authored / generated / vendored source boundary for PX.

This module is the CPU-authoritative answer to a single question: for any path
in the repository, is the content AUTHORED, GENERATED, VENDORED, EVIDENCE, or
RUNTIME STATE?

Why this exists
---------------
Generated projections were living inside source-shaped paths, where nothing
distinguished them from authored source. That made the authored-source census,
the source integrity calculation, and the "unbuilt workspace" measurement all
silently count build output as if a human had written it. Worse, a hand edit to
a generated file is silently destroyed on the next generator run, so an agent
can burn a repair on a file that was never theirs to change.

Two invariants are enforced here, not merely documented:

1. Every generated artifact MUST name an attributable generator that exists on
   disk. A generated entry with no resolvable generator is a validation failure,
   never a silent classification.

2. A generated artifact MUST NOT become the canonical authority for facts about
   the system that generated it. Engine identity is the concrete case: the
   architecture atlas is generated FROM repository source, so it must not feed
   back into that same identity. ``runtime.engine_identity`` already enforces
   this by excluding the atlas; ``assert_generated_never_canonical_authority``
   makes the rule explicit and testable rather than incidental.

Classification precedence matters and is fixed:
    evidence > runtime_state > vendored > packaging_generated > generated > authored
The most specific claim about a path wins, so an evidence file that happens to
sit under a vendored directory is still classified as evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from .bounded_walk import _is_junction
from typing import Any, Iterable

BOUNDARY_SCHEMA = "px.source-boundary/1.0"
ARTIFACT_SCHEMA = "px.generated-artifact/1.0"
BOUNDARY_RELATIVE = Path("registry/source_boundary.json")

# The engineering-OS control directory was renamed to
# ".agentic_engineering_os_px" by owner decision. Every control-directory rule
# below is still spelled with the legacy name, because the legacy tree is where
# all preserved evidence and all recorded receipt references still live.
#
# Rather than duplicating every rule, a canonical-named control path is folded
# onto the legacy spelling before classification. That keeps classification
# identical for both spellings and guarantees a partially migrated tree cannot
# silently change the governed source boundary: an unrecognized canonical
# control path would otherwise fall through to AUTHORED and enter the authored
# digest as if it were source.
try:  # pragma: no cover - exercised by the standalone atlas spec-load
    from runtime.engineering_os_paths import (  # noqa: E402  (name owner, no cycle)
        CANONICAL_CONTROL_DIR, LEGACY_CONTROL_DIR,
    )
except ModuleNotFoundError:
    # The atlas (docs/architecture/tools/build_atlas.py) loads this module by
    # file path with the repository root not on sys.path. The control-directory
    # names are a fixed owner decision, so the standalone fallback preserves
    # exactly the same classification rather than failing the atlas build.
    CANONICAL_CONTROL_DIR = ".agentic_engineering_os_px"
    LEGACY_CONTROL_DIR = ".engineering-bootstrap"


def _normalize_control_dir(path: str) -> str:
    """Fold a canonical control-directory prefix onto the legacy spelling.

    Only the leading path segment is rewritten, and only when it exactly
    matches the canonical name. Interior segments and every other path are
    returned unchanged, so no other boundary rule can be affected.
    """
    if path == CANONICAL_CONTROL_DIR:
        return LEGACY_CONTROL_DIR
    prefix = CANONICAL_CONTROL_DIR + "/"
    if path.startswith(prefix):
        return LEGACY_CONTROL_DIR + "/" + path[len(prefix):]
    return path

# --- classifications -------------------------------------------------------

AUTHORED = "authored"
GENERATED = "generated"
VENDORED = "vendored"
EVIDENCE = "evidence"
RUNTIME_STATE = "runtime_state"
PACKAGING_GENERATED = "packaging_generated"
RUNTIME_REQUIRED_GENERATED = "runtime_required_generated"

CLASSIFICATIONS = (
    AUTHORED,
    GENERATED,
    VENDORED,
    EVIDENCE,
    RUNTIME_STATE,
    PACKAGING_GENERATED,
    RUNTIME_REQUIRED_GENERATED,
)

# Precedence: the first matching class wins, so narrower claims override broader.
_PRECEDENCE = (
    EVIDENCE,
    RUNTIME_STATE,
    VENDORED,
    PACKAGING_GENERATED,
    RUNTIME_REQUIRED_GENERATED,
    GENERATED,
    AUTHORED,
)


@dataclass(frozen=True)
class GeneratedArtifact:
    """One generated output, with the provenance needed to regenerate it.

    ``generator_path`` must exist on disk. ``generator`` names the tool, and
    ``generator_owner`` names the canonical owner of that tool, so a generated
    file can always be traced to a human- or system-owned source of truth.
    """

    path: str
    classification: str
    generator: str
    generator_path: str
    generator_owner: str
    regeneration_command: str
    inputs: tuple[str, ...] = ()
    consumers: tuple[str, ...] = ()
    deterministic: bool = True
    # Whether the named regeneration_command can actually run today. A generator
    # that is present but inoperable must not be presented as a working
    # regeneration path; see PX-GAP-0008 for the live example.
    regenerable: bool = True
    # unbuilt_presence is the machine-testable answer to "may this be absent in
    # an unbuilt checkout?" values: required | optional | absent_by_definition
    unbuilt_presence: str = "optional"
    notes: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "classification": self.classification,
            "generator": self.generator,
            "generator_path": self.generator_path,
            "generator_owner": self.generator_owner,
            "regeneration_command": self.regeneration_command,
            "inputs": list(self.inputs),
            "consumers": list(self.consumers),
            "deterministic": self.deterministic,
            "regenerable": self.regenerable,
            "unbuilt_presence": self.unbuilt_presence,
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "GeneratedArtifact":
        return cls(
            path=str(value["path"]),
            classification=str(value["classification"]),
            generator=str(value["generator"]),
            generator_path=str(value["generator_path"]),
            generator_owner=str(value["generator_owner"]),
            regeneration_command=str(value["regeneration_command"]),
            inputs=tuple(map(str, value.get("inputs", ()))),
            consumers=tuple(map(str, value.get("consumers", ()))),
            deterministic=bool(value.get("deterministic", True)),
            regenerable=bool(value.get("regenerable", True)),
            unbuilt_presence=str(value.get("unbuilt_presence", "optional")),
            notes=str(value.get("notes", "")),
        )


# --- registered generated artifacts ----------------------------------------
#
# Every entry here was confirmed by tracing the generator in source, not
# inferred from size or shape. Sizes are NOT recorded as authority; the census
# measures them.

ATLAS_GENERATOR = "docs/architecture/tools/build_atlas.py"
SKILL_PACKAGING_GENERATOR = "scripts/migration/sync_skill_packaging.py"

GENERATED_ARTIFACTS: tuple[GeneratedArtifact, ...] = (
    GeneratedArtifact(
        path="docs/architecture/ATLAS_OFFLINE.html",
        classification=GENERATED,
        generator="build_atlas.py",
        generator_path=ATLAS_GENERATOR,
        generator_owner="docs/architecture/tools/build_atlas.py",
        regeneration_command="python docs/architecture/tools/build_atlas.py",
        inputs=(
            "runtime/architecture_audit.py",
            "registry/*.json",
            "runtime/*.py",
            "extension/src/**/*.js",
        ),
        consumers=("docs/architecture presentation (offline)",),
        deterministic=False,
        unbuilt_presence="absent_by_definition",
        regenerable=False,
        notes=(
            "Emits a wall-clock generation timestamp, so repeated runs are not "
            "byte-identical. Excluded from engine identity by "
            "runtime/engine_identity.py EXCLUDED_PATHS. NOT CURRENTLY "
            "REGENERABLE: build_atlas.py reads "
            "reference/graph_baseline_architecture.json, which does not exist "
            "in the repository. See PX-GAP-0008. Published output is stale."
        ),
    ),
    GeneratedArtifact(
        path="docs/architecture/graph_data.js",
        classification=GENERATED,
        generator="build_atlas.py",
        generator_path=ATLAS_GENERATOR,
        generator_owner="docs/architecture/tools/build_atlas.py",
        regeneration_command="python docs/architecture/tools/build_atlas.py",
        inputs=("docs/architecture/data/complete_graph.json",),
        consumers=("docs/architecture presentation (offline)",),
        deterministic=False,
        unbuilt_presence="absent_by_definition",
        regenerable=False,
        notes=(
            "NOTE: this is the atlas output copy. It is NOT "
            "extension/media/graph_data.js, which does not exist in this "
            "repository and must not be registered as generated. NOT CURRENTLY "
            "REGENERABLE, see PX-GAP-0008."
        ),
    ),
    GeneratedArtifact(
        path="docs/architecture/data/",
        classification=GENERATED,
        generator="build_atlas.py",
        generator_path=ATLAS_GENERATOR,
        generator_owner="docs/architecture/tools/build_atlas.py",
        regeneration_command="python docs/architecture/tools/build_atlas.py",
        inputs=("runtime/architecture_audit.py", "registry/*.json", "runtime/*.py"),
        consumers=(
            "docs/architecture/data/canonical_systems.json (docs evidence)",
            "docs/architecture/presentation/build.md (status check)",
        ),
        deterministic=True,
        unbuilt_presence="optional",
        regenerable=False,
        notes=(
            "Directory of JSON/JSONL projections. complete_graph.json is the "
            "largest at about 21.8 MB. Excluded from engine identity by "
            "EXCLUDED_PATH_PREFIXES. NOT CURRENTLY REGENERABLE, see "
            "PX-GAP-0008."
        ),
    ),
    GeneratedArtifact(
        path="pyproject.toml#/tool.setuptools.data-files",
        classification=PACKAGING_GENERATED,
        generator="sync_skill_packaging.py",
        generator_path=SKILL_PACKAGING_GENERATOR,
        generator_owner="scripts/migration/sync_skill_packaging.py",
        regeneration_command="python scripts/migration/sync_skill_packaging.py",
        inputs=(".px/skills/**", "scripts/migration/shared.py"),
        consumers=("runtime/generated_artifacts.py:skill_packaging_projection",),
        deterministic=True,
        unbuilt_presence="optional",
        notes=(
            "Bounded by '# BEGIN GENERATED OPERATIONAL SKILL DATA FILES' and "
            "'# END GENERATED OPERATIONAL SKILL DATA FILES' markers. Only the "
            "block between the markers is generated; the rest of pyproject.toml "
            "is authored."
        ),
    ),
    GeneratedArtifact(
        path="extension/server/index.js",
        classification=PACKAGING_GENERATED,
        generator="build-mcp.js",
        generator_path="extension/scripts/build-mcp.js",
        generator_owner="extension/package.json",
        regeneration_command="npm run build:mcp --prefix extension",
        inputs=(
            "extension/server/source.mjs",
            "extension/package.json",
        ),
        consumers=("extension/package.json:files",),
        deterministic=True,
        unbuilt_presence="optional",
        notes=(
            "esbuild bundle of extension/server/source.mjs produced by "
            "extension/scripts/build-mcp.js via esbuild.buildSync(bundle=true, "
            "format='cjs', sourcemap=false). It ships in the extension package's "
            "files list but is not the extension entry point, which is "
            "./src/extension.js. Before this declaration it was classified authored, "
            "which admitted 1406374 bytes of machine-generated output into the "
            "authored denominator used by expected_build_claims and into "
            "engine_identity tree_sha256 and source_freeze. Staleness is detectable "
            "with 'npm run check:mcp --prefix extension', which is declared in "
            "extension/package.json and asserted by extension/tests/package-contract.test.js."
        ),
    ),
    GeneratedArtifact(
        path="extension/node_modules/",
        classification=VENDORED,
        generator="npm install",
        generator_path="extension/package-lock.json",
        generator_owner="extension/package.json",
        regeneration_command="npm ci --prefix extension",
        inputs=("extension/package.json", "extension/package-lock.json"),
        consumers=("extension test runtime only",),
        deterministic=True,
        unbuilt_presence="absent_by_definition",
        notes="Dependency install output, not source. Never edit; never authored.",
    ),
    GeneratedArtifact(
        path="engineering_loop_bootstrap.egg-info/",
        classification=PACKAGING_GENERATED,
        generator="setuptools.build_meta",
        generator_path="pyproject.toml",
        generator_owner="runtime/release_distribution.py",
        regeneration_command="python -m build",
        inputs=("pyproject.toml", "runtime/"),
        consumers=("Python distribution metadata tooling",),
        deterministic=False,
        regenerable=False,
        unbuilt_presence="absent_by_definition",
        notes="Exact project metadata output from the declared setuptools backend. Regeneration is unverified and builds remain on owner hold; preserved bytes are not deleted.",
    ),
    GeneratedArtifact(
        path="extension/tests/generated/plugin-lifecycle/",
        classification=GENERATED,
        generator="build-plugin-lifecycle-fixtures.js",
        generator_path="extension/scripts/build-plugin-lifecycle-fixtures.js",
        generator_owner="extension/scripts/build-plugin-lifecycle-fixtures.js",
        regeneration_command="node extension/scripts/build-plugin-lifecycle-fixtures.js",
        inputs=("extension/tests/fixtures/plugin-lifecycle/",),
        consumers=("extension/tests/extension-lifecycle-host.test.js", "extension/scripts/run-operational-ui-walk.js"),
        regenerable=False,
        unbuilt_presence="optional",
        notes="Exact generated fixture and receipt tree traced to its dedicated producer. Producer not executed in this campaign; no fixture build or installation is authorized.",
    ),
)


# --- path-class rules ------------------------------------------------------

@dataclass(frozen=True)
class BoundaryRule:
    """A path-prefix classification rule.

    ``prefix`` matches when the repository-relative posix path equals it or
    starts with it plus a separator. A file-level rule uses ``exact=True``.
    """

    prefix: str
    classification: str
    exact: bool = False
    owner: str = ""
    reason: str = ""


BOUNDARY_RULES: tuple[BoundaryRule, ...] = (
    BoundaryRule(".engineering-bootstrap/validation", EVIDENCE, owner="runtime/verification_receipts.py", reason="retained focused-test and sweep evidence; never authored source"),
    BoundaryRule("registry/planning/rev1xx/foundation", RUNTIME_STATE, owner="runtime/plan_registry.py", reason="current host admissions, native proofs and actual status transition custody"),
    BoundaryRule("registry/planning/rev1xx/current-status.json", RUNTIME_STATE, exact=True, owner="runtime/plan_registry.py", reason="current campaign status projection"),
    BoundaryRule("registry/planning/rev1xx/status-history", RUNTIME_STATE, owner="runtime/plan_registry.py", reason="retained actual current campaign transitions"),
    # Evidence and mutable receipts.
    BoundaryRule("evidence/", EVIDENCE, owner="runtime", reason="mutable evidence tree"),
    BoundaryRule("test-evidence/", EVIDENCE, owner="runtime", reason="mutable evidence tree"),
    BoundaryRule("extension/evidence/", EVIDENCE, owner="extension", reason="mutable evidence tree"),
    BoundaryRule("registry/operational_gap_ledger.deltas", RUNTIME_STATE, owner="runtime/operational_gap_ledger.py", reason="PX-owned regenerable ledger checkpoints"),
    BoundaryRule("registry/operational_gap_ledger.jsonl", RUNTIME_STATE, owner="runtime/operational_gap_ledger.py", reason="authoritative ledger tail"),
    BoundaryRule("registry/operational_gap_ledger.head.json", RUNTIME_STATE, owner="runtime/operational_gap_ledger.py", reason="derived checkpoint head"),
    BoundaryRule("registry/operational_gap_ledger.snapshot.json", RUNTIME_STATE, owner="runtime/operational_gap_ledger.py", reason="derived projection snapshot"),
    BoundaryRule("registry/.operational-gap-ledger.lock", RUNTIME_STATE, exact=True, owner="runtime/operational_gap_ledger.py", reason="writer lease created by the actual ledger owner"),
    BoundaryRule("extension/.engineering-bootstrap/resource-lifecycle", RUNTIME_STATE, owner="runtime/resource_lifecycle.py", reason="declared extension subproject resource custody"),
    BoundaryRule("registry/operational_gap_ledger.reclaim", RUNTIME_STATE, owner="runtime/operational_gap_ledger.py", reason="governed reclaim set and receipt"),
    BoundaryRule("registry/engine_identity.json", RUNTIME_STATE, owner="runtime/engine_identity.py", reason="derived identity output"),
    BoundaryRule("registry/current_evidence_index.json", RUNTIME_STATE, owner="runtime", reason="derived evidence index"),
    # Source freeze artifacts are DERIVED identity outputs, never authored source.
    # Without these rules a freeze would classify its own receipt and archive as
    # authored and swallow itself into the next freeze.
    BoundaryRule("registry/source_freeze.json", RUNTIME_STATE, owner="runtime/source_freeze.py", reason="derived freeze receipt"),
    BoundaryRule("registry/source-freeze", RUNTIME_STATE, owner="runtime/source_freeze.py", reason="retained freeze archive"),
    # Vendored dependency trees.
    BoundaryRule("node_modules", VENDORED, exact=True, owner="npm", reason="npm dependency tree"),
    BoundaryRule("__pycache__", VENDORED, exact=True, owner="python", reason="python bytecode cache"),
    BoundaryRule(".ruff_cache", RUNTIME_STATE, owner="ruff", reason="tool cache"),
    BoundaryRule(".pytest_cache", RUNTIME_STATE, owner="pytest", reason="tool cache"),
    BoundaryRule(".mypy_cache", VENDORED, owner="mypy", reason="type-checker cache"),
    BoundaryRule("dist", RUNTIME_STATE, owner="build", reason="packaged output"),
    BoundaryRule("build", RUNTIME_STATE, owner="build", reason="build output"),
    # Nested build/package output under any tree (e.g. extension/build,
    # extension/dist). These are generated build artifacts, never authored source,
    # so a generated bundle can never become canonical design authority.
    BoundaryRule("extension/build/", RUNTIME_STATE, owner="extension/build", reason="extension build output"),
    BoundaryRule("extension/dist/", RUNTIME_STATE, owner="extension/dist", reason="extension packaged output"),
    BoundaryRule("preserved-extension-installations", RUNTIME_STATE, exact=True, owner="extension", reason="preserved install output"),
    BoundaryRule("preserved-skills", RUNTIME_STATE, exact=True, owner="runtime", reason="preserved skill output"),
    BoundaryRule(".engineering-bootstrap/receipts", EVIDENCE, owner="runtime", reason="retained cleanup receipts"),
    BoundaryRule(".engineering-bootstrap/test-evidence", EVIDENCE, owner="runtime", reason="retained test evidence"),
    BoundaryRule(".engineering-bootstrap/registers", EVIDENCE, owner="runtime", reason="census and register artifacts"),
    # --- External environment and derived custody -----------------------
    # These mirror runtime/repository_scope.py's EXTERNAL_ENVIRONMENT_ROOTS,
    # EXTERNAL_ENVIRONMENT_PARTS, CANONICAL_WORKSPACE_CUSTODY_ROOTS,
    # DERIVED_CUSTODY_ROOTS and LOCAL_TEST_EVIDENCE_ROOTS. They exist so that a
    # bare classify_path() call on a toolchain, quarantine, venv or workspace
    # custody path returns a custody classification instead of silently falling
    # through to AUTHORED. Without them a path such as .git/config,
    # .venv/lib/.../x.py or Python/python.exe classified as authored, which is
    # the conservative-looking but wrong answer: it would let an external binary
    # into an authored digest and therefore into source identity.
    BoundaryRule(".git", VENDORED, owner="git", reason="version control metadata"),
    BoundaryRule("Python", VENDORED, owner="host", reason="host toolchain runtime"),
    BoundaryRule("PortableGit", VENDORED, owner="host", reason="host toolchain runtime"),
    BoundaryRule(".vscode-test", VENDORED, owner="vscode", reason="downloaded test host"),
    BoundaryRule(".venv", VENDORED, owner="python", reason="virtual environment"),
    BoundaryRule("projects", RUNTIME_STATE, owner="runtime", reason="canonical workspace custody"),
    BoundaryRule("projects_tracking", RUNTIME_STATE, owner="runtime", reason="canonical workspace custody"),
    BoundaryRule("repo_quarantine", RUNTIME_STATE, owner="runtime", reason="canonical workspace custody"),
    BoundaryRule("shared_capabilities", RUNTIME_STATE, owner="runtime", reason="canonical workspace custody"),
    BoundaryRule("coordination", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("diagnostics", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("environment", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("focused-temp", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("project-map", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("project-map-history", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("project-map-history-archives", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("project-map-lock-history", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("runtime-core", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("quarantine", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("operation-bus", RUNTIME_STATE, owner="runtime", reason="volatile operation bus"),
    BoundaryRule("resource-lifecycle", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule("studios", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".lock-recovery-receipts", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".pacify-x", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".quarantine", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".audit-visible", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/architecture-repair-wal", RUNTIME_STATE, owner="runtime", reason="governed repair wal"),
    # Multi-segment derived custody paths. These are declared as full prefixes
    # because repository_scope matches them by segment position
    # (parts[:2] under .engineering-bootstrap or parts[:2] under .px), which a
    # single-component rule cannot express.
    BoundaryRule(".px/preserved-skills", RUNTIME_STATE, owner="runtime", reason="preserved skill output"),
    BoundaryRule(".px/global-skill-isolation", RUNTIME_STATE, owner="runtime", reason="skill isolation tree"),
    BoundaryRule(".px/preserved-extension-installations", RUNTIME_STATE, owner="runtime", reason="preserved install output"),
    BoundaryRule(".engineering-bootstrap/project-map", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/diagnostics", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/environment", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/coordination", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/focused-temp", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/quarantine", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/runtime-core", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/operation-bus", RUNTIME_STATE, owner="runtime", reason="volatile operation bus"),
    BoundaryRule(".engineering-bootstrap/resource-lifecycle", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/studios", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/project-map-history", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    BoundaryRule(".engineering-bootstrap/project-map-history-archives", RUNTIME_STATE, owner="runtime", reason="retained project map archives"),
    BoundaryRule(".engineering-bootstrap/project-map-lock-history", RUNTIME_STATE, owner="runtime", reason="derived custody tree"),
    # Canonical control-directory custody trees that the legacy rule set did not
    # cover. Each is PX-owned runtime state or retained evidence, never authored
    # source, so an explicit rule prevents a control path slipping into the
    # authored denominator.
    BoundaryRule(".engineering-bootstrap/test-evidence", EVIDENCE, owner="runtime", reason="mutable test evidence tree"),
    BoundaryRule(".engineering-bootstrap/receipts", EVIDENCE, owner="runtime", reason="retained receipts"),
    BoundaryRule(".engineering-bootstrap/registers", EVIDENCE, owner="runtime", reason="census and register artifacts"),
    BoundaryRule(".engineering-bootstrap/owned-processes", RUNTIME_STATE, owner="runtime/resource_lifecycle.py", reason="owned process custody"),
    BoundaryRule(".engineering-bootstrap/model-client-gateway", RUNTIME_STATE, owner="runtime/vscode_model_bridge.py", reason="model gateway state"),
    BoundaryRule(".engineering-bootstrap/extension-evidence", EVIDENCE, owner="extension", reason="mutable evidence tree"),
    BoundaryRule(".engineering-bootstrap/processing-order/architecture-repair-wal", RUNTIME_STATE, owner="runtime", reason="governed repair wal"),
    BoundaryRule(".px/mcp-runtime-probe.json", RUNTIME_STATE, owner="runtime", reason="mutable runtime projection"),
)

# Registered generated artifacts participate in classification too.
_GENERATED_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    (artifact.path, artifact.classification)
    for artifact in GENERATED_ARTIFACTS
    if artifact.classification in {GENERATED, PACKAGING_GENERATED, VENDORED}
)


def agent_experience_directories(root: Path) -> frozenset[str]:
    """Resolve bounded current registered body parents; malformed input excludes nothing."""
    from .json_io import load_json_object
    registry = root / "registry/agency_agent_registry.json"
    try:
        if registry.is_symlink():
            return frozenset()
        value = load_json_object(registry, max_bytes=2 * 1024 * 1024)
        rows = value.get("agents")
        if (value.get("provider_id") != "agency-agents" or type(rows) is not list
                or len(rows) > 10000 or type(value.get("agent_count")) is not int
                or value["agent_count"] != len(rows)):
            return frozenset()
        result = set()
        ids = set()
        for row in rows:
            if type(row) is not dict:
                return frozenset()
            identifier, relative = row.get("agent_id"), row.get("path")
            if (type(identifier) is not str or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,191}", identifier) is None
                    or identifier in ids or type(relative) is not str or len(relative) > 512):
                return frozenset()
            ids.add(identifier)
            relative = relative.replace("\\", "/")
            parts = relative.split("/")
            if (not relative.startswith("providers/agency_agents/agents/")
                    or len(parts) > 16 or any(p in {"", ".", ".."} or ":" in p for p in parts)
                    or not relative.endswith(".md")):
                return frozenset()
            body = root / relative
            if any((root.joinpath(*parts[:n])).is_symlink()
                   or _is_junction(root.joinpath(*parts[:n]))
                   for n in range(1, len(parts) + 1)):
                return frozenset()
            if not body.is_file() or not body.resolve().is_relative_to(root.resolve()):
                return frozenset()
            result.add(body.parent.relative_to(root).as_posix() + "/memory")
            result.add(body.parent.relative_to(root).as_posix() + "/memory/" + identifier)
        return frozenset(result)
    except (OSError, ValueError, TypeError, KeyError):
        return frozenset()


def is_operational_experience_path(relative: str, *, agent_directories: frozenset[str] = frozenset()) -> bool:
    """Exact skill/workflow writer outputs; unknown memory remains source.

    Agent roots require the current registry-derived owner set. No experience
    bytes are removed, and classification does not establish per-agent isolation.
    """
    owned = re.fullmatch(
        r"(?:\.px/skills|orchestration/workflows)/[a-z0-9][a-z0-9._-]{0,95}"
        r"/memory/(?:usage\.jsonl|stats\.json|\.tie\.lock|\.stats\.json\.[0-9a-f]{32}\.prepared)",
        relative,
    ) is not None
    parent, _, name = relative.rpartition("/")
    return owned or (parent in agent_directories and re.fullmatch(
        r"usage\.jsonl|stats\.json|\.tie\.lock|\.stats\.json\.[0-9a-f]{32}\.prepared", name) is not None)


def classify_path(relative: str, *, agent_directories: frozenset[str] = frozenset()) -> dict[str, str]:
    """Classify one repository-relative path. Deterministic and pure."""
    path = relative.replace("\\", "/")
    # Strip only a leading "./" prefix. Using str.lstrip("./") here would strip
    # the CHARACTER SET and silently turn ".engineering-bootstrap/..." into
    # "agentic-engineering-os-px/...", defeating every dotted-path rule.
    while path.startswith("./"):
        path = path[2:]
    path = path.lstrip("/")
    # A directory reference may carry a trailing slash; normalize it so a
    # directory path and its contents classify identically.
    while path.endswith("/"):
        path = path[:-1]
    path = _normalize_control_dir(path)
    # These are exact mutable pointers written by the native stage owners.
    # Policies, neighboring files and unrecognized campaign paths remain source.
    lifecycle_owner = {
        '.engineering-bootstrap/processing-order/repair-campaign.json': 'runtime/test_profiles.py',
        '.engineering-bootstrap/processing-order/release-identity.json': 'runtime/release_campaign.py',
    }.get(path)
    if re.fullmatch(r'\.engineering-bootstrap/processing-order/current-campaigns/[a-f0-9]{64}/release-identity\.json', path):
        lifecycle_owner = 'runtime/release_campaign.py'
    if lifecycle_owner is not None:
        return {'classification': RUNTIME_STATE, 'owner': lifecycle_owner,
                'reason': 'exact native mutable campaign lifecycle pointer'}
    if is_operational_experience_path(path, agent_directories=agent_directories):
        return {"classification": RUNTIME_STATE, "owner": "runtime/usage_memory.py",
                "reason": "actual append-only operational experience or derived rollup"}
    components = path.split("/")
    if len(components) >= 2 and components[0] in {".engineering-bootstrap", ".agentic_engineering_os_px"} and components[1] == "tmp":
        return {"classification": RUNTIME_STATE, "owner": "runtime/resource_lifecycle.py",
                "reason": "current or retained legacy operational scratch; not product source"}
    top = components[0]
    normalized_top = top.casefold()
    # Ephemeral and host-toolchain roots that cannot be expressed as a fixed
    # prefix list because the name varies at runtime. These mirror
    # repository_scope.is_external_environment_relative, which excludes
    # ".tmp*", "tmp_*", ".vscodecounter*" and ".venv*" by prefix. Without them a
    # scratch tree such as tmp_scratch/ or .tmp-work/ fell through to AUTHORED,
    # which would let transient scratch bytes into an authored digest.
    if (
        normalized_top.startswith(".tmp")
        or normalized_top.startswith("tmp_")
        or normalized_top.startswith(".vscodecounter")
    ):
        return {
            "classification": RUNTIME_STATE,
            "owner": "runtime",
            "reason": f"ephemeral custody root {top}",
        }
    # A virtual environment is vendored dependency content, not runtime state.
    if normalized_top.startswith(".venv"):
        return {"classification": VENDORED, "owner": "python", "reason": f"virtual environment {top}"}
    # Vendored caches keyed on any path segment, matching engine_identity's
    # directory-walk semantics rather than only repository-root occurrences.
    # .pytest_cache/.ruff_cache are tool caches (RUNTIME_STATE), not dependencies,
    # and are declared as prefix rules below; only true dependency caches are
    # vendored here. Every component is checked (not just the parent segments) so
    # a directory reference such as ``extension/node_modules`` classifies like its
    # contents.
    for component in components:
        if component in {"node_modules", "__pycache__", ".mypy_cache"}:
            return {"classification": VENDORED, "owner": "vendored", "reason": f"vendored segment {component}"}
    # Tool caches are RUNTIME_STATE at any depth (a nested ``extension/.pytest_cache``
    # is the same non-authored tool state as a repository-root one). They must be
    # matched as segments, not only as leading prefixes, or a cache nested under a
    # source tree silently falls through to AUTHORED.
    for component in components:
        if component in {".pytest_cache", ".ruff_cache"}:
            return {"classification": RUNTIME_STATE, "owner": "tool-cache", "reason": f"tool cache segment {component}"}
    # A nested VS Code test installation (``extension/.vscode-test``) is the same
    # vendored toolchain as a repository-root one.
    for component in components:
        if component == ".vscode-test":
            return {"classification": VENDORED, "owner": "vscode-test", "reason": "vendored VS Code test installation"}
    # A nested Python virtual environment (``extension/.venv-build``) is the same
    # vendored dependency installation regardless of where it lives.
    for component in components:
        if component.startswith(".venv") or component in {"venv", "env"}:
            return {"classification": VENDORED, "owner": "python-venv", "reason": f"vendored virtual environment segment {component}"}
    # Lock/recovery custody directories (nested or root) hold ledger writer state,
    # never authored source.
    for component in components:
        if component in {".lock-recovery-receipts", ".audit-visible"}:
            return {"classification": RUNTIME_STATE, "owner": "runtime", "reason": f"ledger lock/recovery custody segment {component}"}
    for rule in BOUNDARY_RULES:
        if rule.exact:
            if path == rule.prefix:
                return {"classification": rule.classification, "owner": rule.owner, "reason": rule.reason}
        elif path == rule.prefix.rstrip("/") or path.startswith(rule.prefix.rstrip("/") + "/"):
            return {"classification": rule.classification, "owner": rule.owner, "reason": rule.reason}
    for prefix, classification in _GENERATED_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/"):
            return {"classification": classification, "owner": "generated", "reason": f"registered generated artifact {prefix}"}
    return {"classification": AUTHORED, "owner": "authored", "reason": "default authored source"}


# --- validation ------------------------------------------------------------


class SourceBoundaryError(ValueError):
    """Raised when the declared source boundary is invalid."""


def validate_artifacts(root: Path) -> dict[str, Any]:
    """Verify every generated artifact names an existing, attributable generator.

    This is the guard against "it seems generated" classification. A generated
    artifact without a resolvable generator on disk fails closed.
    """
    root = Path(root).resolve(strict=True)
    problems: list[str] = []
    attributed = 0
    for artifact in GENERATED_ARTIFACTS:
        if not artifact.generator.strip():
            problems.append(f"{artifact.path}: no generator named")
            continue
        generator_path = root / artifact.generator_path
        if not generator_path.is_file():
            problems.append(
                f"{artifact.path}: generator_path {artifact.generator_path} does not exist"
            )
            continue
        if artifact.generator_owner.strip():
            owner = artifact.generator_owner
            if "/" in owner and not (root / owner).exists():
                problems.append(
                    f"{artifact.path}: generator_owner {owner} does not exist"
                )
                continue
        if artifact.classification not in CLASSIFICATIONS:
            problems.append(f"{artifact.path}: invalid classification")
            continue
        if artifact.unbuilt_presence not in {"required", "optional", "absent_by_definition"}:
            problems.append(f"{artifact.path}: invalid unbuilt_presence")
            continue
        attributed += 1
    return {
        "valid": not problems,
        "problems": problems,
        "artifact_count": len(GENERATED_ARTIFACTS),
        "attributed": attributed,
    }


def assert_generated_never_canonical_authority(root: Path) -> dict[str, Any]:
    """Enforce: no generated artifact is the sole canonical authority.

    Concrete check for the architecture atlas. The atlas is generated FROM
    repository source, so engine identity must not depend on it. This asserts
    the *declaration* (engine_identity excludes the atlas) without requiring a
    mutation probe, so it is safe to run anywhere.
    """
    root = Path(root).resolve(strict=True)
    module = (root / "runtime" / "engine_identity.py").read_text(encoding="utf-8")
    problems: list[str] = []
    for artifact in GENERATED_ARTIFACTS:
        if artifact.path in {"pyproject.toml#/tool.setuptools.data-files"}:
            continue
        prefix = artifact.path.split("#", 1)[0].rstrip("/")
        # The path must appear in engine_identity's exclusion declarations.
        bare = prefix.rsplit("/", 1)[-1]
        if prefix not in module and bare not in module:
            problems.append(
                f"{prefix} is generated from repository source but is not excluded "
                "by runtime/engine_identity.py, so it may feed back into identity"
            )
    return {"valid": not problems, "problems": problems}


def census(root: Path) -> dict[str, Any]:
    """Classify the whole tree and report authored versus everything else.

    Reports physical totals AND governed authored totals separately, so the two
    can no longer be conflated.
    """
    root = Path(root).resolve(strict=True)
    physical_files = 0
    physical_bytes = 0
    per_class: dict[str, dict[str, int]] = {}
    authored_files: list[str] = []
    agent_directories = agent_experience_directories(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        verdict = classify_path(relative, agent_directories=agent_directories)
        classification = verdict["classification"]
        bucket = per_class.setdefault(
            classification, {"files": 0, "bytes": 0}
        )
        bucket["files"] += 1
        bucket["bytes"] += size
        physical_files += 1
        physical_bytes += size
        if classification == AUTHORED:
            authored_files.append(relative)
    authored_bytes = per_class.get(AUTHORED, {}).get("bytes", 0)
    return {
        "schema_version": "px.source-census/1.0",
        "physical": {
            "files": physical_files,
            "bytes": physical_bytes,
        },
        "governed_authored": {
            "files": len(authored_files),
            "bytes": authored_bytes,
        },
        "non_authored": {
            "files": physical_files - len(authored_files),
            "bytes": physical_bytes - authored_bytes,
        },
        "by_classification": {
            key: per_class[key] for key in sorted(per_class)
        },
    }


def authored_paths(root: Path) -> list[str]:
    """Sorted repository-relative authored paths. Deterministic."""
    root = Path(root).resolve(strict=True)
    values = []
    agent_directories = agent_experience_directories(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if classify_path(relative, agent_directories=agent_directories)["classification"] == AUTHORED:
            values.append(relative)
    return values


def unbuilt_profile(root: Path) -> dict[str, Any]:
    """Machine-testable answer to what an unbuilt checkout contains.

    ``absent_by_definition`` artifacts are excluded from an unbuilt checkout;
    ``required`` artifacts must be present; ``optional`` ones may be present
    only as a pre-generated convenience.
    """
    root = Path(root).resolve(strict=True)
    required: list[str] = []
    optional: list[str] = []
    absent: list[str] = []
    for artifact in GENERATED_ARTIFACTS:
        exists = (root / artifact.path.split("#", 1)[0]).exists()
        record = f"{artifact.path} (present={exists})"
        if artifact.unbuilt_presence == "required":
            required.append(record)
        elif artifact.unbuilt_presence == "absent_by_definition":
            absent.append(record)
        else:
            optional.append(record)
    return {
        "schema_version": "px.unbuilt-profile/1.0",
        "required_in_unbuilt": sorted(required),
        "optional_in_unbuilt": sorted(optional),
        "absent_by_definition_in_unbuilt": sorted(absent),
    }


def write_boundary(root: Path) -> Path:
    """Publish the boundary to registry/source_boundary.json, digest-bound."""
    root = Path(root).resolve(strict=True)
    validation = validate_artifacts(root)
    authority = assert_generated_never_canonical_authority(root)
    if not validation["valid"]:
        raise SourceBoundaryError(
            "generated artifacts lack generator attribution: " + "; ".join(validation["problems"])
        )
    if not authority["valid"]:
        raise SourceBoundaryError(
            "generated artifact may be a canonical authority: " + "; ".join(authority["problems"])
        )
    body: dict[str, Any] = {
        "schema_version": BOUNDARY_SCHEMA,
        "classifications": list(CLASSIFICATIONS),
        "generated_artifacts": [artifact.to_json() for artifact in GENERATED_ARTIFACTS],
        "rules": [
            {
                "prefix": rule.prefix,
                "classification": rule.classification,
                "exact": rule.exact,
                "owner": rule.owner,
                "reason": rule.reason,
            }
            for rule in BOUNDARY_RULES
        ],
        "unbuilt_profile": unbuilt_profile(root),
        "validation": validation,
        "canonical_authority_check": authority,
    }
    body["boundary_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    target = root / BOUNDARY_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def read_boundary(root: Path) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    target = root / BOUNDARY_RELATIVE
    if not target.is_file():
        raise SourceBoundaryError("source boundary has not been published")
    return json.loads(target.read_text(encoding="utf-8"))


#: Conformance corpus for PX-GAP-0009. Each entry is a repository-relative path
#: that the two historical boundary mechanisms disagreed on, or that must be
#: classified consistently. ``expect`` is the canonical classification.
CONFORMANCE_CORPUS: tuple[tuple[str, str], ...] = (
    ("runtime/source_boundary.py", AUTHORED),
    ("runtime/repository_scope.py", AUTHORED),
    ("registry/provider_adapters.json", AUTHORED),
    ("extension/src/extension.js", AUTHORED),
    (".mypy_cache/3.12/x.json", VENDORED),
    ("sub/.mypy_cache/x.json", VENDORED),
    (".vscode-test/vscode/out.js", VENDORED),
    ("node_modules/left-pad/index.js", VENDORED),
    ("extension/node_modules/left-pad/index.js", VENDORED),
    ("__pycache__/mod.cpython-312.pyc", VENDORED),
    (".pytest_cache/v/cache/lastfailed", RUNTIME_STATE),
    (".ruff_cache/0.1/x", RUNTIME_STATE),
    (".venv/lib/python3.12/site.py", VENDORED),
    (".venv-custom/lib/site.py", VENDORED),
    ("Python/python.exe", VENDORED),
    ("PortableGit/bin/git.exe", VENDORED),
    (".git/config", VENDORED),
    ("evidence/receipt.json", EVIDENCE),
    (".engineering-bootstrap/test-evidence/x.json", EVIDENCE),
    (".engineering-bootstrap/studios/x.json", RUNTIME_STATE),
    (".agentic_engineering_os_px/runtime-core/semantic/entity-registry.json", RUNTIME_STATE),
    (".agentic_engineering_os_px/processing-order/architecture-repair-wal/x.json", RUNTIME_STATE),
    (".agentic_engineering_os_px/processing-order/repair-campaign.json", RUNTIME_STATE),
    (".agentic_engineering_os_px/processing-order/release-identity.json", RUNTIME_STATE),
    (".agentic_engineering_os_px/processing-order/current-campaigns/" + "a" * 64 + "/release-identity.json", RUNTIME_STATE),
    (".agentic_engineering_os_px/processing-order/current-campaigns/" + "a" * 64 + "/policy.json", AUTHORED),
    ("registry/operational_gap_ledger.jsonl", RUNTIME_STATE),
    (".px/mcp-runtime-probe.json", RUNTIME_STATE),
    ("projects/demo/src/app.py", RUNTIME_STATE),
    ("shared_capabilities/x.py", RUNTIME_STATE),
    ("docs/architecture/ATLAS_OFFLINE.html", GENERATED),
    ("extension/server/index.js", PACKAGING_GENERATED),
    # Nested build/package output is generated build state, never authored source.
    ("extension/build/generated.py", RUNTIME_STATE),
    ("extension/dist/bundle.js", RUNTIME_STATE),
    ("extension/node_modules/", VENDORED),
    (".px/skills/demo/memory/usage.jsonl", RUNTIME_STATE),
    ("tmp_scratch/x.txt", RUNTIME_STATE),
    (".tmp-work/x.txt", RUNTIME_STATE),
)


def conformance_report() -> dict[str, Any]:
    """Prove the canonical classifier agrees with the declared corpus.

    Also cross-checks ``runtime.repository_scope.is_external_environment_relative``
    (which now delegates here) so the two mechanisms cannot silently diverge again.
    """
    mismatches: list[dict[str, str]] = []
    for path, expected in CONFORMANCE_CORPUS:
        actual = classify_path(path)["classification"]
        if actual != expected:
            mismatches.append({"path": path, "expected": expected, "actual": actual})
    # Delegation check: repository_scope must agree with this owner on every entry.
    delegation: list[dict[str, str]] = []
    try:
        from runtime.repository_scope import is_external_environment_relative
        for path, expected in CONFORMANCE_CORPUS:
            external = is_external_environment_relative(path)
            should_be_external = expected != AUTHORED
            if external != should_be_external:
                delegation.append({"path": path, "expected_external": str(should_be_external),
                                   "repository_scope_external": str(external)})
    except ImportError as error:  # pragma: no cover - import cycle guard
        delegation.append({"path": "runtime.repository_scope", "expected_external": "True",
                           "repository_scope_external": f"import-error:{error}"})
    return {
        "schema_version": "px.source-boundary-conformance/1.0",
        "corpus_size": len(CONFORMANCE_CORPUS),
        "classification_mismatches": mismatches,
        "delegation_mismatches": delegation,
        "valid": not mismatches and not delegation,
    }
