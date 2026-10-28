"""Convert the newly added exact-match boundary rules into prefix rules.

`exact=True` in runtime/source_boundary.py matches only the bare directory name,
so a rule declared for `.git` never classified `.git/config`. The external
environment and derived custody roots must classify their whole trees, so these
rules are declared as prefixes instead.

Only the rules added for PX-GAP-0009 conformance are touched; pre-existing
`exact=True` rules elsewhere in the table are left exactly as they are.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "runtime" / "source_boundary.py"

VENDORED_PREFIXES = (".git", "Python", "PortableGit", ".vscode-test", ".venv")

RUNTIME_STATE_PREFIXES = (
    "projects",
    "projects_tracking",
    "repo_quarantine",
    "shared_capabilities",
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
    ".lock-recovery-receipts",
    ".pacify-x",
    ".quarantine",
    ".audit-visible",
)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    converted = 0
    for name in VENDORED_PREFIXES:
        old = f'BoundaryRule("{name}", VENDORED, exact=True'
        if old in text:
            text = text.replace(old, f'BoundaryRule("{name}", VENDORED')
            converted += 1
    for name in RUNTIME_STATE_PREFIXES:
        old = f'BoundaryRule("{name}", RUNTIME_STATE, exact=True'
        if old in text:
            text = text.replace(old, f'BoundaryRule("{name}", RUNTIME_STATE')
            converted += 1
    TARGET.write_text(text, encoding="utf-8")
    print(f"converted {converted} exact-match rules to prefix rules")
    remaining = text.count("exact=True")
    print(f"pre-existing exact=True rules preserved: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())