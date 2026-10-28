"""The PX-GAP-0009 boundary conformance corpus.

Two modules answer "is this product source?":
  runtime/repository_scope.py  -> is_external_environment_relative (custody)
  runtime/source_boundary.py   -> classify_path (authored/generated/...)

`source_boundary` is the declared canonical owner. `repository_scope` is the
older, coarser custody predicate. This corpus asserts that a bare
`classify_path()` call never calls an external, vendored, ephemeral, quarantine or
derived-custody path authored source.

Generated artifacts and retained evidence use the same canonical non-source
boundary in both modules. Explicit fixture retention does not make them authored.
"""

from __future__ import annotations

from pathlib import Path

import runtime.repository_scope as repository_scope
import runtime.source_boundary as source_boundary

ROOT = Path(__file__).resolve().parents[1]


def test_retained_and_current_scratch_cannot_enter_effect_inventory(tmp_path):
    from runtime.effect_surface import discover_effect_surfaces
    for namespace in (".engineering-bootstrap", ".agentic_engineering_os_px"):
        path = tmp_path / namespace / "tmp" / "broken_probe.py"
        path.parent.mkdir(parents=True)
        path.write_text('s"""corrupt historical probe"""', encoding="utf-8")
        relative = path.relative_to(tmp_path).as_posix()
        assert repository_scope.is_external_environment_relative(relative)
        assert source_boundary.classify_path(relative)["classification"] != source_boundary.AUTHORED
    owner = tmp_path / "runtime" / "actual.py"
    owner.parent.mkdir()
    owner.write_text("def run():\n    subprocess.run(['actual'], timeout=1)\n", encoding="utf-8")
    assert {row["path"] for row in discover_effect_surfaces(tmp_path)} == {"runtime/actual.py"}

# Paths that must never classify as authored source.
MUST_NOT_BE_AUTHORED = (
    # host toolchain and version control
    ".git/config",
    "Python/python.exe",
    "PortableGit/git.exe",
    ".venv/lib/python3.14/site-packages/x.py",
    ".vscode-test/vscode-linux-x64/bin/code",
    # vendored and generated output
    "node_modules/pkg/index.js",
    "build/output.bin",
    "dist/package.zip",
    "__pycache__/module.cpython-314.pyc",
    # evidence and derived custody
    "evidence/capability-mining-receipt.json",
    ".agentic_engineering_os_px/project-map/architecture-graph.json",
    ".agentic_engineering_os_px/diagnostics/report.json",
    ".agentic_engineering_os_px/runtime-core/state.json",
    # canonical workspace custody
    "projects/prj_x/memory/plan.md",
    "repo_quarantine/old/thing.py",
    "shared_capabilities/tool.py",
    # quarantine and audit trees
    ".quarantine/thing.py",
    ".audit-visible/x.py",
    ".pacify-x/state.json",
    ".lock-recovery-receipts/r.json",
    ".px/preserved-skills/s.py",
    ".px/global-skill-isolation/g.py",
    ".px/preserved-extension-installations/e.js",
    ".agentic_engineering_os_px/processing-order/architecture-repair-wal/w.json",
    # ephemeral scratch, matched by prefix
    "tmp_scratch/note.md",
    ".tmp-work/file.txt",
    ".vscodecounter-out/x.txt",
    ".venv311/lib/x.py",
    # mutable projections
    "registry/operational_gap_ledger.jsonl",
)

# Paths that must classify as authored source.
MUST_BE_AUTHORED = (
    "runtime/source_boundary.py",
    "runtime/repository_scope.py",
    "registry/plan_corpus.json",
    "tests/test_semantic_entity.py",
    "README.md",
    "extension/src/extension.js",
    "extension/server/source.mjs",
    "extension/package.json",
)

# Intended coarser-vs-canonical divergences: repository_scope says "source",
# source_boundary correctly says a custody classification. Recorded, not hidden.
INTENTIONAL_DIVERGENCES = (
    # Generated/evidence paths that source_boundary correctly refuses to call
    # authored. repository_scope's coarser custody predicate still treats the
    # atlas and the retained test-evidence receipts as product source, which is a
    # granularity difference, not a boundary conflict.
    "docs/architecture/graph_data.js",
    "docs/architecture/ATLAS_OFFLINE.html",
    ".agentic_engineering_os_px/test-evidence/groups/g1.json",
)


def test_external_and_derived_paths_are_never_authored() -> None:
    failures = [
        path
        for path in MUST_NOT_BE_AUTHORED
        if source_boundary.classify_path(path)["classification"]
        == source_boundary.AUTHORED
    ]
    assert not failures, "classified as authored but must not be: " + ", ".join(failures)


def test_product_source_paths_remain_authored() -> None:
    failures = [
        path
        for path in MUST_BE_AUTHORED
        if source_boundary.classify_path(path)["classification"]
        != source_boundary.AUTHORED
    ]
    assert not failures, "classified as non-authored but must be authored: " + ", ".join(failures)


def test_generated_and_evidence_paths_use_one_canonical_non_source_boundary() -> None:
    # Canonical delegation removes the old coarser custody split.
    for path in INTENTIONAL_DIVERGENCES:
        assert source_boundary.classify_path(path)["classification"] != source_boundary.AUTHORED
        assert repository_scope.is_external_environment_relative(path)


def test_custody_agreement_is_total_outside_the_recorded_exceptions() -> None:
    """The two owners must not silently diverge on anything unrecorded."""
    corpus = set(MUST_NOT_BE_AUTHORED) | set(MUST_BE_AUTHORED)
    unrecorded = []
    for path in corpus:
        scope_says_source = not repository_scope.is_external_environment_relative(path)
        boundary_says_source = (
            source_boundary.classify_path(path)["classification"]
            == source_boundary.AUTHORED
        )
        if scope_says_source != boundary_says_source:
            unrecorded.append(path)
    assert not unrecorded, (
        "boundary owners disagree on paths outside the recorded exception set: "
        + ", ".join(sorted(unrecorded))
    )


def test_declared_generated_artifacts_all_validate() -> None:
    result = source_boundary.validate_artifacts(ROOT)
    assert result["valid"], result
