"""Verify the two-root evidence custody rules for Recovery WAVE-02.

Builds a synthetic tree and asserts the export boundary, then confirms the real
tree's current custody state. Read-only with respect to the repository: nothing
is written into the project and no evidence artifact is created.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.clean_source_export import included_files  # noqa: E402


def _workspace(prefix: str):
    from runtime.resource_lifecycle import ResourceManager

    manager = ResourceManager(ROOT / ".agentic_engineering_os_px/resource-lifecycle/ledger.json")
    record = manager.create_workspace(Path(tempfile.gettempdir()), project_id="pacify-x",
        run_id=prefix + uuid4().hex, lane_id="current-diagnostic",
        creator=__name__, prefix=prefix)
    return manager, record, Path(record.path)


def _close_workspace(manager, record):
    receipt = manager.reclaim_ephemeral_path(record.resource_id, reason="current_diagnostic_complete")
    if receipt.errors or receipt.resources_reclaimed != 1:
        raise RuntimeError("diagnostic workspace closure failed: " + repr(receipt.errors))


def _make(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def build_synthetic_tree(base: Path) -> Path:
    """Construct a tree covering every custody branch the export decides."""
    root = base / "framework"
    # must be retained: governed source-tree receipt subtree
    _make(
        root / ".agentic_engineering_os_px/test-evidence/groups/g1.json",
        '{"group":"g1"}',
    )
    _make(
        root / ".agentic_engineering_os_px/test-evidence/profiles/p1.json",
        '{"profile":"p1"}',
    )
    # must be excluded: .agentic_engineering_os_px non-receipt content
    _make(root / ".agentic_engineering_os_px/scratch-notes.md", "notes")
    # must be retained: declared distribution evidence root
    _make(
        root / "extension/evidence/installed-vsix-smoke.json",
        '{"stage":"installed-certification"}',
    )
    _make(root / "extension/evidence/nested/sub-receipt.json", '{"sub":true}')
    # must be retained: declared packaged product-artifact receipts
    _make(root / "evidence/capability-mining-receipt.json", '{"packaged":true}')
    _make(root / "evidence/process-audit-intake-receipt.json", '{"packaged":true}')
    # must be excluded: the rest of the top-level evidence root is NOT packaged
    _make(root / "evidence/bundles/archive/manifest.json", '{"bundle":true}')
    _make(root / "evidence/release/historical.json", '{"historical":true}')
    _make(root / "evidence/not-a-declared-receipt.json", '{"stray":true}')
    # must be excluded: unrelated generated/dependency/history trees
    _make(root / "node_modules/pkg/index.js", "module.exports={}")
    _make(root / "build/output.bin", "binary")
    _make(root / "dist/package.zip", "zip")
    _make(root / ".pytest_cache/v/cache/nodeids", "[]")
    _make(root / "__pycache__/mod.cpython-314.pyc", "compiled")
    # must be retained: ordinary authored source
    _make(root / "runtime/module.py", "VALUE = 1\n")
    _make(root / "README.md", "# readme\n")
    _make(root / "pyproject.toml", '[tool.setuptools.data-files]\n"share/agentic-engineering-os-px/evidence" = ["evidence/capability-mining-receipt.json", "evidence/process-audit-intake-receipt.json"]\n')
    return root


EXPECTED_RETAINED = {
    ".agentic_engineering_os_px/test-evidence/groups/g1.json",
    ".agentic_engineering_os_px/test-evidence/profiles/p1.json",
    "extension/evidence/installed-vsix-smoke.json",
    "extension/evidence/nested/sub-receipt.json",
    "evidence/capability-mining-receipt.json",
    "evidence/process-audit-intake-receipt.json",
    "runtime/module.py",
    "README.md",
    "pyproject.toml",
}

EXPECTED_EXCLUDED = {
    ".agentic_engineering_os_px/scratch-notes.md",
    "evidence/bundles/archive/manifest.json",
    "evidence/release/historical.json",
    "evidence/not-a-declared-receipt.json",
    "node_modules/pkg/index.js",
    "build/output.bin",
    "dist/package.zip",
    ".pytest_cache/v/cache/nodeids",
    "__pycache__/mod.cpython-314.pyc",
}


def check_synthetic() -> list[str]:
    failures: list[str] = []
    manager, record, base = _workspace("px-custody-")
    try:
        root = build_synthetic_tree(base)
        included = {
            path.relative_to(root).as_posix() for path in included_files(root)
        }
        for relative in sorted(EXPECTED_RETAINED):
            if relative not in included:
                failures.append(f"should be RETAINED but was excluded: {relative}")
        for relative in sorted(EXPECTED_EXCLUDED):
            if relative in included:
                failures.append(f"should be EXCLUDED but was retained: {relative}")
        print(f"synthetic tree: {len(included)} files included")
    finally:
        _close_workspace(manager, record)
    return failures


def check_real_tree() -> dict[str, object]:
    print()
    print("real tree custody:")
    status: dict[str, object] = {}
    # A historical index cannot establish fresh custody. Inspect current files.
    status["validation_basis"] = "current_implementation"

    source_root = ROOT / ".agentic_engineering_os_px/test-evidence"
    distribution_root = ROOT / "extension/evidence"
    status["source_root_present"] = source_root.is_dir()
    status["source_root_files"] = (
        sum(1 for item in source_root.rglob("*") if item.is_file())
        if source_root.is_dir()
        else 0
    )
    status["distribution_root_present"] = distribution_root.is_dir()

    included = {
        path.relative_to(ROOT).as_posix() for path in included_files(ROOT)
    }
    status["test_evidence_receipts_included"] = sum(
        1 for relative in included if "/test-evidence/" in f"/{relative}"
    )

    print(f"  source-tree receipt root present: {status['source_root_present']}")
    print(f"  source-tree receipt files: {status['source_root_files']}")
    print(f"  distribution root present: {status['distribution_root_present']}")
    print(f"  test-evidence receipts in export: {status['test_evidence_receipts_included']}")

    if not status["distribution_root_present"]:
        print(
            "  note: extension/evidence/ does not exist in this tree because installed-"
            "artifact certification has not been performed. The retention rule is still "
            "declared and is exercised by the synthetic check above."
        )
    return status


def check_packaged_declaration_alignment(root: Path) -> list[str]:
    """The export carve-out must mirror the pyproject packaged declaration."""
    failures: list[str] = []
    try:
        import tomllib

        project = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )
    except Exception as error:  # noqa: BLE001 - diagnostic probe
        return [f"pyproject.toml unreadable: {type(error).__name__}: {error}"]

    declared: set[str] = set()
    for group in (
        project.get("tool", {}).get("pacta", {}).get("package-data", {})
        or project.get("tool", {}).get("package-data", {})
    ).values():
        if isinstance(group, list):
            declared.update(str(item) for item in group)
    if not declared:
        # Fall back to scanning every packaging table for evidence/ members.
        def _walk(node: object) -> None:
            if isinstance(node, dict):
                for value in node.values():
                    _walk(value)
            elif isinstance(node, list):
                for value in node:
                    if isinstance(value, str) and value.startswith("evidence/"):
                        declared.add(value)

        _walk(project)

    import fnmatch
    included = {path.relative_to(root).as_posix() for path in included_files(root)}
    present = {path.relative_to(root).as_posix() for path in (root / "evidence").rglob("*") if path.is_file()}
    mirrored = {path for path in present if any(fnmatch.fnmatchcase(path, pattern) for pattern in declared)}
    missing_from_export = sorted(mirrored - included)
    extra_in_export = sorted({path for path in included if path.startswith("evidence/")} - mirrored)
    if missing_from_export:
        failures.append(
            "packaged in pyproject but not retained by the export carve-out: "
            + ", ".join(missing_from_export)
        )
    if extra_in_export:
        failures.append(
            "retained by the export carve-out but not declared packaged: "
            + ", ".join(extra_in_export)
        )
    if not failures:
        print(f"packaged-evidence declaration aligned: {len(mirrored)} members")
    return failures


def main() -> int:
    failures = check_synthetic()
    failures.extend(check_packaged_declaration_alignment(ROOT))
    status = check_real_tree()
    print()
    if failures:
        print("CUSTODY FAILURES:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("OK: all three governed evidence roots are retained by declared custody.")
    print("OK: undeclared evidence paths and every unrelated generated, dependency and history tree stay excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
