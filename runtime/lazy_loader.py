"""Budgeted, duplicate-safe hydration of selected skill files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
from threading import RLock
import time
from types import MappingProxyType
from typing import Iterable

from .archive_io import reject_path_links
from .json_io import decode_json_object
from .skill_inputs import (
    MAX_DESCRIPTORS,
    MAX_CATALOG_BYTES as MAX_CATALOG_BYTES,
    _text,
    _relative,
    _sequence,
    _deadline,
    _file,
    _image,
    load_catalog_metadata,
)

MAX_DESCRIPTOR_BYTES = 8 * 1024 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024
MAX_PACKAGE_TOTAL_BYTES = 16 * 1024 * 1024
MAX_HYDRATION_BYTES = 64 * 1024 * 1024


def _limits(max_active, max_bytes, max_depth, max_seconds) -> None:
    for name, value, ceiling in (
        ("max_active", max_active, 8),
        ("max_bytes", max_bytes, MAX_HYDRATION_BYTES),
        ("max_depth", max_depth, 32),
    ):
        if type(value) is not int or not 1 <= value <= ceiling:
            raise ValueError(f"loader {name} must be a bounded positive integer")
    if (
        type(max_seconds) not in (int, float)
        or not 0 < max_seconds <= 300
        or not math.isfinite(max_seconds)
    ):
        raise ValueError("loader duration budget must be positive, finite and bounded")


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    capability_id: str
    body: str
    dependencies: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    status: str = "active"


@dataclass(frozen=True, slots=True)
class HydratedSkill:
    capability_id: str
    body: str
    references: tuple[tuple[str, str], ...]
    bytes_loaded: int


class LazySkillLoader:
    def __init__(
        self,
        root: Path,
        descriptors: Iterable[SkillDescriptor],
        *,
        max_active: int = 3,
        max_bytes: int = 262144,
        max_depth: int = 4,
        max_seconds: float = 10.0,
    ) -> None:
        _limits(max_active, max_bytes, max_depth, max_seconds)
        reject_path_links(root)
        self.root = root.resolve(strict=True)
        records = {}
        used = 0
        deadline = time.monotonic() + max_seconds
        for index, item in enumerate(descriptors):
            _deadline(deadline)
            if index >= MAX_DESCRIPTORS:
                raise ValueError("skill descriptor record budget exceeded")
            if type(item) is not SkillDescriptor:
                raise ValueError("typed skill descriptor is required")
            identifier = _text(item.capability_id, "identity")
            if identifier in records:
                raise ValueError("duplicate skill descriptor")
            normalized = SkillDescriptor(
                identifier,
                _relative(item.body),
                _sequence(item.dependencies, "dependencies"),
                _sequence(item.references, "references", paths=True),
                _text(item.status, "status", 64),
            )
            used += sum(
                len(value.encode("utf-8"))
                for value in (
                    normalized.capability_id,
                    normalized.body,
                    normalized.status,
                    *normalized.dependencies,
                    *normalized.references,
                )
            )
            if used > MAX_DESCRIPTOR_BYTES:
                raise ValueError("skill descriptor metadata byte budget exceeded")
            records[identifier] = normalized
        _deadline(deadline)
        self.descriptors = MappingProxyType(records)
        self.max_active = max_active
        self.max_bytes = max_bytes
        self.max_depth = max_depth
        self.max_seconds = max_seconds
        self._active: dict[str, HydratedSkill] = {}
        self._lock = RLock()

    @classmethod
    def from_catalog(
        cls,
        root: Path,
        *,
        max_active: int = 3,
        max_bytes: int = 262144,
        max_depth: int = 4,
        max_seconds: float = 10.0,
    ) -> "LazySkillLoader":
        _limits(max_active, max_bytes, max_depth, max_seconds)
        reject_path_links(root)
        deadline = time.monotonic() + max_seconds
        catalog = load_catalog_metadata(root, deadline=deadline)
        if max_active > catalog["hard_active_limit"]:
            raise ValueError("skill catalog active limits are invalid or exceeded")
        rows = catalog["skills"]
        packages = {}
        total = 0
        for item in rows:
            _deadline(deadline)
            contract = item["contract"]
            if "skill_packages" in contract.split("/") and contract not in packages:
                path, info = _file(root, contract)
                if info.st_size > MAX_PACKAGE_BYTES:
                    raise ValueError("skill package metadata byte budget exceeded")
                total += info.st_size
                if total > MAX_PACKAGE_TOTAL_BYTES:
                    raise ValueError(
                        "skill package aggregate metadata byte budget exceeded"
                    )
                packages[contract] = (path, info)
        package_references = {}
        for contract, (path, info) in packages.items():
            raw = _image(path, info, limit=MAX_PACKAGE_BYTES, deadline=deadline)
            package = decode_json_object(
                raw, max_bytes=MAX_PACKAGE_BYTES, max_depth=16, max_nodes=50000
            )
            package_references[contract] = _sequence(
                package.get("references", ()), "references", paths=True
            )
        descriptors: list[SkillDescriptor] = []
        for item in rows:
            references = package_references.get(item["contract"], ())
            dependencies: tuple[str, ...] = ()
            descriptors.append(
                SkillDescriptor(
                    item["id"],
                    item["body"],
                    dependencies,
                    references,
                    item["status"],
                )
            )
        _deadline(deadline)
        result = cls(
            root,
            descriptors,
            max_active=max_active,
            max_bytes=max_bytes,
            max_depth=max_depth,
            max_seconds=max_seconds,
        )
        _deadline(deadline)
        return result

    def _read(self, relative: str) -> str:
        path, info = _file(self.root, relative)
        raw = _image(
            path,
            info,
            limit=self.max_bytes,
            deadline=time.monotonic() + self.max_seconds,
        )
        return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")

    @property
    def footprint_bytes(self) -> int:
        with self._lock:
            return sum(item.bytes_loaded for item in self._active.values())

    @property
    def active_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))

    def hydrate(
        self, capability_id: str, *, include_references: bool = False, _depth: int = 0
    ) -> HydratedSkill:
        del (
            _depth
        )  # retained only for source compatibility; recursion is transaction-local.
        _text(capability_id, "identity")
        if type(include_references) is not bool:
            raise ValueError("include_references must be boolean")
        _limits(self.max_active, self.max_bytes, self.max_depth, self.max_seconds)
        deadline = time.monotonic() + self.max_seconds
        if not self._lock.acquire(timeout=self.max_seconds):
            raise ValueError("skill hydration lock duration budget exhausted")
        try:
            _deadline(deadline)
            ordered = []
            requested = {}
            new_ids = set()
            visiting: set[str] = set()

            def plan(identifier: str, depth: int, references_requested: bool) -> None:
                _deadline(deadline)
                descriptor = self.descriptors.get(identifier)
                if descriptor is None:
                    raise KeyError(f"unknown skill: {identifier}")
                if descriptor.status not in {"active", "admitted"}:
                    raise PermissionError(
                        f"skill is not admitted for hydration: {identifier}"
                    )
                existing = self._active.get(identifier)
                if existing is not None and (
                    not references_requested
                    or existing.references
                    or not descriptor.references
                ):
                    return
                if identifier in requested:
                    return
                if depth >= self.max_depth:
                    raise ValueError("skill dependency depth exceeds budget")
                if identifier in visiting:
                    raise ValueError("skill dependency cycle detected")
                if existing is None:
                    new_ids.add(identifier)
                    if len(self._active) + len(new_ids) > self.max_active:
                        raise ValueError("active skill budget exhausted")
                visiting.add(identifier)
                try:
                    for dependency in descriptor.dependencies:
                        plan(dependency, depth + 1, False)
                    requested[identifier] = references_requested
                    ordered.append(identifier)
                finally:
                    visiting.remove(identifier)

            plan(capability_id, 0, include_references)
            if not ordered:
                return self._active[capability_id]
            remaining = self.max_bytes - self.footprint_bytes
            files = {}
            logical_raw_bytes = 0
            for identifier in ordered:
                descriptor = self.descriptors[identifier]
                paths = [] if identifier in self._active else [descriptor.body]
                if requested[identifier]:
                    paths.extend(descriptor.references)
                for relative in paths:
                    _deadline(deadline)
                    if relative not in files:
                        files[relative] = _file(self.root, relative)
                    logical_raw_bytes += files[relative][1].st_size
                    if logical_raw_bytes > remaining:
                        raise ValueError(
                            "skill context byte budget exhausted before acquisition"
                        )
            images = {}
            raw_used = 0
            for relative, (path, info) in files.items():
                raw = _image(path, info, limit=remaining - raw_used, deadline=deadline)
                raw_used += len(raw)
                # Preserve Path.read_text's universal newline behavior. Raw input
                # is conservatively bounded separately from retained UTF-8 text.
                images[relative] = (
                    raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                )
            prepared = {}
            added_bytes = 0
            for identifier in ordered:
                descriptor = self.descriptors[identifier]
                existing = self._active.get(identifier)
                body = (
                    existing.body if existing is not None else images[descriptor.body]
                )
                references = (
                    tuple((path, images[path]) for path in descriptor.references)
                    if requested[identifier]
                    else (existing.references if existing is not None else ())
                )
                loaded = len(body.encode("utf-8")) + sum(
                    len(value.encode("utf-8")) for _, value in references
                )
                prepared[identifier] = HydratedSkill(
                    identifier, body, references, loaded
                )
                added_bytes += loaded - (
                    existing.bytes_loaded if existing is not None else 0
                )
            if added_bytes > remaining:
                raise ValueError("skill context byte budget exhausted")
            _deadline(deadline)
            # The only mutation in hydration happens after every read, contract,
            # dependency, depth, count, and byte-budget check succeeds.
            self._active.update(prepared)
            return self._active[capability_id]
        finally:
            self._lock.release()

    def unload(self, capability_id: str) -> bool:
        with self._lock:
            return self._active.pop(capability_id, None) is not None

    def unload_all(self) -> None:
        with self._lock:
            self._active.clear()
