from __future__ import annotations

import pytest

from runtime.session_context_guard import SessionContextGuard, SessionContextVersion

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64


def test_stale_async_commit_is_denied_after_context_advance() -> None:
    current = SessionContextGuard.create(topic_key="retrieval", user_scope="user:a", role_scope="operator", context_signature=H1, fabric_generation=H2, retrieval_generation=H3)
    old = current.token
    advanced = SessionContextGuard.advance(current, expected_token=old, context_signature=H4)
    assert advanced.entry_version == 1
    assert not SessionContextGuard.can_commit(old, advanced)
    assert SessionContextGuard.can_commit(advanced.token, advanced)


def test_advance_requires_current_token() -> None:
    current = SessionContextGuard.create(topic_key="x", user_scope="u", role_scope="r", context_signature=H1, fabric_generation=H2, retrieval_generation=H3)
    with pytest.raises(ValueError, match="stale session context"):
        SessionContextGuard.advance(current, expected_token="f" * 64, topic_key="y")


def test_cache_compatibility_binds_model_and_retrieval_generations() -> None:
    first = SessionContextVersion(0, "x", "u", "r", H1, H2, H3)
    second = SessionContextVersion(1, "x", "u", "r", H1, H4, H3)
    assert SessionContextGuard.cache_compatible(first, second) == (False, "fabric_generation_mismatch")


def test_context_hash_fields_are_strict() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        SessionContextGuard.create(topic_key="x", user_scope="u", role_scope="r", context_signature="nope", fabric_generation=H2, retrieval_generation=H3)
