"""Sanitation controls over one bounded, image-bound local source corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from .json_io import decode_json_object, bounded_json_text
from .numeric_inputs import bounded_json_value, bounded_sequence, bounded_text
from .secret_scanning import (
    _SourceCorpus,
    _scan_corpus,
    _incomplete_scan,
    MAX_CONTROL_BYTES,
    MAX_OUTPUT_BYTES,
    SCAN_EXCLUSIONS,
)

EMAIL_PATTERN = re.compile(
    rb"(?<!\\)\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
SANITATION_MAX_BYTES = 2 * 1024 * 1024 * 1024
MAX_PII_MATCHES = 100000
MAX_LOCAL_FINDINGS = 10000
MAX_EMAIL_TOKEN_BYTES = 4096
MAX_EMAIL_REGEX_WORK = 10000000
_EMAIL_TOKEN = re.compile(rb"[A-Za-z0-9._%+@-]+")


def _gate(
    name: str,
    *,
    status: str,
    tool: str,
    findings: list[dict[str, Any]],
    exclusions: list[str],
    limitations: str,
    corpus_sha256: str | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "tool": tool,
        "corpus": ".",
        "corpus_sha256": corpus_sha256,
        "exclusions": exclusions,
        "limitations": limitations,
        "findings": findings,
        "disposition": "pass" if status == "passed" else "fail",
    }


def _policy(corpus):
    raw = corpus.control("policies/public-data-allowlist.json")
    data = decode_json_object(
        raw, max_bytes=MAX_CONTROL_BYTES, max_depth=32, max_nodes=100000
    )
    required = {
        "approved_public_identifiers",
        "inert_test_domains",
        "technical_uri_tokens",
        "binary_types",
    }
    if (
        not required <= set(data)
        or set(data) - required - {"schema_version"}
        or data.get("schema_version", "1.0") != "1.0"
    ):
        raise ValueError("public-data policy fields are invalid")
    emails = set()
    identities = set()
    for record in bounded_sequence(
        data["approved_public_identifiers"], "public identifiers", maximum=256
    ):
        if (
            type(record) is not dict
            or not {"type", "value"} <= set(record)
            or set(record) - {"type", "value", "owner", "reason"}
        ):
            raise ValueError("public identifier fields are invalid")
        for key, value in record.items():
            bounded_text(value, "public identifier " + key, maximum=4096, strip=False)
        identity = (record["type"], record["value"].casefold())
        if identity in identities:
            raise ValueError("duplicate public identifier")
        identities.add(identity)
        if record["type"] == "email":
            emails.add(record["value"].casefold())

    def labels(key):
        values = [
            bounded_text(v, key, maximum=256, strip=False).casefold()
            for v in bounded_sequence(data[key], key, maximum=256)
        ]
        if len(set(values)) != len(values):
            raise ValueError("duplicate policy label")
        return set(values)

    domains = labels("inert_test_domains")
    technical = labels("technical_uri_tokens")
    binary = data["binary_types"]
    if type(binary) is not dict or len(binary) > 64:
        raise ValueError("binary policy must be a bounded mapping")
    signatures = {}
    for suffix, magic in binary.items():
        bounded_text(suffix, "binary suffix", maximum=32, strip=False)
        bounded_text(magic, "binary signature", maximum=128, strip=False)
        if (
            re.fullmatch(r"\.[A-Za-z0-9]{1,16}", suffix) is None
            or re.fullmatch(r"(?:[0-9a-fA-F]{2}){1,64}", magic) is None
            or suffix.casefold() in signatures
        ):
            raise ValueError("binary signature is invalid or ambiguous")
        signatures[suffix.casefold()] = bytes.fromhex(magic)
    return emails, domains, technical, signatures


def _supplied_metadata(identifier_audit, licensing):
    for data in (identifier_audit, licensing):
        if type(data) is not dict:
            raise ValueError("sanitation inputs must be actual objects")
        bounded_json_value(data)
    gates = identifier_audit.get("gates")
    if type(gates) is not dict or not gates or len(gates) > 32:
        raise ValueError("identifier gates must be a bounded nonempty mapping")
    for name, gate in gates.items():
        bounded_text(name, "gate name", maximum=128, strip=False)
        if (
            type(gate) is not dict
            or type(gate.get("status")) is not str
            or gate["status"] not in {"passed", "failed", "not_run"}
        ):
            raise ValueError("identifier gate shape/status is invalid")
    if (
        "scoped_valid" in identifier_audit
        and type(identifier_audit["scoped_valid"]) is not bool
    ):
        raise ValueError("identifier scoped validity must be an actual boolean")
    if type(licensing.get("valid")) is not bool:
        raise ValueError("licensing validity must be an actual boolean")
    for error in bounded_sequence(
        licensing.get("errors", []), "license errors", maximum=256
    ):
        bounded_text(error, "license error", maximum=4096, strip=False)
    return dict(gates)


def build_sanitation_summary(
    root: Path, identifier_audit: dict[str, Any], licensing: dict[str, Any]
) -> dict[str, Any]:
    base_gates = _supplied_metadata(identifier_audit, licensing)
    excluded = [
        SCAN_EXCLUSIONS,
        "tests/test_sanitation_assurance.py (negative email fixtures only)",
    ]
    pii_findings = []
    binary_findings = []
    try:
        corpus = _SourceCorpus(root, max_bytes=SANITATION_MAX_BYTES)
        allowed_emails, inert_domains, technical_tokens, binary_types = _policy(corpus)
        matched = 0
        output_bytes = 2
        email_work = 0

        def retain(target, record):
            nonlocal output_bytes
            # Each record is small and typed; bound aggregate before retaining it.
            output_bytes += (
                len(bounded_json_text(record, max_bytes=16384).encode("utf-8")) + 2
            )
            if (
                len(pii_findings) + len(binary_findings) >= MAX_LOCAL_FINDINGS
                or output_bytes > MAX_OUTPUT_BYTES
            ):
                raise ValueError("local sanitation finding budget exceeded")
            target.append(record)

        def consume(relative, path, raw, digest):
            nonlocal matched, email_work
            expected_magic = binary_types.get(path.suffix.casefold())
            declared_binary = expected_magic is not None and raw.startswith(
                expected_magic
            )
            nul_bearing = b"\0" in raw[:8192]
            if (
                relative != "tests/test_sanitation_assurance.py"
                and not declared_binary
                and not nul_bearing
            ):
                for token in _EMAIL_TOKEN.finditer(raw):
                    if b"@" not in token.group(0):
                        continue
                    size = token.end() - token.start()
                    email_work += size * size
                    if (
                        size > MAX_EMAIL_TOKEN_BYTES
                        or email_work > MAX_EMAIL_REGEX_WORK
                    ):
                        raise ValueError(
                            "email candidate work budget exceeded before matching"
                        )
                    # A maximal alphabet token contains every possible email match.
                    # pos retains the original preceding byte for escape/boundary checks.
                    for match in EMAIL_PATTERN.finditer(
                        raw, token.start(), token.end()
                    ):
                        matched += 1
                        if matched > MAX_PII_MATCHES:
                            raise ValueError("email match work budget exceeded")
                        value = (
                            match.group(0).decode("ascii", errors="ignore").casefold()
                        )
                        domain = value.rsplit("@", 1)[-1]
                        if re.fullmatch(
                            r"\d+x(?:-\d+)?\.(?:gif|jpe?g|png|svg|webp)", domain
                        ):
                            continue
                        if (
                            value in allowed_emails
                            or domain in inert_domains
                            or value in technical_tokens
                        ):
                            continue
                        retain(
                            pii_findings,
                            {
                                "path": relative,
                                "kind": "email",
                                "offset": match.start(),
                                "value_sha256": hashlib.sha256(
                                    value.encode()
                                ).hexdigest(),
                            },
                        )
            if nul_bearing and not declared_binary:
                retain(
                    binary_findings,
                    {"path": relative, "kind": "undeclared_binary", "sha256": digest},
                )

        secret_scan = _scan_corpus(corpus, consume=consume)
    except (OSError, ValueError) as error:
        secret_scan = _incomplete_scan(error)
        pii_findings = []
        binary_findings = []
    corpus_sha = secret_scan["corpus_sha256"]
    secret_findings = [
        item for item in secret_scan["findings"] if item["kind"] != "generic_secret"
    ]
    credential_findings = [
        item for item in secret_scan["findings"] if item["kind"] == "generic_secret"
    ]
    scanner_errors = secret_scan["errors"]
    complete = secret_scan["complete"]
    for name, findings in [
        ("secret_scanning", secret_findings),
        ("credential_scanning", credential_findings),
    ]:
        failed = (
            not complete
            or scanner_errors
            or any(item["classification"] == "unreviewed" for item in findings)
        )
        base_gates[name] = _gate(
            name,
            status="failed" if failed else "passed",
            tool="runtime.secret_scanning/identity-bound-secret-shapes-v1",
            findings=findings,
            exclusions=excluded,
            limitations="Bounded credential-shape matching over the shared admitted images; reviewed fixture declarations are not authenticated reviewer authority. No entropy, novel-encoding or provider-revocation proof.",
            corpus_sha256=corpus_sha,
        )
    for name, findings, tool, limitation in [
        (
            "pii_review",
            pii_findings,
            "runtime.sanitation_assurance/email-review-v1",
            "Email review with explicit public/inert allowlist; not a general legal PII determination.",
        ),
        (
            "binary_review",
            binary_findings,
            "runtime.sanitation_assurance/binary-magic-v1",
            "NUL-bearing payloads checked against declared extension magic; semantic media review is out of scope.",
        ),
    ]:
        base_gates[name] = _gate(
            name,
            status="failed" if findings or not complete else "passed",
            tool=tool,
            findings=findings,
            exclusions=excluded,
            limitations=limitation,
            corpus_sha256=corpus_sha,
        )
    license_findings = licensing.get("errors", [])
    base_gates["license_provenance_review"] = _gate(
        "license_provenance_review",
        status="failed" if license_findings or not licensing["valid"] else "passed",
        tool="runtime.licensing.validate_licensing",
        findings=[{"error": item} for item in license_findings],
        exclusions=[],
        limitations="Supplied repository licensing result; this compositor does not independently execute or authenticate licensing evidence.",
        corpus_sha256=None,
    )
    errors = [
        name + ": status=" + gate["status"]
        for name, gate in base_gates.items()
        if gate["status"] != "passed"
    ]
    if not complete:
        errors.append("local_source_scan: incomplete")
    result = {
        "schema_version": "1.0",
        "valid": not errors,
        "complete": complete,
        "corpus_sha256": corpus_sha,
        "file_count": secret_scan["file_count"],
        "gates": base_gates,
        "errors": errors,
        "scan_errors": scanner_errors,
        "review_registry_sha256": secret_scan["review_registry_sha256"],
        "scope": "Local secret/credential/email/binary controls share the measured corpus. Supplied identifier/license gates retain their separate declared provenance.",
    }
    bounded_json_text(result, max_bytes=MAX_OUTPUT_BYTES)
    return result
