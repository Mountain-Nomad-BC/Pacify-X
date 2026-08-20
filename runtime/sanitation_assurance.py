"""Independent, bounded sanitation controls with honest per-gate evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .bounded_walk import WalkLimits, bounded_walk
from .secret_scanning import scan_secret_shapes


EMAIL_PATTERN = re.compile(
    rb"(?<!\\)\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
SANITATION_MAX_BYTES = 2 * 1024 * 1024 * 1024
EXCLUDED_TREE_NAMES = {
    ".engineering-bootstrap",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode-test",
    "PortableGit",
    "Python",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
EXCLUDED_CUSTODY_PREFIXES = (
    ".px/preserved-extension-installations",
    ".px/preserved-skills",
)


def _gate(
    name: str,
    *,
    status: str,
    tool: str,
    findings: list[dict[str, Any]],
    exclusions: list[str],
    limitations: str,
    corpus_sha256: str,
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


def build_sanitation_summary(
    root: Path,
    identifier_audit: dict[str, Any],
    licensing: dict[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    policy_path = root / "policies/public-data-allowlist.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    negative_fixture_paths = {"tests/test_sanitation_assurance.py"}
    excluded = [
        ".git/",
        ".engineering-bootstrap/ (generated control state)",
        ".venv*/ (generated Python environments)",
        "PortableGit/, Python/, build/, dist/, node_modules/ (generated or dependency stores)",
        "evidence/bundles/",
        ".px/preserved-extension-installations/ (preserved user custody)",
        ".px/preserved-skills/ (preserved user custody)",
        "tests/test_sanitation_assurance.py (deliberate negative scanner fixtures only)",
    ]
    walk = bounded_walk(
        root,
        limits=WalkLimits(
            max_files=30_000,
            max_depth=80,
            max_bytes=SANITATION_MAX_BYTES,
        ),
        symlink_policy="reject",
        exclude=lambda relative: (
            relative == ".git"
            or relative.startswith(".git/")
            or relative == "evidence/bundles"
            or relative.startswith("evidence/bundles/")
            or any(
                part in EXCLUDED_TREE_NAMES or part.startswith(".venv")
                for part in relative.split("/")
            )
            or any(
                relative == prefix or relative.startswith(prefix + "/")
                for prefix in EXCLUDED_CUSTODY_PREFIXES
            )
        ),
    )
    records: list[tuple[str, int, str]] = []
    pii_findings: list[dict[str, Any]] = []
    binary_findings: list[dict[str, Any]] = []
    allowed_emails = {
        str(item["value"]).casefold()
        for item in policy.get("approved_public_identifiers", [])
        if item.get("type") == "email"
    }
    inert_domains = {
        str(item).casefold() for item in policy.get("inert_test_domains", [])
    }
    technical_tokens = {
        str(item).casefold() for item in policy.get("technical_uri_tokens", [])
    }
    binary_types = {
        str(key).casefold(): bytes.fromhex(str(value))
        for key, value in policy.get("binary_types", {}).items()
    }
    for entry in walk.files:
        data = entry.path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        records.append((entry.relative, len(data), digest))
        expected_magic = binary_types.get(entry.path.suffix.casefold())
        declared_binary = expected_magic is not None and data.startswith(
            expected_magic
        )
        nul_bearing = b"\x00" in data[:8192]
        # Pattern matching compressed/archive bytes creates random false PII
        # positives.  Classify admitted binary formats first; unknown binary
        # payloads remain fail-closed under the binary review below.
        if (
            entry.relative not in negative_fixture_paths
            and not declared_binary
            and not nul_bearing
        ):
            for match in EMAIL_PATTERN.finditer(data):
                value = match.group(0).decode("ascii", errors="ignore").casefold()
                domain = value.rsplit("@", 1)[-1]
                if re.fullmatch(r"\d+x(?:-\d+)?\.(?:gif|jpe?g|png|svg|webp)", domain):
                    continue
                if (
                    value in allowed_emails
                    or domain in inert_domains
                    or value in technical_tokens
                ):
                    continue
                pii_findings.append(
                    {
                        "path": entry.relative,
                        "kind": "email",
                        "offset": match.start(),
                        "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
                    }
                )
        if nul_bearing:
            if not declared_binary:
                binary_findings.append(
                    {
                        "path": entry.relative,
                        "kind": "undeclared_binary",
                        "sha256": digest,
                    }
                )
    corpus_sha = hashlib.sha256(
        json.dumps(records, separators=(",", ":")).encode()
    ).hexdigest()
    base_gates = dict(identifier_audit.get("gates", {}))
    secret_scan = scan_secret_shapes(root)
    secret_findings = [
        item for item in secret_scan["findings"] if item["kind"] != "generic_secret"
    ]
    credential_findings = [
        item for item in secret_scan["findings"] if item["kind"] == "generic_secret"
    ]
    secret_unreviewed = [
        item for item in secret_findings if item.get("classification") == "unreviewed"
    ]
    credential_unreviewed = [
        item
        for item in credential_findings
        if item.get("classification") == "unreviewed"
    ]
    scanner_errors = list(secret_scan["errors"])
    base_gates["secret_scanning"] = _gate(
        "secret_scanning",
        status="failed" if secret_unreviewed or scanner_errors else "passed",
        tool="runtime.secret_scanning/identity-bound-secret-shapes-v1",
        findings=secret_findings,
        exclusions=excluded,
        limitations="Credential-shape matching with reviewed synthetic fixtures; not entropy analysis or provider-side revocation verification.",
        corpus_sha256=corpus_sha,
    )
    base_gates["credential_scanning"] = _gate(
        "credential_scanning",
        status="failed" if credential_unreviewed or scanner_errors else "passed",
        tool="runtime.secret_scanning/identity-bound-secret-shapes-v1",
        findings=credential_findings,
        exclusions=excluded,
        limitations="Credential-shaped assignments only; cannot prove absence of novel encodings.",
        corpus_sha256=corpus_sha,
    )
    base_gates["pii_review"] = _gate(
        "pii_review",
        status="failed" if pii_findings else "passed",
        tool="runtime.sanitation_assurance/email-review-v1",
        findings=pii_findings,
        exclusions=excluded,
        limitations="Email review with explicit public/inert allowlist; not a general legal PII determination.",
        corpus_sha256=corpus_sha,
    )
    base_gates["binary_review"] = _gate(
        "binary_review",
        status="failed" if binary_findings else "passed",
        tool="runtime.sanitation_assurance/binary-magic-v1",
        findings=binary_findings,
        exclusions=excluded,
        limitations="NUL-bearing payloads are checked against explicit extension magic; semantic media review is out of scope.",
        corpus_sha256=corpus_sha,
    )
    license_findings = list(licensing.get("errors", []))
    base_gates["license_provenance_review"] = _gate(
        "license_provenance_review",
        status="failed" if license_findings or not licensing.get("valid") else "passed",
        tool="runtime.licensing.validate_licensing",
        findings=[{"error": item} for item in license_findings],
        exclusions=[],
        limitations="Checks declared repository licensing and owned package metadata; not independent legal advice.",
        corpus_sha256=corpus_sha,
    )
    errors = [
        name for name, gate in base_gates.items() if gate.get("status") != "passed"
    ]
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "corpus_sha256": corpus_sha,
        "file_count": walk.file_count,
        "gates": base_gates,
        "errors": [
            f"{name}: status={base_gates[name].get('status')}" for name in errors
        ],
    }
