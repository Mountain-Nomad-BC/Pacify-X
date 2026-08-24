"""Audit a tree for private identifiers and active ZIP archives without mutating it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.repository_scope import is_external_environment_relative  # noqa: E402


TERMS = ("r" + "ie", "re" + "my", "rh" + "eem")
PATTERN = re.compile(
    rb"(?i)(?:(?<![A-Za-z])("
    + TERMS[0].encode()
    + rb")(?![A-Za-z])|("
    + TERMS[1].encode()
    + rb"|"
    + TERMS[2].encode()
    + rb"))"
)
LEGACY_TERMS = ("integration" + "_" + "engine", "governed" + "_" + "retrieval")
LEGACY_PATTERN = re.compile(
    rb"(?i)("
    + LEGACY_TERMS[0].encode()
    + rb"|"
    + LEGACY_TERMS[1].encode()
    + rb"(?!_system_with_deterministic_rails))"
)
HOST_HOME_PATTERN = re.compile(
    rb"(?i)(?:[a-z]:[\\/]+users[\\/]+[a-z0-9._-]+|/(?:home|users)/[a-z0-9._-]+)"
)
EXCLUDED_DIRECTORIES = {".git"}
BINARY_SUFFIXES = {
    ".7z",
    ".avi",
    ".bmp",
    ".dll",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".tar",
    ".vsix",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}
TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".svg",
    ".toml",
    ".ts",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def _is_admitted_text(path: Path) -> bool:
    """Classify content before applying text-only identifier patterns."""
    suffix = path.suffix.casefold()
    if suffix in BINARY_SUFFIXES:
        return False
    if suffix in TEXT_SUFFIXES or path.name in {"LICENSE", "NOTICE"}:
        return True
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
            chunk = handle.read(1024 * 1024)
            while chunk:
                chunk = handle.read(1024 * 1024)
    except (OSError, UnicodeDecodeError):
        return False
    return True


def audit(
    root: Path,
    *,
    ignored: tuple[Path, ...] = (),
    excluded_names: frozenset[str] = frozenset(),
) -> dict[str, object]:
    resolved = root.resolve()
    ignored_paths = {path.resolve() for path in ignored}
    identifier_hits: list[dict[str, object]] = []
    legacy_placeholder_hits: list[dict[str, object]] = []
    host_home_hits: list[dict[str, object]] = []
    zip_paths: list[str] = []
    files_scanned = 0
    bytes_scanned = 0
    errors: list[str] = []
    for path in sorted(
        resolved.rglob("*"), key=lambda item: item.as_posix().casefold()
    ):
        if any(
            part in EXCLUDED_DIRECTORIES or part in excluded_names
            for part in path.relative_to(resolved).parts
        ) or is_external_environment_relative(path.relative_to(resolved)):
            continue
        if not path.is_file() or path.resolve() in ignored_paths:
            continue
        relative = path.relative_to(resolved).as_posix()
        files_scanned += 1
        if path.suffix.casefold() == ".zip":
            zip_paths.append(relative)
        path_match = PATTERN.search(relative.encode("utf-8", errors="replace"))
        if path_match:
            identifier_hits.append(
                {"path": relative, "location": "path", "offset": path_match.start()}
            )
        legacy_path_match = LEGACY_PATTERN.search(
            relative.encode("utf-8", errors="replace")
        )
        if legacy_path_match:
            legacy_placeholder_hits.append(
                {
                    "path": relative,
                    "location": "path",
                    "offset": legacy_path_match.start(),
                }
            )
        host_path_match = HOST_HOME_PATTERN.search(
            relative.encode("utf-8", errors="replace")
        )
        if host_path_match:
            host_home_hits.append(
                {"path": relative, "location": "path", "offset": host_path_match.start()}
            )
        try:
            if not _is_admitted_text(path):
                bytes_scanned += path.stat().st_size
                continue
            overlap = b""
            offset = 0
            with path.open("rb") as handle:
                chunk = handle.read(1024 * 1024)
                while chunk:
                    following = handle.read(1024 * 1024)
                    bytes_scanned += len(chunk)
                    buffer = overlap + chunk
                    safe_end = (
                        len(buffer) if not following else max(0, len(buffer) - 128)
                    )
                    buffer_start = offset - len(overlap)
                    for match in PATTERN.finditer(buffer):
                        absolute = buffer_start + match.start()
                        if match.start() < safe_end and absolute >= 0:
                            identifier_hits.append(
                                {
                                    "path": relative,
                                    "location": "content",
                                    "offset": absolute,
                                }
                            )
                    for match in LEGACY_PATTERN.finditer(buffer):
                        absolute = buffer_start + match.start()
                        if match.start() < safe_end and absolute >= 0:
                            legacy_placeholder_hits.append(
                                {
                                    "path": relative,
                                    "location": "content",
                                    "offset": absolute,
                                }
                            )
                    for match in HOST_HOME_PATTERN.finditer(buffer):
                        absolute = buffer_start + match.start()
                        if match.start() < safe_end and absolute >= 0:
                            host_home_hits.append(
                                {
                                    "path": relative,
                                    "location": "content",
                                    "offset": absolute,
                                }
                            )
                    overlap = buffer[safe_end:]
                    offset += len(chunk)
                    chunk = following
        except OSError as error:
            errors.append(f"{relative}: {type(error).__name__}: {error}")
    identifier_hits.sort(
        key=lambda item: (str(item["path"]), str(item["location"]), int(item["offset"]))
    )
    legacy_placeholder_hits.sort(
        key=lambda item: (str(item["path"]), str(item["location"]), int(item["offset"]))
    )
    host_home_hits.sort(
        key=lambda item: (str(item["path"]), str(item["location"]), int(item["offset"]))
    )
    exclusions = sorted(EXCLUDED_DIRECTORIES | set(excluded_names))

    def gate(
        name: str, status: str, findings: object, limitations: str
    ) -> dict[str, object]:
        return {
            "name": name,
            "status": status,
            "tool": "audit_sanitization.py",
            "corpus": ".",
            "exclusions": exclusions,
            "limitations": limitations,
            "findings": findings,
            "disposition": "pass"
            if status == "passed"
            else ("fail" if status == "failed" else "not_run"),
        }

    gates = {
        "brand_identifier_sanitation": gate(
            "brand_identifier_sanitation",
            "failed" if identifier_hits else "passed",
            identifier_hits,
            "Configured identifier patterns only; not a general secret or PII scan.",
        ),
        "legacy_placeholder_detection": gate(
            "legacy_placeholder_detection",
            "failed" if legacy_placeholder_hits else "passed",
            legacy_placeholder_hits,
            "Configured legacy placeholder patterns only.",
        ),
        "host_home_path_sanitation": gate(
            "host_home_path_sanitation",
            "failed" if host_home_hits else "passed",
            host_home_hits,
            "Detects absolute Windows, Linux, and macOS user-home paths.",
        ),
        "archive_detection": gate(
            "archive_detection",
            "failed" if zip_paths else "passed",
            sorted(zip_paths),
            "Detects active ZIP paths only; does not inspect archive contents.",
        ),
        "secret_scanning": gate(
            "secret_scanning",
            "not_run",
            [],
            "No credential/secret scanner was invoked by this control.",
        ),
        "credential_scanning": gate(
            "credential_scanning",
            "not_run",
            [],
            "No credential scanner was invoked by this control.",
        ),
        "pii_review": gate(
            "pii_review",
            "not_run",
            [],
            "No PII review tool or human review was invoked.",
        ),
        "binary_review": gate(
            "binary_review",
            "not_run",
            [],
            "Binary payload classification is outside this identifier scanner.",
        ),
        "license_provenance_review": gate(
            "license_provenance_review",
            "not_run",
            [],
            "License and provenance review requires a separate admitted control.",
        ),
    }
    scoped_valid = (
        not identifier_hits
        and not legacy_placeholder_hits
        and not host_home_hits
        and not zip_paths
        and not errors
    )
    not_run = sorted(
        name for name, value in gates.items() if value["status"] == "not_run"
    )
    return {
        "schema_version": "1.0",
        "root": ".",
        "excluded_directory_names": exclusions,
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "identifier_hit_count": len(identifier_hits),
        "identifier_hits": identifier_hits,
        "legacy_placeholder_hit_count": len(legacy_placeholder_hits),
        "legacy_placeholder_hits": legacy_placeholder_hits,
        "host_home_path_hit_count": len(host_home_hits),
        "host_home_path_hits": host_home_hits,
        "active_zip_count": len(zip_paths),
        "active_zip_paths": sorted(zip_paths),
        "error_count": len(errors),
        "errors": errors,
        "gates": gates,
        "scoped_valid": scoped_valid,
        "valid": scoped_valid and not not_run,
        "limitations": [f"Required comprehensive gates not run: {', '.join(not_run)}"]
        if not_run
        else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-name", action="append", default=[])
    args = parser.parse_args()
    result = audit(
        args.root,
        ignored=(args.output,),
        excluded_names=frozenset(args.exclude_name),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "valid",
                    "files_scanned",
                    "bytes_scanned",
                    "identifier_hit_count",
                    "legacy_placeholder_hit_count",
                    "active_zip_count",
                    "error_count",
                )
            },
            indent=2,
        )
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
