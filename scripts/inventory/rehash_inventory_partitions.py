"""Refresh map-level hashes after a bounded mechanical sanitization pass."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _confined(path: Path, label: str) -> Path:
    """Resolve a destination and refuse anything outside the repository.

    Unlike a report file, `--parts-root` names a *tree to walk*, so the repository root itself
    is a legitimate value. The destination check that refuses a root is applied to each
    summary file this producer rewrites, not to the walk origin.
    """
    from runtime.confined_output import ConfinementError

    root = Path(__file__).resolve().parents[2]
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
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
    import os

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def rehash(parts_root: Path) -> dict[str, object]:
    parts_root = _confined(parts_root, "parts_root")
    updated: list[dict[str, object]] = []
    for inventory in sorted(
        parts_root.rglob("inventory.jsonl"), key=lambda path: path.as_posix()
    ):
        summary = inventory.with_name("file_inventory_summary.json")
        if not summary.is_file():
            continue
        digest = hashlib.sha256(inventory.read_bytes()).hexdigest()
        payload = json.loads(summary.read_text(encoding="utf-8"))
        payload["inventory_sha256"] = digest
        _publish(_confined_file(summary), json.dumps(payload, indent=2) + "\n")
        markdown = inventory.with_name("file_inventory_summary.md")
        if markdown.is_file():
            lines = markdown.read_text(encoding="utf-8").splitlines()
            lines = [
                f"- Inventory SHA-256: `{digest}`"
                if line.startswith("- Inventory SHA-256:")
                else line
                for line in lines
            ]
            _publish(_confined_file(markdown), "\n".join(lines) + "\n")
        updated.append({"partition": inventory.parent.name, "inventory_sha256": digest})
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
    result = rehash(args.parts_root)
    if args.output:
        # Confined, atomic publication inside the repository root.
        from runtime.confined_output import publish_json

        publish_json(Path(__file__).resolve().parents[2], args.output, result)
    print(json.dumps({"updated_count": result["updated_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
