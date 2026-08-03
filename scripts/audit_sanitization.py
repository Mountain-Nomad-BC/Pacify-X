"""Audit a tree for private identifiers and active ZIP archives without mutating it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


TERMS = ("r" + "ie", "re" + "my", "rh" + "eem")
PATTERN = re.compile(
    rb"(?i)(?:(?<![A-Za-z])(" + TERMS[0].encode() + rb")(?![A-Za-z])|(" + TERMS[1].encode()
    + rb"|" + TERMS[2].encode() + rb"))"
)
LEGACY_TERMS = ("integration" + "_" + "engine", "governed" + "_" + "retrieval")
LEGACY_PATTERN = re.compile(
    rb"(?i)(" + LEGACY_TERMS[0].encode() + rb"|" + LEGACY_TERMS[1].encode()
    + rb"(?!_system_with_deterministic_rails))"
)
EXCLUDED_DIRECTORIES = {".git"}


def audit(
    root: Path, *, ignored: tuple[Path, ...] = (), excluded_names: frozenset[str] = frozenset(),
) -> dict[str, object]:
    resolved = root.resolve()
    ignored_paths = {path.resolve() for path in ignored}
    identifier_hits: list[dict[str, object]] = []
    legacy_placeholder_hits: list[dict[str, object]] = []
    zip_paths: list[str] = []
    files_scanned = 0
    bytes_scanned = 0
    errors: list[str] = []
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if any(part in EXCLUDED_DIRECTORIES or part in excluded_names for part in path.relative_to(resolved).parts):
            continue
        if not path.is_file() or path.resolve() in ignored_paths:
            continue
        relative = path.relative_to(resolved).as_posix()
        files_scanned += 1
        if path.suffix.casefold() == ".zip":
            zip_paths.append(relative)
        path_match = PATTERN.search(relative.encode("utf-8", errors="replace"))
        if path_match:
            identifier_hits.append({"path": relative, "location": "path", "offset": path_match.start()})
        legacy_path_match = LEGACY_PATTERN.search(relative.encode("utf-8", errors="replace"))
        if legacy_path_match:
            legacy_placeholder_hits.append({"path": relative, "location": "path", "offset": legacy_path_match.start()})
        try:
            overlap = b""
            offset = 0
            with path.open("rb") as handle:
                chunk = handle.read(1024 * 1024)
                while chunk:
                    following = handle.read(1024 * 1024)
                    bytes_scanned += len(chunk)
                    buffer = overlap + chunk
                    safe_end = len(buffer) if not following else max(0, len(buffer) - 128)
                    buffer_start = offset - len(overlap)
                    for match in PATTERN.finditer(buffer):
                        absolute = buffer_start + match.start()
                        if match.start() < safe_end and absolute >= 0:
                            identifier_hits.append({"path": relative, "location": "content", "offset": absolute})
                    for match in LEGACY_PATTERN.finditer(buffer):
                        absolute = buffer_start + match.start()
                        if match.start() < safe_end and absolute >= 0:
                            legacy_placeholder_hits.append({"path": relative, "location": "content", "offset": absolute})
                    overlap = buffer[safe_end:]
                    offset += len(chunk)
                    chunk = following
        except OSError as error:
            errors.append(f"{relative}: {type(error).__name__}: {error}")
    identifier_hits.sort(key=lambda item: (str(item["path"]), str(item["location"]), int(item["offset"])))
    legacy_placeholder_hits.sort(key=lambda item: (str(item["path"]), str(item["location"]), int(item["offset"])))
    return {
        "schema_version": "1.0", "root": ".",
        "excluded_directory_names": sorted(EXCLUDED_DIRECTORIES | set(excluded_names)),
        "files_scanned": files_scanned, "bytes_scanned": bytes_scanned,
        "identifier_hit_count": len(identifier_hits), "identifier_hits": identifier_hits,
        "legacy_placeholder_hit_count": len(legacy_placeholder_hits), "legacy_placeholder_hits": legacy_placeholder_hits,
        "active_zip_count": len(zip_paths), "active_zip_paths": sorted(zip_paths),
        "error_count": len(errors), "errors": errors,
        "valid": not identifier_hits and not legacy_placeholder_hits and not zip_paths and not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-name", action="append", default=[])
    args = parser.parse_args()
    result = audit(
        args.root, ignored=(args.output,), excluded_names=frozenset(args.exclude_name),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("valid", "files_scanned", "bytes_scanned", "identifier_hit_count", "legacy_placeholder_hit_count", "active_zip_count", "error_count")}, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
