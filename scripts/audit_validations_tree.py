"""Create a deterministic, content-hashed inventory of an external validation tree.

The output files are created only after source enumeration, so the manifest does
not recursively inventory itself. Existing reports remain ordinary input files.
This is an evidence census, not a claim that each file must be imported.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    report = args.report.resolve(strict=True)
    if not report.is_relative_to(root) or not report.is_dir():
        parser.error("report must be an existing directory inside root")
    manifest = report / "validations-file-manifest-20260926.csv"
    summary_path = report / "validations-file-manifest-summary-20260926.json"
    for output in (manifest, summary_path):
        if output.exists():
            parser.error(f"refusing to overwrite existing report: {output}")

    paths: list[Path] = []
    directory_count = 0
    linked_paths: list[str] = []
    walk_errors: list[str] = []

    def on_error(error: OSError) -> None:
        walk_errors.append(str(error))

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=on_error):
        directory_count += 1
        dirs.sort()
        files.sort()
        for name in dirs:
            path = Path(directory) / name
            if path.is_symlink():
                linked_paths.append(path.relative_to(root).as_posix())
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                linked_paths.append(path.relative_to(root).as_posix())
            else:
                paths.append(path)
    paths.sort(key=lambda path: path.relative_to(root).as_posix().casefold())
    print(f"Enumerated {len(paths)} files and {directory_count} directories", flush=True)

    top_levels: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    total_bytes = 0
    with manifest.open("x", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("relative_path", "size_bytes", "sha256", "status"))
        for index, path in enumerate(paths, 1):
            relative = path.relative_to(root).as_posix()
            try:
                size = path.stat().st_size
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                writer.writerow((relative, size, digest.hexdigest(), "ok"))
                total_bytes += size
                top_levels[relative.split("/", 1)[0]] += 1
                extensions[path.suffix.lower() or "<none>"] += 1
            except OSError as error:
                writer.writerow((relative, "", "", "error"))
                errors.append({"path": relative, "error": str(error)})
            if index % 1000 == 0:
                print(f"Hashed {index}/{len(paths)}", flush=True)

    result = {
        "schema_version": "px.validations-file-manifest/1.0",
        "root": str(root),
        "manifest": str(manifest),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "source_files_enumerated": len(paths),
        "source_files_hashed": len(paths) - len(errors),
        "source_bytes_hashed": total_bytes,
        "directories_enumerated": directory_count,
        "top_levels": dict(sorted(top_levels.items())),
        "extensions": dict(sorted(extensions.items())),
        "symbolic_links_not_followed": linked_paths,
        "walk_errors": walk_errors,
        "hash_errors": errors,
        "self_reference_rule": "The two new output files were absent at enumeration and excluded; pre-existing reports were included.",
    }
    summary_path.open("x", encoding="utf-8").write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "source_files_enumerated", "source_files_hashed", "source_bytes_hashed",
        "directories_enumerated", "walk_errors", "hash_errors", "manifest_sha256",
    )}, indent=2), flush=True)
    return 0 if not walk_errors and not errors and not linked_paths else 1


if __name__ == "__main__":
    sys.exit(main())
