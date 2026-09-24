"""Optimistic session/context version tokens for rejecting stale async commits."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Mapping

_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_FIELD_BYTES = 4096


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _text(value: object, label: str, *, required: bool = True) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{label} must not be empty")
    if len(text.encode("utf-8")) > _MAX_FIELD_BYTES:
        raise ValueError(f"{label} exceeds byte budget")
    return text


def _generation(value: object, label: str) -> str:
    text = _text(value, label)
    if not _SHA.fullmatch(text):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return text


@dataclass(frozen=True, slots=True)
class SessionContextVersion:
    entry_version: int
    topic_key: str
    user_scope: str
    role_scope: str
    context_signature: str
    fabric_generation: str
    retrieval_generation: str

    def __post_init__(self) -> None:
        if type(self.entry_version) is not int or self.entry_version < 0:
            raise ValueError("entry_version must be a nonnegative integer")
        _text(self.topic_key, "topic_key")
        _text(self.user_scope, "user_scope")
        _text(self.role_scope, "role_scope")
        _generation(self.context_signature, "context_signature")
        _generation(self.fabric_generation, "fabric_generation")
        _generation(self.retrieval_generation, "retrieval_generation")

    @property
    def token(self) -> str:
        return _sha(asdict(self))


@dataclass(frozen=True, slots=True)
class CommitGuardDecision:
    allowed: bool
    reason: str
    expected_token: str
    current_token: str
    current_version: int


class SessionContextGuard:
    """Version-token helper only; it stores no conversation or memory content."""

    @staticmethod
    def create(*, topic_key: str, user_scope: str, role_scope: str, context_signature: str, fabric_generation: str, retrieval_generation: str) -> SessionContextVersion:
        return SessionContextVersion(0, topic_key, user_scope, role_scope, context_signature, fabric_generation, retrieval_generation)

    @staticmethod
    def advance(current: SessionContextVersion, *, expected_token: str, **changes: str) -> SessionContextVersion:
        if type(current) is not SessionContextVersion:
            raise ValueError("typed SessionContextVersion required")
        decision = SessionContextGuard.commit_decision(expected_token, current)
        if not decision.allowed:
            raise ValueError("stale session context token")
        allowed = {"topic_key", "user_scope", "role_scope", "context_signature", "fabric_generation", "retrieval_generation"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown session-context fields: {sorted(unknown)}")
        return replace(current, entry_version=current.entry_version + 1, **changes)

    @staticmethod
    def commit_decision(expected_token: str, current: SessionContextVersion) -> CommitGuardDecision:
        if type(expected_token) is not str or not _SHA.fullmatch(expected_token):
            raise ValueError("expected_token must be a lowercase SHA-256")
        if type(current) is not SessionContextVersion:
            raise ValueError("typed SessionContextVersion required")
        token = current.token
        return CommitGuardDecision(expected_token == token, "current_context" if expected_token == token else "stale_context", expected_token, token, current.entry_version)

    @staticmethod
    def can_commit(expected_token: str, current: SessionContextVersion) -> bool:
        return SessionContextGuard.commit_decision(expected_token, current).allowed

    @staticmethod
    def cache_compatible(cached: SessionContextVersion, current: SessionContextVersion) -> tuple[bool, str]:
        if type(cached) is not SessionContextVersion or type(current) is not SessionContextVersion:
            raise ValueError("typed SessionContextVersion records required")
        for field in ("user_scope", "role_scope", "context_signature", "fabric_generation", "retrieval_generation"):
            if getattr(cached, field) != getattr(current, field):
                return False, f"{field}_mismatch"
        if cached.topic_key != current.topic_key:
            return False, "topic_changed"
        return True, "compatible"
