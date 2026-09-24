"""Bounded lifecycle ownership for project semantic sessions."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import RLock

from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_paths import canonical_project_root
from .semantic_code_project import SemanticProjectSession
from .semantic_code_registry import SemanticBackendRegistry


class SemanticSessionManager:
    def __init__(self, *, max_sessions: int = 8):
        if type(max_sessions) is not int or not 1 <= max_sessions <= 128:
            raise ValueError("max_sessions must be between 1 and 128")
        self.max_sessions = max_sessions
        self._lock = RLock()
        self._sessions: OrderedDict[str, SemanticProjectSession] = OrderedDict()

    def open(
        self,
        root: Path,
        *,
        registry: SemanticBackendRegistry | None = None,
        limits: SemanticCodeLimits = SemanticCodeLimits(),
        read_only: bool = True,
    ) -> SemanticProjectSession:
        canonical = canonical_project_root(root)
        key = canonical.as_posix()
        with self._lock:
            existing = self._sessions.get(key)
            if existing is not None:
                if existing.read_only != bool(read_only):
                    raise ValueError("semantic session already exists with different write authority")
                if existing.limits != limits:
                    raise ValueError("semantic session already exists with different resource limits")
                if registry is not None and existing.registry is not registry:
                    raise ValueError("semantic session already exists with a different backend registry")
                self._sessions.move_to_end(key)
                return existing
            session = SemanticProjectSession(
                canonical,
                registry=registry,
                limits=limits,
                read_only=read_only,
            )
            self._sessions[key] = session
            while len(self._sessions) > self.max_sessions:
                _, evicted = self._sessions.popitem(last=False)
                evicted.close()
            return session

    def close(self, root: Path) -> bool:
        key = canonical_project_root(root).as_posix()
        with self._lock:
            session = self._sessions.pop(key, None)
        if session is None:
            return False
        session.close()
        return True

    def close_all(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

    def active_projects(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._sessions.keys())
