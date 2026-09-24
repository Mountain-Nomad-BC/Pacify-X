from datetime import datetime, timedelta, timezone
from runtime.semantic_authorization import authorize
from runtime.semantic_integration_types import QueryAuthorization

def test_authorization_fails_closed_for_write_and_expiry():
    now = datetime.now(timezone.utc)
    auth = QueryAuthorization("t", "a", ("p",), ("semantic.symbol.find", "semantic.edit.apply"), now + timedelta(seconds=30))
    assert authorize(auth, "p", "semantic.symbol.find", now=now).allowed
    assert not authorize(auth, "p", "semantic.edit.apply", now=now).allowed
    assert not authorize(auth, "p", "semantic.symbol.find", now=now + timedelta(minutes=1)).allowed

import pytest


def test_authorization_contract_rejects_naive_expiry_and_duplicate_scope():
    with pytest.raises(ValueError, match="timezone-aware"):
        QueryAuthorization("t", "a", ("p",), ("semantic.symbol.find",), datetime(2026, 9, 20))
    with pytest.raises(ValueError, match="unique"):
        QueryAuthorization("t", "a", ("p", "p"), ("semantic.symbol.find",))
