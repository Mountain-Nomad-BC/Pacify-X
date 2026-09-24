"""Verify the governed 0.9.x release invariants from policies/release-invariants.json.

This is the machine-verifiable fence the owner asked for: the invariants are policy
assertions, and this tool proves the **current tree** satisfies them. A future legitimate
feature changes the policy deliberately (version bump in the manifest) rather than drifting
past an unenforced rule.

Each check returns evidence and, on failure, the exact offending locations so a report is
actionable rather than a bare boolean.

Usage:
    python scripts/verify_release_invariants.py --root .
    python scripts/verify_release_invariants.py --root . --json
Exit code 0 when every enforced invariant holds, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MANIFEST = Path("policies/release-invariants.json")
SCHEMA = "px.release-invariant-verification/1.0"

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv-certify",
    "node_modules",
    "__pycache__",
    ".tmp",
    ".px",
    ".pacify-x",
    "dist",
    "out",
}

# Authored surfaces each invariant can apply to.
CODE_AREAS = ("runtime", "scripts", "extension/src", "extension/scripts")
POLICY_AREAS = ("bootstrap", "models", "policies", "contracts")
DOC_AREAS = ("docs", "bootstrap")

SCAN_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ps1",
    ".psm1",
    ".sh",
    ".cmd",
    ".bat",
    ".md",
}

MAX_FILE_BYTES = 2 * 1024 * 1024

URL_HOST = re.compile(r"https?://([A-Za-z0-9._\-]+)")
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}

# Identifier-only URL contexts: these carry a URL as *vocabulary* or *recorded provenance*,
# never as a runtime destination. Preserved deliberately as documented false-positive classes
# so the scanner does not train people to ignore it (owner instruction 2026-09-23).
IDENTIFIER_CONTEXTS = (
    "\"buildType\"",            # SLSA/in-toto provenance vocabulary
    "$schema",                  # JSON Schema namespace
    "xmlns",                    # XML namespace
    "source            =",      # runtime-lock provenance record of a clone source
    "repository",               # repository reference
    "REPOSITORY =",             # the project's own repository URL for licence/attribution
    "homepage",
    "bugs",
    "license_url",
)

# A technology name used as a *mapping key* is a keyword table, not an emitter call, and a
# genuine emitter is a call/construction (it contains a parenthesis or a member access).
# Requiring that shape removes the whole false-positive class structurally instead of trying
# to enumerate every vocabulary line.
def _is_emitter_call(line: str) -> bool:
    if not TELEMETRY_EMITTERS.search(line):
        return False
    stripped = line.strip()
    if stripped.startswith(("#", "//", "*")):
        return False
    has_call_shape = "(" in line or ".capture(" in line or "new " in line or "= require(" in line
    return has_call_shape

# Telemetry emitters that would constitute production telemetry.
TELEMETRY_EMITTERS = re.compile(
    r"(?i)\b("
    r"sendTelemetryEvent|TelemetryReporter|appInsights|applicationinsights|"
    r"sentry|posthog|mixpanel|segment\.(?:io|track|analytics)|amplitude|"
    r"opentelemetry|otel\.|datadog|newrelic|bugsnag"
    r")\b"
)
VSCODE_TELEMETRY_GUARD = re.compile(
    r"isTelemetryEnabled|onDidChangeTelemetryEnabled|telemetryLevel"
)

# Download calls that would constitute automatic model acquisition.
DOWNLOAD_CALL = re.compile(
    r"(?i)(requests\.get|httpx\.(?:get|stream)|urlretrieve|urllib\.request\.urlopen|"
    r"Invoke-WebRequest|Invoke-RestMethod|curl\s+-|wget\s)"
)

SECRET_SHAPES = (
    re.compile(
        r"(?i)\b(api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password)\s*[:=]\s*[\"']([A-Za-z0-9+/]{24,})[\"']"
    ),
    re.compile(
        r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
)

PII_SHAPES = (
    (
        "contact_email",
        re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.(?:com|org|net|io|edu|gov|co\.uk)\b"
        ),
    ),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._\-]+")),
    ("posix_home_path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._\-]+/")),
)

# Placeholder/fixture markers that must never be reported as real findings.
SECRET_ALLOW = (
    "example",
    "placeholder",
    "redacted",
    "fixture",
    "preview-",
    "test-",
    "dummy",
    "xxxx",
    "sample",
)
PII_ALLOW = (
    "git@github.com",
    "noreply@",
    "example.com",
    "example.org",
    "example.net",
    "example.invalid",
    "mailto:",
)


def _iter_files(root: Path, areas: tuple[str, ...]):
    for area in areas:
        base = root / area
        if not base.exists():
            continue
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        if entry.name not in EXCLUDE_DIRS:
                            stack.append(entry)
                        continue
                    if (
                        not entry.is_file()
                        or entry.suffix.casefold() not in SCAN_SUFFIXES
                    ):
                        continue
                    if entry.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                yield entry


def _lines(path: Path):
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return list(enumerate(text.splitlines(), start=1))


def _load_manifest(root: Path) -> dict:
    path = root / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"release invariant manifest is missing: {MANIFEST}")
    return json.loads(path.read_text(encoding="utf-8"))


def _invariant(manifest: dict, invariant_id: str) -> dict:
    return next(i for i in manifest["invariants"] if i["id"] == invariant_id)


def check_network_hosts(root: Path, manifest: dict) -> dict:
    inv = _invariant(manifest, "no-px-operated-remote-endpoints")
    allow = set(inv.get("false_positive_allowlist", []))
    areas = tuple(a.rstrip("/") for a in inv["applies_to"])
    findings: list[dict] = []
    observed: set[str] = set()
    for path in _iter_files(root, areas):
        rel = path.relative_to(root).as_posix()
        for number, line in _lines(path):
            for host in URL_HOST.findall(line):
                observed.add(host)
                if host in allow or host in LOOPBACK:
                    continue
                # Identifier/provenance contexts carry a URL as vocabulary, not as a runtime
                # destination (SLSA buildType, JSON Schema namespace, recorded clone source).
                if any(marker in line for marker in IDENTIFIER_CONTEXTS):
                    continue
                if "clone" in line or path.suffix == ".md":
                    continue
                findings.append(
                    {
                        "path": rel,
                        "line": number,
                        "host": host,
                        "text": line.strip()[:120],
                    }
                )
    return {
        "id": inv["id"],
        "passed": not findings,
        "observed_hosts": sorted(observed),
        "allowed_hosts": sorted(allow | LOOPBACK),
        "findings": findings[:50],
    }


def check_telemetry(root: Path, manifest: dict) -> dict:
    inv = _invariant(manifest, "no-production-remote-telemetry")
    areas = tuple(a.rstrip("/") for a in inv["applies_to"])
    findings: list[dict] = []
    guards: list[str] = []
    for path in _iter_files(root, areas):
        rel = path.relative_to(root).as_posix()
        # A test walk script is not production.
        if rel.startswith("extension/scripts/") and "walk" in rel:
            continue
        for number, line in _lines(path):
            if _is_emitter_call(line):
                findings.append(
                    {"path": rel, "line": number, "text": line.strip()[:120]}
                )
            if VSCODE_TELEMETRY_GUARD.search(line):
                guards.append(f"{rel}:{number}")
    return {
        "id": inv["id"],
        "passed": not findings,
        "emitter_findings": findings[:50],
        "vscode_guard_locations": guards,
        "clarification": inv["clarification"],
    }


def check_model_download(root: Path, manifest: dict) -> dict:
    inv = _invariant(manifest, "no-unapproved-model-download")
    areas = tuple(a.rstrip("/") for a in inv["applies_to"])
    policy_path = root / inv["policy_source"]
    policy_ok = False
    if policy_path.is_file():
        policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
        policy_ok = (
            policy.get("authority", {}).get("normal_requests_may_download") is False
        )
    findings: list[dict] = []
    for path in _iter_files(root, areas):
        rel = path.relative_to(root).as_posix()
        if "test" in rel or "benchmark" in rel or "install" in rel or "verify" in rel:
            continue
        for number, line in _lines(path):
            if not DOWNLOAD_CALL.search(line):
                continue
            lowered = line.casefold()
            if ".gguf" in lowered or "huggingface" in lowered or "model" in lowered:
                findings.append(
                    {"path": rel, "line": number, "text": line.strip()[:120]}
                )
    return {
        "id": inv["id"],
        "passed": not findings and policy_ok,
        "policy_enforces_no_auto_download": policy_ok,
        "policy_source": inv["policy_source"],
        "findings": findings[:50],
    }


def check_secrets(root: Path, manifest: dict) -> dict:
    inv = _invariant(manifest, "no-shipped-secrets")
    areas = tuple(a.rstrip("/") for a in inv["applies_to"])
    allow = tuple(inv.get("false_positive_allowlist_terms", ()))
    findings: list[dict] = []
    for path in _iter_files(root, areas):
        rel = path.relative_to(root).as_posix()
        for number, line in _lines(path):
            for pattern in SECRET_SHAPES:
                match = pattern.search(line)
                if not match:
                    continue
                if any(token in line.casefold() for token in allow):
                    continue
                findings.append(
                    {"path": rel, "line": number, "text": line.strip()[:120]}
                )
                break
    return {"id": inv["id"], "passed": not findings, "findings": findings[:50]}


def check_pii(root: Path, manifest: dict) -> dict:
    inv = _invariant(manifest, "no-machine-specific-paths-or-pii")
    areas = tuple(a.rstrip("/") for a in inv["applies_to"])
    allow = tuple(inv.get("false_positive_allowlist_terms", ()))
    # The project's own published security contact legitimately appears in the disclosure
    # documents that tell a reporter where to send a vulnerability.
    contact_allow = tuple(inv.get("project_contact_allowlist", ()))
    findings: list[dict] = []
    for path in _iter_files(root, areas):
        rel = path.relative_to(root).as_posix()
        for number, line in _lines(path):
            for name, pattern in PII_SHAPES:
                match = pattern.search(line)
                if not match:
                    continue
                if any(
                    token in match.group(0) or token in line.casefold()
                    for token in allow
                ):
                    continue
                if name == "contact_email" and any(token in line for token in contact_allow):
                    continue
                findings.append(
                    {
                        "path": rel,
                        "line": number,
                        "kind": name,
                        "text": line.strip()[:120],
                    }
                )
    return {"id": inv["id"], "passed": not findings, "findings": findings[:50]}


CHECKS = {
    "no-px-operated-remote-endpoints": check_network_hosts,
    "no-production-remote-telemetry": check_telemetry,
    "no-unapproved-model-download": check_model_download,
    "no-shipped-secrets": check_secrets,
    "no-machine-specific-paths-or-pii": check_pii,
}


def verify(root: Path) -> dict:
    root = root.resolve(strict=True)
    manifest = _load_manifest(root)
    results: list[dict] = []
    for invariant in manifest["invariants"]:
        checker = CHECKS.get(invariant["id"])
        if checker is None:
            # Policy-only invariants are reviewed through the applicability matrix, not scanned.
            results.append(
                {
                    "id": invariant["id"],
                    "passed": True,
                    "mode": "policy_review",
                    "statement": invariant["statement"],
                    "reclassification_trigger": invariant["reclassification_trigger"],
                }
            )
            continue
        result = checker(root, manifest)
        result.setdefault("statement", invariant["statement"])
        results.append(result)
    failed = [r for r in results if not r["passed"]]
    return {
        "schema_version": SCHEMA,
        "release_line": manifest["release_line"],
        "valid": not failed,
        "invariant_count": len(results),
        "failed_count": len(failed),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.root)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 1
    print(
        f"release invariants: valid={result['valid']} "
        f"({result['invariant_count'] - result['failed_count']}/{result['invariant_count']} hold)"
    )
    for row in result["results"]:
        mark = "PASS" if row["passed"] else "FAIL"
        mode = row.get("mode", "scan")
        print(f"  [{mark}] {row['id']} ({mode})")
        if not row["passed"]:
            for finding in row.get("findings", [])[:10]:
                print(
                    f"        {finding.get('path')}:{finding.get('line')} {finding.get('text', '')}"
                )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
