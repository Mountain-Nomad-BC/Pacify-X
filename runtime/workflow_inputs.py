"""Bounded declaration relationships; structural validation grants no authority."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

from .archive_io import reject_path_links
from .input_files import (
    check_deadline, contained_file, directory_root, read_file_image,
    relative_source_path,
)
from .json_io import decode_json_object
from .numeric_inputs import bounded_integer, bounded_json_value, bounded_mapping, bounded_text
from .studio_filesystem import bounded_directory_entries


MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_RECORDS = 4096
MAX_STEPS = 512
MAX_EDGES = 4096
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def declaration_id(value: object) -> str:
    value = bounded_text(value, "declaration identity", maximum=128, strip=False)
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("invalid declaration identity")
    return value


def read_declaration(root: Path, relative: str, *, deadline: float) -> dict:
    """Parse one contained image, including the complete bounded TOML document."""
    root = directory_root(root)
    path, info = contained_file(root, relative)
    raw = read_file_image(path, info, limit=MAX_DOCUMENT_BYTES, deadline=deadline)
    if path.suffix == ".toml":
        value = tomllib.loads(raw.decode("utf-8"))
        bounded_json_value(value)
    else:
        value = decode_json_object(
            raw, max_bytes=MAX_DOCUMENT_BYTES, max_depth=32, max_nodes=100000
        )
    check_deadline(deadline)
    return bounded_mapping(value, "declaration document", maximum=64)


def unique_declarations(
    value: object, key: str, *, maximum: int = MAX_RECORDS,
    path_keys: bool = False, minimum: int = 1,
) -> dict[str, dict]:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError("declaration list is missing or outside its count budget")
    result = {}
    aliases = set()
    for item in value:
        item = bounded_mapping(item, "declaration record", maximum=64)
        identity = (
            relative_source_path(item.get(key))
            if path_keys else declaration_id(item.get(key))
        )
        alias = identity.casefold() if path_keys else identity
        if alias in aliases:
            raise ValueError("duplicate declaration identity")
        aliases.add(alias)
        result[identity] = item
    return result


def require_declared_count(document: dict, key: str, actual: int) -> None:
    count = bounded_integer(
        document.get(key), "declaration count", minimum=0, maximum=MAX_RECORDS
    )
    if count != actual:
        raise ValueError("declaration count does not match its complete records")


def ordered_steps(value: object) -> tuple[dict, ...]:
    """Require unique steps and edges, with dependencies preceding consumers."""
    records = unique_declarations(value, "id", maximum=MAX_STEPS)
    seen = set()
    edges = 0
    for identity, row in records.items():
        declaration_id(row.get("skill"))
        dependencies = row.get("depends_on")
        if type(dependencies) is not list or len(dependencies) > MAX_STEPS:
            raise ValueError("step dependencies must be a bounded array")
        edges += len(dependencies)
        if edges > MAX_EDGES:
            raise ValueError("workflow dependency edge budget exceeded")
        distinct = set()
        for dependency in dependencies:
            dependency = declaration_id(dependency)
            if dependency in distinct:
                raise ValueError("duplicate step dependency")
            distinct.add(dependency)
            if dependency not in seen:
                raise ValueError("step dependency is missing, cyclic or out of order")
        seen.add(identity)
    return tuple(records.values())


def active_skill_declarations(root: Path, *, deadline: float) -> set[str]:
    catalog = read_declaration(root, "registry/skill_catalog.toml", deadline=deadline)
    records = unique_declarations(catalog.get("skills"), "id")
    active = set()
    for identity, row in records.items():
        status = bounded_text(row.get("status"), "skill status", maximum=64, strip=False)
        if status in {"active", "admitted"}:
            active.add(identity)
    return active


def declaration_paths(
    root: Path, relative: str, *, deadline: float, directories: bool = False,
) -> set[str]:
    """Bound direct enumeration before filtering; reject original links and aliases."""
    root = directory_root(root)
    relative = relative_source_path(relative)
    base = directory_root(root / relative)
    entries = bounded_directory_entries(
        base, MAX_RECORDS, lambda: ValueError("declaration directory budget exceeded")
    )
    selected = set()
    aliases = set()
    for path in entries:
        check_deadline(deadline)
        reject_path_links(path)
        if directories:
            if not path.is_dir():
                continue
            identity = declaration_id(path.name)
        else:
            if path.suffix != ".yaml":
                continue
            contained_file(root, path.relative_to(root).as_posix())
            identity = relative_source_path(path.relative_to(root).as_posix())
        if identity.casefold() in aliases:
            raise ValueError("ambiguous declaration path")
        aliases.add(identity.casefold())
        selected.add(identity)
    if not selected:
        raise ValueError("declaration directory is empty")
    return selected
