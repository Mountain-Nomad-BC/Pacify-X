"""Budgeted, duplicate-safe hydration of selected skill files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from threading import RLock
import tomllib
from typing import Iterable


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
    ) -> None:
        if min(max_active, max_bytes, max_depth) < 1:
            raise ValueError("loader budgets must be positive")
        self.root = root.resolve()
        descriptor_records = tuple(descriptors)
        self.descriptors = {item.capability_id: item for item in descriptor_records}
        if len(self.descriptors) != len(descriptor_records):
            raise ValueError("duplicate skill descriptor")
        self.max_active = max_active
        self.max_bytes = max_bytes
        self.max_depth = max_depth
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
    ) -> "LazySkillLoader":
        resolved = root.resolve()
        catalog = tomllib.loads(
            (resolved / "registry/skill_catalog.toml").read_text(encoding="utf-8")
        )
        descriptors: list[SkillDescriptor] = []
        for item in catalog.get("skills", ()):
            references: tuple[str, ...] = ()
            dependencies: tuple[str, ...] = ()
            contract_path = resolved / item["contract"]
            if "skill_packages" in contract_path.parts:
                package = json.loads(contract_path.read_text(encoding="utf-8"))
                references = tuple(package.get("references", ()))
            descriptors.append(
                SkillDescriptor(
                    item["id"],
                    item["body"],
                    dependencies,
                    references,
                    str(item.get("status", "candidate")),
                )
            )
        return cls(
            resolved,
            descriptors,
            max_active=max_active,
            max_bytes=max_bytes,
            max_depth=max_depth,
        )

    def _read(self, relative: str) -> str:
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("skill path escapes trusted root")
        return path.read_text(encoding="utf-8")

    @property
    def footprint_bytes(self) -> int:
        return sum(item.bytes_loaded for item in self._active.values())

    @property
    def active_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._active))

    def hydrate(
        self, capability_id: str, *, include_references: bool = False, _depth: int = 0
    ) -> HydratedSkill:
        del (
            _depth
        )  # retained only for source compatibility; recursion is transaction-local.
        with self._lock:
            if capability_id in self._active:
                return self._active[capability_id]
            prepared: dict[str, HydratedSkill] = {}
            visiting: set[str] = set()

            def prepare(
                identifier: str, depth: int, references_requested: bool
            ) -> None:
                if identifier in self._active or identifier in prepared:
                    return
                if depth >= self.max_depth:
                    raise ValueError("skill dependency depth exceeds budget")
                if identifier in visiting:
                    raise ValueError("skill dependency cycle detected")
                descriptor = self.descriptors.get(identifier)
                if descriptor is None:
                    raise KeyError(f"unknown skill: {identifier}")
                if descriptor.status not in {"active", "admitted"}:
                    raise PermissionError(
                        f"skill is not admitted for hydration: {identifier}"
                    )
                visiting.add(identifier)
                try:
                    for dependency in descriptor.dependencies:
                        prepare(dependency, depth + 1, False)
                    body = self._read(descriptor.body)
                    references = (
                        tuple(
                            (path, self._read(path)) for path in descriptor.references
                        )
                        if references_requested
                        else ()
                    )
                    loaded = len(body.encode()) + sum(
                        len(value.encode()) for _, value in references
                    )
                    prepared[identifier] = HydratedSkill(
                        identifier, body, references, loaded
                    )
                finally:
                    visiting.remove(identifier)

            prepare(capability_id, 0, include_references)
            if len(self._active) + len(prepared) > self.max_active:
                raise ValueError("active skill budget exhausted")
            if (
                self.footprint_bytes
                + sum(item.bytes_loaded for item in prepared.values())
                > self.max_bytes
            ):
                raise ValueError("skill context byte budget exhausted")
            # The only mutation in hydration happens after every read, contract,
            # dependency, depth, count, and byte-budget check succeeds.
            self._active.update(prepared)
            return self._active[capability_id]

    def unload(self, capability_id: str) -> bool:
        with self._lock:
            return self._active.pop(capability_id, None) is not None

    def unload_all(self) -> None:
        with self._lock:
            self._active.clear()
