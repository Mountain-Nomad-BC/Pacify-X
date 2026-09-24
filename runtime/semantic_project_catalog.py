"""Explicit project catalog and per-project query borrowing without mutable active-project state."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore, RLock
from typing import Iterator

from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import ProjectDescriptor


class SemanticProjectCatalog:
    def __init__(self, *, limits: SemanticIntegrationLimits = SemanticIntegrationLimits()):
        self.limits = limits
        self._projects: dict[str, ProjectDescriptor] = {}
        self._locks: dict[str, RLock] = {}
        self._guard = RLock()
        self._slots = BoundedSemaphore(limits.max_concurrent_project_queries)

    def register(
        self,
        project_id: str,
        root: Path,
        *,
        read_only: bool = True,
        labels: tuple[str, ...] = (),
    ) -> ProjectDescriptor:
        if type(project_id) is not str or not project_id.strip() or len(project_id.encode("utf-8")) > 256:
            raise ValueError("project_id must be bounded nonempty text")
        if type(read_only) is not bool:
            raise TypeError("read_only must be a boolean")
        if type(labels) is not tuple or len(labels) > 64:
            raise ValueError("labels must be a tuple with at most 64 entries")
        normalized_labels: list[str] = []
        for label in labels:
            if type(label) is not str or not label.strip() or len(label.encode("utf-8")) > 256:
                raise ValueError("project labels must be bounded nonempty text")
            normalized_labels.append(label)
        if len(set(normalized_labels)) != len(normalized_labels):
            raise ValueError("project labels must be unique")

        resolved = Path(root).resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("project root must be a directory")
        descriptor = ProjectDescriptor(
            project_id,
            resolved.as_posix(),
            read_only,
            tuple(sorted(normalized_labels)),
        )
        with self._guard:
            if project_id in self._projects and self._projects[project_id] != descriptor:
                raise ValueError("project_id is already bound to a different project")
            if project_id not in self._projects and len(self._projects) >= self.limits.max_projects:
                raise ValueError("project catalog budget exceeded")
            self._projects[project_id] = descriptor
            self._locks.setdefault(project_id, RLock())
        return descriptor

    def get(self, project_id: str) -> ProjectDescriptor:
        with self._guard:
            try:
                return self._projects[project_id]
            except KeyError as exc:
                raise KeyError(f"unknown project {project_id!r}") from exc

    def ids(self) -> tuple[str, ...]:
        with self._guard:
            return tuple(sorted(self._projects))

    @contextmanager
    def borrow(self, project_id: str) -> Iterator[ProjectDescriptor]:
        descriptor = self.get(project_id)
        with self._slots:
            with self._guard:
                lock = self._locks.get(project_id)
                if lock is None:
                    raise KeyError(f"unknown project {project_id!r}")
            with lock:
                # Re-resolve to reject removed/replaced roots between registration and use.
                current = Path(descriptor.root).resolve(strict=True)
                if current.as_posix() != descriptor.root:
                    raise RuntimeError("registered project root identity changed")
                yield descriptor
