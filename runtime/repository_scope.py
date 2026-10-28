"""Shared product-source boundary for repository-wide audits.

Canonical-owner note (PX-GAP-0009)
---------------------------------
This module and ``runtime/source_boundary.py`` historically both decided whether
a repository path is product-authored source, and they disagreed (``.mypy_cache``,
``.vscode-test`` and first-component-vs-full-path external detection).
``runtime/source_boundary.py`` is now the single canonical owner: it is
precedence-based, carries generator attribution and enforces the
"generated never canonical authority" rule. ``is_external_environment_relative``
and ``is_project_source`` here now DELEGATE to it, so the two mechanisms can no
longer disagree on any path. The public constant names are preserved for
existing consumers, but they are no longer the decision table.
"""

from __future__ import annotations

from pathlib import Path

# The canonical classifier lives in runtime/source_boundary.py. It is imported
# lazily inside is_external_environment_relative so this module can still be
# spec-loaded standalone (e.g. by docs/architecture/tools/build_atlas.py) even
# when the repository root is not on sys.path.

# Retained for import compatibility with existing consumers/tests. The actual
# classification decision is made by runtime/source_boundary.py; these sets are
# descriptive of the legacy owner and are not consulted for decisions.


EXTERNAL_ENVIRONMENT_ROOTS = frozenset(
    {"Python", "PortableGit", "node_modules", ".tmp", ".pacify-x", ".quarantine", ".audit-visible", ".audit-handoff"}
)
CANONICAL_WORKSPACE_CUSTODY_ROOTS = frozenset(
    {"projects", "projects_tracking", "repo_quarantine", "shared_capabilities"}
)
EXTERNAL_ENVIRONMENT_PARTS = frozenset(
    {
        "node_modules",
        ".vscode-test",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "evidence",
    }
)
DERIVED_CUSTODY_ROOTS = frozenset(
    {
        ".lock-recovery-receipts",
        "coordination",
        "diagnostics",
        "environment",
        "focused-temp",
        "project-map",
        "project-map-history",
        "project-map-history-archives",
        "project-map-lock-history",
        "runtime-core",
        "quarantine",
        "operation-bus",
        "resource-lifecycle",
        "studios",
    }
)
LOCAL_TEST_EVIDENCE_ROOTS = frozenset(
    {
        "adversarial-repair-gates",
        "github-reconciliation-gates",
    }
)
MUTABLE_RUNTIME_PROJECTIONS = frozenset(
    {
        ".px/mcp-runtime-probe.json",
        "registry/operational_gap_ledger.jsonl",
        "registry/operational_gap_ledger.snapshot.json",
    }
)


def _canonical_classify(text: str) -> str:
    """Classify via the canonical owner, importing it robustly.

    Prefers the installed package import; falls back to loading the sibling
    ``runtime/source_boundary.py`` by path so a standalone spec-load (which does
    not put the repo root on sys.path) still resolves the canonical owner.
    """
    try:
        from runtime.source_boundary import classify_path
    except ImportError:  # pragma: no cover - standalone spec-load path
        import importlib.util
        import sys

        candidate = Path(__file__).resolve().parent / "source_boundary.py"
        spec = importlib.util.spec_from_file_location("px_scope_source_boundary", candidate)
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        # Register before execution: on Python 3.12+ the dataclass machinery
        # resolves the defining module through sys.modules, so an unregistered
        # spec-loaded module fails at @dataclass with a NoneType error.
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(spec.name, None)
            raise
        classify_path = module.classify_path
    return classify_path(text)["classification"]


def is_external_environment_relative(relative: str | Path) -> bool:
    """Identify non-product source trees by delegating to the canonical owner.

    A path is "external" (not product-authored source) exactly when the canonical
    source boundary classifies it as anything other than AUTHORED. Delegation is
    what removes the historical disagreement: this function no longer applies its
    own rule table.
    """
    relative_path = Path(relative)
    text = relative_path.as_posix()
    if not text or text == ".":
        return False
    return _canonical_classify(text) != "authored"


def is_project_source(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return not is_external_environment_relative(relative)
