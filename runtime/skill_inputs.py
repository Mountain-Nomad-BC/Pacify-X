"""Shared bounded skill/catalog metadata acquisition; no execution authority."""

from __future__ import annotations
import tomllib
from pathlib import Path
from .json_io import decode_json_object, validate_json_value
from .input_files import (
    relative_source_path as _relative,
    check_deadline as _deadline,
    contained_file as _file,
    read_file_image as _image,
    cooperative_deadline as bounded_deadline,
)

MAX_DESCRIPTORS = 10000
MAX_CATALOG_BYTES = 1024 * 1024


def _text(value: object, name: str, limit: int = 256) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > limit
        or len(value.encode("utf-8")) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"skill {name} must be bounded nonempty text")
    return value


def _sequence(value: object, name: str, *, paths: bool = False) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or len(value) > 128:
        raise ValueError(f"skill {name} requires a bounded sequence")
    result = tuple(_relative(item) if paths else _text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"duplicate skill {name}")
    return result


def load_metadata_object(
    root: Path, relative: str, *, deadline: float | None = None
) -> dict:
    deadline = bounded_deadline(deadline)
    path, info = _file(root, relative)
    return decode_json_object(
        _image(path, info, limit=MAX_CATALOG_BYTES, deadline=deadline),
        max_bytes=MAX_CATALOG_BYTES,
        max_depth=16,
        max_nodes=100000,
    )


def load_catalog_metadata(
    root: Path, *, max_records: int = MAX_DESCRIPTORS, deadline: float | None = None
) -> dict:
    if type(max_records) is not int or not 1 <= max_records <= MAX_DESCRIPTORS:
        raise ValueError("catalog record budget must be a bounded positive integer")
    deadline = bounded_deadline(deadline)
    catalog_path, catalog_info = _file(root, "registry/skill_catalog.toml")
    try:
        raw = _image(
            catalog_path, catalog_info, limit=MAX_CATALOG_BYTES, deadline=deadline
        )
    except (ValueError, RecursionError) as error:
        raise ValueError("invalid or oversized skill catalog metadata") from error
    return parse_catalog_metadata(raw, max_records=max_records, deadline=deadline)


def parse_catalog_metadata(
    raw: bytes | bytearray,
    *,
    max_records: int = MAX_DESCRIPTORS,
    deadline: float | None = None,
) -> dict:
    """Validate supplied catalog bytes; callers own acquisition and authority."""
    if type(max_records) is not int or not 1 <= max_records <= MAX_DESCRIPTORS:
        raise ValueError("catalog record budget must be a bounded positive integer")
    deadline = bounded_deadline(deadline)
    _deadline(deadline)
    if type(raw) not in (bytes, bytearray) or len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("invalid or oversized skill catalog metadata")
    try:
        catalog = tomllib.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as error:
        raise ValueError("invalid or oversized skill catalog metadata") from error
    validate_json_value(catalog, max_depth=16, max_nodes=100000)
    if (
        set(catalog)
        != {
            "schema_version",
            "loading_rule",
            "default_active_limit",
            "hard_active_limit",
            "skills",
        }
        or catalog["schema_version"] != "1.0"
        or catalog["loading_rule"] != "metadata_only_at_startup_body_after_selection"
    ):
        raise ValueError("unsupported skill catalog contract")
    default, hard = catalog["default_active_limit"], catalog["hard_active_limit"]
    if (
        type(default) is not int
        or type(hard) is not int
        or not 1 <= default <= hard <= 8
    ):
        raise ValueError("skill catalog active limits are invalid or exceeded")
    rows = catalog["skills"]
    if type(rows) is not list or len(rows) > max_records:
        raise ValueError("skill catalog requires bounded records")
    seen = set()
    for item in rows:
        _deadline(deadline)
        if (
            type(item) is not dict
            or len(item) != 7
            or set(item)
            != {
                "id",
                "version",
                "status",
                "body",
                "contract",
                "admission_record",
                "tags",
            }
        ):
            raise ValueError(
                "skill catalog record fields are incomplete or unsupported"
            )
        identifier = _text(item["id"], "identity")
        if identifier in seen:
            raise ValueError("duplicate skill descriptor")
        seen.add(identifier)
        _relative(item["body"])
        for field in ("version", "status", "admission_record"):
            _text(item[field], field)
        _sequence(item["tags"], "tags")
        _relative(item["contract"])
    _deadline(deadline)
    return catalog
