"""Measure whether repository_scope and source_boundary actually disagree.

PX-GAP-0009 asserts two competing owners for the source boundary. This builds a
conformance corpus of real repository paths plus adversarial cases, runs both
modules over every path, and reports exactly where they disagree and in which
direction. Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.repository_scope as rs  # noqa: E402
import runtime.source_boundary as sb  # noqa: E402

# Real repository paths that exercise each boundary class, plus adversarial
# cases chosen because the two modules could plausibly disagree.
CONFORMANCE_CORPUS = (
    "runtime/source_boundary.py",
    "runtime/repository_scope.py",
    "runtime/module.py",
    "registry/plan_corpus.json",
    "tests/test_semantic_entity.py",
    "README.md",
    "extension/src/extension.js",
    "extension/server/index.js",
    "extension/server/source.mjs",
    "extension/package-lock.json",
    "extension/package.json",
    "docs/architecture/graph_data.js",
    "docs/architecture/reference/graph_baseline_architecture.json",
    "docs/architecture/ATLAS_OFFLINE.html",
    "node_modules/pkg/index.js",
    "node_modules/esbuild/lib/main.js",
    "__pycache__/module.cpython-314.pyc",
    "build/output.bin",
    "dist/package.zip",
    "evidence/capability-mining-receipt.json",
    "extension/evidence/installed-vsix-smoke.json",
    ".agentic_engineering_os_px/test-evidence/groups/g1.json",
    ".agentic_engineering_os_px/project-map/architecture-graph.json",
    ".agentic_engineering_os_px/diagnostics/report.json",
    ".agentic_engineering_os_px/runtime-core/state.json",
    "Python/python.exe",
    "PortableGit/git.exe",
    "projects/prj_x/memory/plan.md",
    "repo_quarantine/old/thing.py",
    "shared_capabilities/tool.py",
    ".git/config",
    "registry/operational_gap_ledger.jsonl",
    "registry/source-freeze.json",
    ".vscode-test/vscode-linux-x64/bin/code",
    ".pytest_cache/v/cache/nodeids",
    ".ruff_cache/a/b",
    ".venv/lib/python3.14/site-packages/x.py",
    "tmp_scratch/note.md",
    ".tmp-work/file.txt",
    ".pacify-x/state.json",
    ".quarantine/thing.py",
    ".audit-visible/x.py",
    ".lock-recovery-receipts/r.json",
    ".px/preserved-skills/s.py",
    ".px/global-skill-isolation/g.py",
    ".px/preserved-extension-installations/e.js",
    ".agentic_engineering_os_px/processing-order/architecture-repair-wal/w.json",
    ".agentic_engineering_os_px/test-evidence/adversarial-repair-gates/a.json",
)


def main() -> int:
    print(f"{'path':62s} {'scope':6s} {'boundary':20s} agreement")
    print("-" * 104)
    disagreements: list[tuple[str, bool, str]] = []
    for relative in CONFORMANCE_CORPUS:
        scope_says_source = not rs.is_external_environment_relative(relative)
        classified = sb.classify_path(relative)
        boundary = str(classified.get("classification"))
        # source_boundary says "product source" for authored only; vendored,
        # generated, evidence and runtime_state are all non-source.
        boundary_says_source = boundary == sb.AUTHORED
        agree = scope_says_source == boundary_says_source
        if not agree:
            disagreements.append((relative, scope_says_source, boundary))
        flag = "ok" if agree else "DIVERGES"
        print(
            f"{relative:62s} {str(scope_says_source):6s} {boundary:20s} {flag}"
        )

    print()
    print(f"corpus size: {len(CONFORMANCE_CORPUS)}")
    print(f"disagreements: {len(disagreements)}")
    for relative, scope_says_source, boundary in disagreements:
        direction = (
            "repository_scope calls it source, source_boundary does not"
            if scope_says_source
            else "repository_scope excludes it, source_boundary calls it authored"
        )
        print(f"  {relative} -> boundary={boundary}; {direction}")
    print()
    print(
        "module docstring self-declaration:\n"
        f"  repository_scope: {rs.__doc__}"
    )
    print(
        f"  source_boundary:  {sb.__doc__.splitlines()[0] if sb.__doc__ else None}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())