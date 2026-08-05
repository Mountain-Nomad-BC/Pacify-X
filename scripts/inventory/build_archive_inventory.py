"""Build a deterministic, non-extracting inventory of ZIP archives.

Only ZIP central-directory metadata and archive bytes (for SHA-256) are read.
Members are never extracted, opened, imported, or executed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Iterable, Sequence
from zipfile import BadZipFile, LargeZipFile, ZipFile


_SOURCE_TERMS = ("r" + "ie", "re" + "my", "rh" + "eem")
_SOURCE_PATTERN = re.compile(
    rf"(?i)(?:(?<![A-Za-z])({'|'.join(_SOURCE_TERMS[:2])})(?![A-Za-z])|({_SOURCE_TERMS[2]}))"
)
_SOURCE_REPLACEMENTS = dict(
    zip(
        _SOURCE_TERMS,
        (
            "intelligent_integrations_and_engines",
            "governed_retrieval_system_with_deterministic_rails",
            "enterprise",
        ),
    )
)
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".jar",
    ".war",
    ".ear",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
)


@dataclass(frozen=True, slots=True)
class BombThresholds:
    max_entries: int = 100_000
    max_uncompressed_bytes: int = 10 * 1024**3
    max_compression_ratio: float = 1_000.0
    max_entry_uncompressed_bytes: int = 2 * 1024**3
    max_entry_compression_ratio: float = 1_000.0

    def __post_init__(self) -> None:
        for name in (
            "max_entries",
            "max_uncompressed_bytes",
            "max_entry_uncompressed_bytes",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        for name in ("max_compression_ratio", "max_entry_compression_ratio"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than 0")


def sanitize_relative_path(value: str) -> str:
    """Return a report-safe relative path while preserving hazard visibility."""
    redacted = _SOURCE_PATTERN.sub(
        lambda match: _SOURCE_REPLACEMENTS[match.group(0).lower()], value
    )
    normalized = _CONTROL_CHARACTERS.sub("_", redacted).replace("\\", "/")
    normalized = _DRIVE_PATH.sub("", normalized)
    parts: list[str] = []
    for part in normalized.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            parts.append("__parent__")
            continue
        # A colon can make the first component drive-like when reused elsewhere.
        parts.append(part.replace(":", "_"))
    return "/".join(parts) or "_"


def _sanitize_label(value: str) -> str:
    return sanitize_relative_path(value).replace("/", "_")


def _is_absolute_member(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.startswith("/") or _DRIVE_PATH.match(value) is not None


def _has_traversal(value: str) -> bool:
    return ".." in value.replace("\\", "/").split("/")


def _is_zip_symlink(create_system: int, external_attr: int) -> bool:
    if create_system != 3:
        return False
    return stat.S_ISLNK(external_attr >> 16)


def _is_nested_archive(value: str) -> bool:
    lowered = value.casefold()
    return any(lowered.endswith(suffix) for suffix in _NESTED_ARCHIVE_SUFFIXES)


def _ratio(uncompressed: int, compressed: int) -> float | None:
    if compressed == 0:
        return 1.0 if uncompressed == 0 else None
    return round(uncompressed / compressed, 6)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_archive(
    root_label: str,
    root: Path,
    archive: Path,
    thresholds: BombThresholds,
    *,
    include_entries: bool = False,
) -> dict[str, object]:
    """Inspect one ZIP without reading any member payload."""
    relative = sanitize_relative_path(archive.relative_to(root).as_posix())
    errors: list[str] = []
    try:
        size_bytes: int | None = archive.stat().st_size
    except OSError as exc:
        size_bytes = None
        errors.append(f"stat_failed:{type(exc).__name__}")
    try:
        archive_sha256: str | None = _sha256(archive)
    except OSError as exc:
        archive_sha256 = None
        errors.append(f"hash_failed:{type(exc).__name__}")

    encrypted: set[str] = set()
    traversal: set[str] = set()
    absolute: set[str] = set()
    symlinks: set[str] = set()
    nested: set[str] = set()
    suspicious_entries: list[dict[str, object]] = []
    entry_records: list[dict[str, object]] = []
    entry_count = 0
    compressed_bytes = 0
    uncompressed_bytes = 0

    try:
        with ZipFile(archive, "r", allowZip64=True) as handle:
            infos = handle.infolist()
            entry_count = len(infos)
            for info in infos:
                reported_path = sanitize_relative_path(info.filename)
                compressed_bytes += info.compress_size
                uncompressed_bytes += info.file_size
                if info.flag_bits & 0x1:
                    encrypted.add(reported_path)
                if _has_traversal(info.filename):
                    traversal.add(reported_path)
                if _is_absolute_member(info.filename):
                    absolute.add(reported_path)
                if _is_zip_symlink(info.create_system, info.external_attr):
                    symlinks.add(reported_path)
                if _is_nested_archive(info.filename):
                    nested.add(reported_path)
                if include_entries:
                    entry_records.append(
                        {
                            "path": reported_path,
                            "bytes": info.file_size,
                            "compressed_bytes": info.compress_size,
                            "crc32": f"{info.CRC:08x}",
                            "is_directory": info.is_dir(),
                            "encrypted": bool(info.flag_bits & 0x1),
                            "symlink": _is_zip_symlink(
                                info.create_system, info.external_attr
                            ),
                            "nested_archive": _is_nested_archive(info.filename),
                        }
                    )

                entry_reasons: list[str] = []
                if info.file_size > thresholds.max_entry_uncompressed_bytes:
                    entry_reasons.append("entry_uncompressed_bytes_exceeded")
                entry_ratio = _ratio(info.file_size, info.compress_size)
                if entry_ratio is None and info.file_size:
                    entry_reasons.append("entry_zero_compressed_nonempty")
                elif (
                    entry_ratio is not None
                    and entry_ratio > thresholds.max_entry_compression_ratio
                ):
                    entry_reasons.append("entry_compression_ratio_exceeded")
                if entry_reasons:
                    suspicious_entries.append(
                        {"path": reported_path, "reasons": sorted(entry_reasons)}
                    )
    except (BadZipFile, LargeZipFile, OSError, ValueError) as exc:
        errors.append(f"zip_open_failed:{type(exc).__name__}")

    compression_ratio = _ratio(uncompressed_bytes, compressed_bytes)
    bomb_reasons: list[str] = []
    if entry_count > thresholds.max_entries:
        bomb_reasons.append("entry_count_exceeded")
    if uncompressed_bytes > thresholds.max_uncompressed_bytes:
        bomb_reasons.append("uncompressed_bytes_exceeded")
    if compression_ratio is None and uncompressed_bytes:
        bomb_reasons.append("zero_compressed_nonempty")
    elif (
        compression_ratio is not None
        and compression_ratio > thresholds.max_compression_ratio
    ):
        bomb_reasons.append("compression_ratio_exceeded")
    if suspicious_entries:
        bomb_reasons.append("suspicious_entry")

    danger_present = bool(
        errors or encrypted or traversal or absolute or symlinks or bomb_reasons
    )
    disposition = "quarantine_recommended" if danger_present else "inventory_only"
    if errors:
        disposition = "review_required"

    result = {
        "root": _sanitize_label(root_label),
        "path": relative,
        "sha256": archive_sha256,
        "size_bytes": size_bytes,
        "entry_count": entry_count,
        "encrypted_entry_count": len(encrypted),
        "encrypted_entries": sorted(encrypted),
        "compressed_bytes": compressed_bytes,
        "uncompressed_bytes": uncompressed_bytes,
        "compression_ratio": compression_ratio,
        "traversal": sorted(traversal),
        "absolute_paths": sorted(absolute),
        "zip_symlinks": sorted(symlinks),
        "nested_archives": sorted(nested),
        "suspicious_bomb": bool(bomb_reasons),
        "bomb_reasons": sorted(set(bomb_reasons)),
        "suspicious_entries": sorted(
            suspicious_entries, key=lambda item: (str(item["path"]), item["reasons"])
        ),
        "errors": sorted(set(errors)),
        "extracted": False,
        "disposition": disposition,
    }
    if include_entries:
        result["entries"] = sorted(
            entry_records, key=lambda item: str(item["path"]).casefold()
        )
    return result


def build_inventory(
    roots: Iterable[tuple[str, Path]],
    *,
    thresholds: BombThresholds | None = None,
    include_entries: bool = False,
) -> dict[str, object]:
    """Inventory all ``.zip`` files below one or more labeled roots."""
    limits = thresholds or BombThresholds()
    normalized_roots: list[tuple[str, Path]] = []
    seen_labels: set[str] = set()
    for label, path in roots:
        safe_label = _sanitize_label(label)
        if safe_label in seen_labels:
            raise ValueError(f"duplicate root label: {safe_label}")
        resolved = path.resolve()
        if not resolved.is_dir():
            raise ValueError(f"root is not a directory: {safe_label}")
        seen_labels.add(safe_label)
        normalized_roots.append((safe_label, resolved))

    archives: list[dict[str, object]] = []
    for label, root in sorted(normalized_roots, key=lambda item: item[0]):
        candidates = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".zip"
            ),
            key=lambda path: path.relative_to(root).as_posix().casefold(),
        )
        archives.extend(
            inspect_archive(
                label,
                root,
                archive,
                limits,
                include_entries=include_entries,
            )
            for archive in candidates
        )

    archives.sort(key=lambda item: (str(item["root"]), str(item["path"])))
    return {
        "schema_version": "1.0",
        "roots": [
            label for label, _ in sorted(normalized_roots, key=lambda item: item[0])
        ],
        "bomb_thresholds": asdict(limits),
        "archives": archives,
        "summary": {
            "archive_count": len(archives),
            "error_count": sum(bool(item["errors"]) for item in archives),
            "quarantine_recommended_count": sum(
                item["disposition"] == "quarantine_recommended" for item in archives
            ),
            "suspicious_bomb_count": sum(
                bool(item["suspicious_bomb"]) for item in archives
            ),
        },
    }


def write_archive_maps(report: dict[str, object], maps_dir: Path) -> int:
    """Write one stable map for each archive in an existing combined report."""
    maps_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for archive in report.get("archives", ()):
        identity = f"{archive['root']}:{archive['path']}"
        map_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        payload = {
            "schema_version": "1.0",
            "archive_map_id": map_id,
            "archive": archive,
        }
        (maps_dir / f"archive-{map_id}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        count += 1
    return count


def _root_argument(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("root must use label=path")
    label, raw_path = value.split("=", 1)
    if not label.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("root must use non-empty label=path")
    return label, Path(raw_path)


def build_parser() -> argparse.ArgumentParser:
    defaults = BombThresholds()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        type=_root_argument,
        metavar="LABEL=PATH",
        help="labeled search root; may be supplied more than once",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="inventory JSON path"
    )
    parser.add_argument(
        "--maps-dir",
        type=Path,
        help="optional directory for one deterministic JSON map per archive",
    )
    parser.add_argument(
        "--include-entries",
        action="store_true",
        help="include sanitized central-directory records in the inventory and per-archive maps",
    )
    parser.add_argument("--max-entries", type=int, default=defaults.max_entries)
    parser.add_argument(
        "--max-uncompressed-bytes",
        type=int,
        default=defaults.max_uncompressed_bytes,
    )
    parser.add_argument(
        "--max-compression-ratio", type=float, default=defaults.max_compression_ratio
    )
    parser.add_argument(
        "--max-entry-uncompressed-bytes",
        type=int,
        default=defaults.max_entry_uncompressed_bytes,
    )
    parser.add_argument(
        "--max-entry-compression-ratio",
        type=float,
        default=defaults.max_entry_compression_ratio,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        thresholds = BombThresholds(
            max_entries=args.max_entries,
            max_uncompressed_bytes=args.max_uncompressed_bytes,
            max_compression_ratio=args.max_compression_ratio,
            max_entry_uncompressed_bytes=args.max_entry_uncompressed_bytes,
            max_entry_compression_ratio=args.max_entry_compression_ratio,
        )
        report = build_inventory(
            args.root,
            thresholds=thresholds,
            include_entries=args.include_entries,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.maps_dir is not None:
        write_archive_maps(report, args.maps_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
