"""Evidence-preserving deterministic reduction verifier.

A model/extractor may propose a compact receipt.  PX verifies exact quotations,
source identity, exit status and actual size reduction before allowing the
receipt to replace a large observation in context.  Failure returns raw evidence.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, re
from typing import Callable, Mapping, Sequence

SCHEMA_VERSION = "px.evidence-reduction/1.0"
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)

def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def _hash_bytes(value: bytes) -> str: return hashlib.sha256(value).hexdigest()

def suspected_secret(text: str) -> bool: return any(p.search(text) for p in SECRET_PATTERNS)

@dataclass(frozen=True, slots=True)
class ReductionOutcome:
    mode: str
    projected_text: str
    receipt: Mapping[str, object] | None
    reason: str


def verify_candidate_receipt(*, source_text: str, exit_status: int, source_locator: str, candidate: Mapping[str, object], max_quotes: int = 32, max_summary_chars: int = 4096) -> dict[str, object]:
    if type(source_text) is not str or type(exit_status) is not int or isinstance(exit_status, bool):
        raise ValueError("source text and integer exit status are required")
    if type(source_locator) is not str or not source_locator.strip() or len(source_locator) > 1024:
        raise ValueError("source locator must be bounded text")
    if type(max_quotes) is not int or not 1 <= max_quotes <= 128 or type(max_summary_chars) is not int or not 1 <= max_summary_chars <= 16384:
        raise ValueError("reduction policy bounds are invalid")
    source_bytes = source_text.encode("utf-8"); source_sha = _hash_bytes(source_bytes); errors: list[str] = []
    if candidate.get("schema_version") != SCHEMA_VERSION: errors.append("schema_version")
    if candidate.get("source_sha256") != source_sha: errors.append("source_sha256")
    if candidate.get("source_locator") != source_locator: errors.append("source_locator")
    if type(candidate.get("exit_status")) is not int or candidate.get("exit_status") != exit_status: errors.append("exit_status")
    summary = candidate.get("summary")
    if type(summary) is not str or not summary.strip() or len(summary) > max_summary_chars: errors.append("summary"); summary = ""
    quotes = candidate.get("exact_quotes")
    if not isinstance(quotes, list) or not quotes: errors.append("exact_quotes"); quotes = []
    if len(quotes) > max_quotes: errors.append("too_many_quotes")
    clean_quotes: list[str] = []
    for index, quote in enumerate(quotes):
        if type(quote) is not str or not quote or quote not in source_text: errors.append(f"quote_{index}_not_exact")
        else: clean_quotes.append(quote)
    labels = candidate.get("finding_labels", [])
    if not isinstance(labels, list) or any(type(x) is not str or not x.strip() or len(x) > 128 for x in labels): errors.append("finding_labels"); labels = []
    core = {
        "schema_version": SCHEMA_VERSION, "source_sha256": source_sha, "source_locator": source_locator,
        "exit_status": exit_status, "summary": summary.strip(), "exact_quotes": clean_quotes,
        "finding_labels": sorted(set(labels)), "source_bytes": len(source_bytes),
        "authority_granted": False,
    }
    # Compute the exact serialized receipt size with a fixed-width placeholder hash.
    # receipt_bytes is self-describing, so converge the decimal-width field first.
    receipt_bytes = 0
    provisional_errors = sorted(set(errors))
    for _ in range(8):
        body = {**core, "receipt_bytes": receipt_bytes, "verified": not provisional_errors, "verification_errors": provisional_errors}
        candidate_bytes = len(_canonical({**body, "receipt_sha256": "0" * 64}).encode("utf-8"))
        if candidate_bytes == receipt_bytes:
            break
        receipt_bytes = candidate_bytes
    if receipt_bytes >= len(source_bytes):
        errors.append("no_size_reduction")
    final_errors = sorted(set(errors))
    for _ in range(8):
        body = {**core, "receipt_bytes": receipt_bytes, "verified": not final_errors, "verification_errors": final_errors}
        candidate_bytes = len(_canonical({**body, "receipt_sha256": "0" * 64}).encode("utf-8"))
        if candidate_bytes == receipt_bytes:
            break
        receipt_bytes = candidate_bytes
    body = {**core, "receipt_bytes": receipt_bytes, "verified": not final_errors, "verification_errors": final_errors}
    result = {**body, "receipt_sha256": _hash_bytes(_canonical(body).encode("utf-8"))}
    if len(_canonical(result).encode("utf-8")) != receipt_bytes:
        raise RuntimeError("evidence receipt size did not converge")
    return result


def validate_verified_receipt(receipt: Mapping[str, object]) -> None:
    if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("verified") is not True or receipt.get("authority_granted") is not False:
        raise ValueError("evidence-reduction receipt is not verified")
    body = {str(k): v for k, v in receipt.items() if k != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash_bytes(_canonical(body).encode("utf-8")):
        raise ValueError("evidence-reduction receipt hash mismatch")
    if receipt.get("verification_errors") != []:
        raise ValueError("verified evidence-reduction receipt contains errors")
    if type(receipt.get("receipt_bytes")) is not int or receipt.get("receipt_bytes") != len(_canonical(dict(receipt)).encode("utf-8")):
        raise ValueError("evidence-reduction receipt byte count mismatch")


def reduce_evidence(source_text: str, *, exit_status: int, source_locator: str, extractor: Callable[[str, int, str, str], Mapping[str, object]], minimum_bytes: int = 4096) -> ReductionOutcome:
    if type(minimum_bytes) is not int or isinstance(minimum_bytes, bool) or minimum_bytes < 256:
        raise ValueError("minimum_bytes is invalid")
    raw = source_text.encode("utf-8")
    if len(raw) < minimum_bytes: return ReductionOutcome("raw", source_text, None, "below_threshold")
    if suspected_secret(source_text): return ReductionOutcome("raw", source_text, None, "suspected_secret")
    digest = _hash_bytes(raw)
    candidate = extractor(source_text, exit_status, digest, source_locator)
    receipt = verify_candidate_receipt(source_text=source_text, exit_status=exit_status, source_locator=source_locator, candidate=candidate)
    if receipt["verified"] is not True:
        return ReductionOutcome("raw", source_text, receipt, "verification_failed:" + ",".join(receipt["verification_errors"]))
    return ReductionOutcome("verified_receipt", _canonical(receipt), receipt, "verified")
