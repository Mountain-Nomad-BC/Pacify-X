from __future__ import annotations
import pytest
from runtime.evidence_reducer import reduce_evidence, verify_candidate_receipt, validate_verified_receipt


def source():
    return ("prefix important failure line suffix\n" * 300)


def candidate(text, status, digest, locator):
    return {"schema_version":"px.evidence-reduction/1.0", "source_sha256":digest, "source_locator":locator, "exit_status":status, "summary":"failure preserved", "exact_quotes":["important failure line"], "finding_labels":["failure"]}


def test_verified_reduction_is_deterministic_and_source_bound():
    text=source(); one=verify_candidate_receipt(source_text=text, exit_status=1, source_locator="log:1", candidate=candidate(text,1,__import__('hashlib').sha256(text.encode()).hexdigest(),"log:1"))
    two=verify_candidate_receipt(source_text=text, exit_status=1, source_locator="log:1", candidate=candidate(text,1,__import__('hashlib').sha256(text.encode()).hexdigest(),"log:1"))
    assert one == two and one["verified"] is True
    validate_verified_receipt(one)


def test_non_exact_quote_or_wrong_source_falls_back_to_raw():
    text=source()
    def bad(t,s,d,l):
        row=candidate(t,s,d,l); row["exact_quotes"]=["invented quote"]; return row
    out=reduce_evidence(text, exit_status=2, source_locator="log:2", extractor=bad, minimum_bytes=256)
    assert out.mode == "raw" and "quote_0_not_exact" in out.reason


def test_secret_like_output_is_never_sent_to_reducer():
    called=False
    def extractor(*args):
        nonlocal called; called=True; return {}
    text=("token=super-secret-value\n"*500)
    out=reduce_evidence(text, exit_status=0, source_locator="log:s", extractor=extractor, minimum_bytes=256)
    assert out.mode == "raw" and out.reason == "suspected_secret" and called is False


def test_receipt_larger_than_source_is_not_accepted():
    text="x"*300
    digest=__import__('hashlib').sha256(text.encode()).hexdigest()
    row={"schema_version":"px.evidence-reduction/1.0","source_sha256":digest,"source_locator":"x","exit_status":0,"summary":"s"*250,"exact_quotes":["x"],"finding_labels":[]}
    receipt=verify_candidate_receipt(source_text=text, exit_status=0, source_locator="x", candidate=row)
    assert receipt["verified"] is False and "no_size_reduction" in receipt["verification_errors"]

def test_receipt_byte_count_matches_actual_canonical_receipt():
    import json, hashlib
    text=source(); digest=hashlib.sha256(text.encode()).hexdigest()
    receipt=verify_candidate_receipt(source_text=text, exit_status=0, source_locator="log:bytes", candidate=candidate(text,0,digest,"log:bytes"))
    rendered=json.dumps(receipt,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    assert receipt["receipt_bytes"] == len(rendered)
