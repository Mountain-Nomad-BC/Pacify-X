"""Exact-generation temporary exceptions expire mechanically, never grant effects."""
from datetime import datetime, timezone

from .generation_bound_verdict import digest, sha256_text, validate_record


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("aware UTC timestamp required")
    return parsed


def create_exception(*, exception_id, scope, owner, reason, generation_sha256, evidence_sha256,
                     expires_utc, supersession_condition):
    sha256_text(generation_sha256)
    sha256_text(evidence_sha256)
    for value in (exception_id, scope, owner, reason, supersession_condition):
        if type(value) is not str or not value.strip() or len(value) > 512:
            raise ValueError("exception identity scope owner reason and supersession condition required")
    timestamp(expires_utc)
    body = dict(schema_version="px.governed-exception/1.0", exception_id=exception_id, scope=scope,
                owner=owner, reason=reason, generation_sha256=generation_sha256, evidence_sha256=evidence_sha256,
                expires_utc=expires_utc, supersession_condition=supersession_condition, authority_granted=False)
    return validate_record({**body, "exception_sha256": digest(body)}, "governed-exception")


def exception_is_active(record, *, scope, generation_sha256, now, superseded_ids=()):
    try:
        values = {k: v for k, v in record.items() if k not in {"schema_version", "exception_sha256", "authority_granted"}}
        rebuilt = create_exception(**values)
        return (rebuilt == record and record["scope"] == scope and record["generation_sha256"] == generation_sha256
                and record["exception_id"] not in superseded_ids and timestamp(now) < timestamp(record["expires_utc"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
