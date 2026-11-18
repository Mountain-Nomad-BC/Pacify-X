"""Refresh map-level hashes after a bounded mechanical sanitization pass."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from runtime.secure_publish import atomic_write_bytes


def _confined(path: Path, label: str) -> Path:
    """Resolve a destination and refuse anything outside the repository.

    Unlike a report file, `--parts-root` names a *tree to walk*, so the repository root itself
    is a legitimate value. The destination check that refuses a root is applied to each
    summary file this producer rewrites, not to the walk origin.
    """
    from runtime.confined_output import ConfinementError
    from runtime.archive_io import reject_path_links

    root = Path(__file__).resolve().parents[2]
    candidate = Path(path)
    original = candidate if candidate.is_absolute() else root / candidate
    try:
        reject_path_links(original)
    except ValueError as error:
        raise ConfinementError(f"{label} must not contain links or junctions") from error
    resolved = original.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ConfinementError(f"{label} must stay inside the repository root: {resolved}") from error
    return resolved


def _confined_file(path: Path) -> Path:
    """A file destination must be strictly below the repository root."""
    from runtime.confined_output import confined_path

    return confined_path(Path(__file__).resolve().parents[2], path, label="partition summary")


def _publish(path: Path, text: str) -> None:
    """Atomic replacement so a failure never leaves a half-written summary."""
    atomic_write_bytes(path, text.encode("utf-8"))


def _inventory_sha256(path: Path) -> str:
    # Delegate to the canonical owner; this was a byte-identical copy of
    # runtime.hash_utils.file_sha256.
    from runtime.hash_utils import file_sha256

    return file_sha256(path)


def rehash(parts_root: Path, *, report_path: Path | None = None) -> dict[str, object]:
    parts_root = _confined(parts_root, "parts_root")
    if not parts_root.is_dir():
        raise ValueError(f"parts_root must be an existing directory: {parts_root}")
    report_path = _confined_file(report_path) if report_path is not None else None
    if report_path is not None:
        if report_path.exists() and not report_path.is_file():
            raise ValueError(f"report must name a regular file: {report_path}")
        for parent in report_path.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"report parent must be a directory: {parent}")
    updated: list[dict[str, object]] = []
    publications: list[tuple[Path, str]] = []
    for inventory in sorted(
        parts_root.rglob("inventory.jsonl"), key=lambda path: path.as_posix()
    ):
        # Validate original input components before reading any file content.
        inventory = _confined_file(inventory)
        summary = _confined_file(inventory.with_name("file_inventory_summary.json"))
        markdown = _confined_file(inventory.with_name("file_inventory_summary.md"))
        if report_path is not None and any(
            report_path == path.resolve() or (
                report_path.exists() and path.exists() and report_path.samefile(path)
            )
            for path in (inventory, summary, markdown)
        ):
            raise ValueError("report must be distinct from partition inputs and summaries")
        if not summary.is_file():
            continue
        digest = _inventory_sha256(inventory)
        payload = json.loads(summary.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"partition summary must be a JSON object: {summary}")
        payload["inventory_sha256"] = digest
        publications.append((_confined_file(summary), json.dumps(payload, indent=2) + "\n"))
        if markdown.is_file():
            lines = markdown.read_text(encoding="utf-8").splitlines()
            if not any(line.startswith("- Inventory SHA-256:") for line in lines):
                raise ValueError(f"partition markdown is missing its inventory digest marker: {markdown}")
            lines = [
                f"- Inventory SHA-256: `{digest}`"
                if line.startswith("- Inventory SHA-256:")
                else line
                for line in lines
            ]
            publications.append((_confined_file(markdown), "\n".join(lines) + "\n"))
        updated.append({"partition": inventory.parent.name, "inventory_sha256": digest})
    # Decode and confine the entire batch before the first replacement. Publication
    # remains atomic per file; an I/O failure during commit is not a batch rollback.
    for destination, text in publications:
        _publish(destination, text)
    return {
        "schema_version": "1.0",
        "updated_count": len(updated),
        "partitions": updated,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    # Refuse invalid report destinations before any partition is rewritten.
    output = _confined_file(args.output) if args.output is not None else None
    result = rehash(args.parts_root, report_path=output)
    if output is not None:
        # Confined, atomic publication inside the repository root.
        from runtime.confined_output import publish_json

        publish_json(Path(__file__).resolve().parents[2], output, result)
    print(json.dumps({"updated_count": result["updated_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
