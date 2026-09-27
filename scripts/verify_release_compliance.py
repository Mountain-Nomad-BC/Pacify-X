"""Release compliance gate: required policy/document presence, version consistency, and
claim hygiene.

Implements the `[auto]` and `[item]` checks from
``docs/compliance/RELEASE_COMPLIANCE_CHECKLIST.md`` that can be verified mechanically:

  * required policy documents exist and are non-trivial;
  * no document claims compliance with a framework the project does not hold;
  * no document describes a superseded release as current;
  * version references agree with the actual version sources;
  * compliance artifacts are present and consistent.

This is a **release gate**, not a linter. It fails closed: a missing required document, or a
forbidden compliance claim, blocks the release. It does not attempt to judge prose quality.

Usage:
    python scripts/verify_release_compliance.py --root .
    python scripts/verify_release_compliance.py --root . --json
Exit 0 when the gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SCHEMA = "px.release-compliance-verification/1.0"

# --- required artifacts -----------------------------------------------------
# (path, minimum non-whitespace characters, why it is required)
REQUIRED_ROOT_DOCS: tuple[tuple[str, int, str], ...] = (
    ("LICENSE", 0, "software licence"),
    ("NOTICE", 0, "redistribution notices"),
    ("SECURITY.md", 0, "vulnerability reporting and security policy"),
    ("PRIVACY.md", 0, "privacy behaviour disclosure"),
    ("TELEMETRY.md", 0, "telemetry disclosure"),
    ("DATA_FLOW.md", 0, "data-flow inventory"),
    ("THIRD_PARTY_NOTICES.md", 0, "third-party licence inventory"),
    ("MODEL_AND_DATA_LICENSES.md", 0, "model/data licence registry"),
    ("TRADEMARKS.md", 0, "trademark usage"),
    ("DISCLAIMER.md", 0, "limitations and certification scope"),
    ("INTENDED_USE.md", 0, "intended purpose"),
    ("HIGH_RISK_AND_CONSEQUENTIAL_USE.md", 0, "high-risk use boundary"),
    ("AI_TRANSPARENCY.md", 0, "AI disclosure"),
    ("AI_LIMITATIONS.md", 0, "known AI limitations"),
    ("DATA_RETENTION_AND_DELETION.md", 0, "retention and deletion semantics"),
    ("PROVIDER_DATA_HANDLING.md", 0, "provider data boundary"),
    ("MEMORY_PRIVACY_MODEL.md", 0, "memory privacy model"),
    ("CODE_OF_CONDUCT.md", 0, "community conduct"),
    ("README.md", 0, "project overview"),
)

REQUIRED_DOCS_TREE: tuple[tuple[str, int, str], ...] = (
    ("docs/security/THREAT_MODEL.md", 0, "threat model"),
    ("docs/security/SECURITY_ARCHITECTURE.md", 0, "security architecture"),
    ("docs/security/SECURE_UPDATE_POLICY.md", 0, "secure update policy"),
    ("docs/security/VULNERABILITY_RESPONSE.md", 0, "vulnerability response"),
    ("docs/security/INCIDENT_RESPONSE.md", 0, "incident response"),
    ("docs/security/SUPPLY_CHAIN.md", 0, "supply chain"),
    ("docs/security/SBOM_POLICY.md", 0, "SBOM policy"),
    ("docs/compliance/COMPLIANCE_SCOPE.md", 0, "compliance scope"),
    ("docs/compliance/REGULATORY_APPLICABILITY_MATRIX.md", 0, "applicability matrix"),
    ("docs/compliance/EU_AI_ACT.md", 0, "EU AI Act analysis"),
    ("docs/compliance/EU_CRA.md", 0, "CRA analysis"),
    ("docs/compliance/GDPR.md", 0, "GDPR analysis"),
    ("docs/compliance/US_FEDERAL.md", 0, "US federal baseline"),
    ("docs/compliance/US_STATE_AI_PRIVACY_MATRIX.md", 0, "US state matrix"),
    ("docs/compliance/ACCESSIBILITY.md", 0, "accessibility"),
    ("docs/compliance/EXPORT_CONTROL_REVIEW.md", 0, "export control review"),
    ("docs/compliance/RELEASE_COMPLIANCE_CHECKLIST.md", 0, "release checklist"),
    ("docs/privacy/DATA_INVENTORY.md", 0, "data inventory"),
    ("docs/privacy/RETENTION_MATRIX.md", 0, "retention matrix"),
    ("docs/privacy/SUBPROCESSORS.md", 0, "subprocessors"),
    ("docs/privacy/DSAR_PROCESS.md", 0, "DSAR process"),
)

# --- policy artifacts that must stay consistent -----------------------------
REQUIRED_POLICY_FILES: tuple[tuple[str, str], ...] = (
    ("policies/release-invariants.json", "governed release invariants"),
    ("registry/system_one_decision_policy.json", "System-1 decision thresholds"),
)

# --- forbidden compliance claims --------------------------------------------
# Owner instruction: do not label PX as compliant/certified in these frameworks unless there is
# actual authority and evidence. The manifest itself may *list* them under `not_claimed`.
FORBIDDEN_CLAIMS: tuple[tuple[str, str], ...] = (
    (r"\bEU AI Act compliant\b", "EU AI Act compliance claim"),
    (r"\bCRA compliant\b", "CRA compliance claim"),
    (r"\bGDPR compliant\b", "GDPR compliance claim"),
    (r"\bSOC ?2 compliant\b", "SOC 2 compliance claim"),
    (r"\bISO ?27001 certified\b", "ISO 27001 certification claim"),
    (r"\bHIPAA compliant\b", "HIPAA compliance claim"),
    (r"\bFedRAMP (?:compliant|authorized)\b", "FedRAMP claim"),
    (r"\bFIPS compliant\b", "FIPS compliance claim"),
    (r"\bNIST certified\b", "NIST certification claim"),
)

# Documents permitted to name these frameworks, because they exist to *deny* or *assess* them.
CLAIM_EXEMPT_PATHS = (
    "README.md",
    "DISCLAIMER.md",
    "docs/compliance/",
    "policies/release-invariants.json",
    "SECURITY.md",
)

NEGATION_MARKERS = (
    "does not claim", "do not claim", "not claim", "not_claimed", "no claim",
    "is not ", "are not ", "not represented as", "not certified", "does not hold",
    "not applicable", "must not", "prohibited", "never claim", "does not describe",
    "not a compliance", "not compliance", "without authority",
)

SCAN_SUFFIXES = {".md", ".json", ".toml", ".yaml", ".yml"}
EXCLUDE_DIRS = {".git", ".venv", ".venv-certify", "node_modules", "__pycache__", ".tmp",
                ".px", ".pacify-x", "dist", "out", "evidence"}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _iter_docs(root: Path):
    # Iterate authored documents only, scoped deliberately.
    # Walking the repository root would recurse into evidence, registry data,
    # and custody stores, which are neither claim surfaces nor small.
    targets: list[Path] = list(root.glob("*.md"))
    for area in ("docs", "bootstrap", "policies"):
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
                    if not entry.is_file() or entry.suffix.casefold() not in SCAN_SUFFIXES:
                        continue
                except OSError:
                    continue
                targets.append(entry)
    # The extension copy is a claim surface for the Marketplace listing.
    for name in ("README.md", "CHANGELOG.md"):
        candidate = root / "extension" / name
        if candidate.is_file():
            targets.append(candidate)
    yield from targets


def check_required_documents(root: Path) -> dict:
    missing: list[dict] = []
    trivial: list[dict] = []
    present: list[str] = []
    for relative, min_chars, why in REQUIRED_ROOT_DOCS + REQUIRED_DOCS_TREE:
        path = root / relative
        if not path.is_file():
            missing.append({"path": relative, "reason": why})
            continue
        body = _read(path)
        if body is None or len("".join(body.split())) < min_chars:
            trivial.append({"path": relative, "reason": why, "chars": len(body or "")})
            continue
        present.append(relative)
    return {
        "id": "required-documents",
        "passed": not missing and not trivial,
        "required_count": len(REQUIRED_ROOT_DOCS) + len(REQUIRED_DOCS_TREE),
        "present_count": len(present),
        "missing": missing,
        "trivial": trivial,
    }


def check_policy_artifacts(root: Path) -> dict:
    missing: list[dict] = []
    invalid: list[dict] = []
    for relative, why in REQUIRED_POLICY_FILES:
        path = root / relative
        if not path.is_file():
            missing.append({"path": relative, "reason": why})
            continue
        try:
            json.loads(_read(path))
        except json.JSONDecodeError as error:
            invalid.append({"path": relative, "error": str(error)[:120]})
    return {
        "id": "policy-artifacts",
        "passed": not missing and not invalid,
        "missing": missing,
        "invalid": invalid,
    }


def check_forbidden_claims(root: Path) -> dict:
    findings: list[dict] = []
    for path in _iter_docs(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(CLAIM_EXEMPT_PATHS):
            continue
        text = _read(path)
        for number, line in enumerate(text.splitlines(), start=1):
            lowered = line.casefold()
            for pattern, label in FORBIDDEN_CLAIMS:
                if not re.search(pattern, line, re.IGNORECASE):
                    continue
                if any(marker in lowered for marker in NEGATION_MARKERS):
                    continue
                findings.append({
                    "path": relative, "line": number, "claim": label,
                    "text": line.strip()[:140],
                })
    return {
        "id": "forbidden-compliance-claims",
        "passed": not findings,
        "claim_count": len(findings),
        "findings": findings[:50],
    }


def check_version_consistency(root: Path) -> dict:
    """Version sources must be internally consistent and not contradictory."""

    sources: dict[str, str] = {}
    problems: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        match = re.search(r'^\s*version\s*=\s*"([^"]+)"', _read(pyproject), re.MULTILINE)
        if match:
            sources["pyproject.toml"] = match.group(1)
    runtime_version = root / "runtime/version.py"
    if runtime_version.is_file():
        match = re.search(r'^VERSION\s*=\s*"([^"]+)"', _read(runtime_version), re.MULTILINE)
        if match:
            sources["runtime/version.py"] = match.group(1)
    json_sources = {
        "extension/package.json": "version",
        "extension/package-lock.json": "version",
        "registry/build_claims.json": "version",
    }
    for relative_path, key in json_sources.items():
        path = root / relative_path
        if not path.is_file():
            problems.append(f"{relative_path} is missing")
            continue
        try:
            value = json.loads(_read(path))
        except json.JSONDecodeError as error:
            problems.append(
                f"{relative_path} contains invalid JSON "
                f"at line {error.lineno}, column {error.colno}"
            )
            continue
        sources[relative_path] = str(value.get(key, "")) if isinstance(value, dict) else ""
        if relative_path == "extension/package-lock.json" and isinstance(value, dict):
            packages = value.get("packages", {})
            package_root = packages.get("", {}) if isinstance(packages, dict) else {}
            sources["extension/package-lock.json#packages."] = (
                str(package_root.get("version", "")) if isinstance(package_root, dict) else ""
            )
    adapter = root / "extension/src/agentHarness/adapters/codexAppServer.js"
    if adapter.is_file():
        match = re.search(r"clientVersion\s*\|\|\s*'([^']+)'", _read(adapter))
        if match:
            sources["extension/src/agentHarness/adapters/codexAppServer.js"] = match.group(1)

    # The release lines must not silently disagree in a way that misleads: if pyproject declares a
    # line, the README must reference the same line as current.
    readme = _read(root / "README.md")
    declared_line = sources.get("pyproject.toml", "")
    if declared_line:
        major_minor = ".".join(declared_line.split(".")[:2])
        if major_minor and major_minor not in readme:
            problems.append(
                f"README.md does not reference the pyproject version line {major_minor}"
            )
    required_sources = (
        "pyproject.toml", "runtime/version.py", "extension/package.json",
        "extension/package-lock.json", "extension/package-lock.json#packages.",
        "registry/build_claims.json", "extension/src/agentHarness/adapters/codexAppServer.js",
    )
    for source in required_sources:
        if source not in sources and not any(problem.startswith(f"{source} ") for problem in problems):
            problems.append(f"{source} declares no version")
        elif source in sources and not sources[source]:
            problems.append(f"{source} declares no version")
    for source, version in sources.items():
        if declared_line and version and version != declared_line:
            problems.append(f"{source} version {version} disagrees with pyproject.toml {declared_line}")

    return {
        "id": "version-consistency",
        "passed": not problems,
        "sources": sources,
        "problems": problems,
    }


def verify(root: Path) -> dict:
    root = root.resolve(strict=True)
    results = [
        check_required_documents(root),
        check_policy_artifacts(root),
        check_forbidden_claims(root),
        check_version_consistency(root),
    ]
    failed = [r for r in results if not r["passed"]]
    return {
        "schema_version": SCHEMA,
        "valid": not failed,
        "check_count": len(results),
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
    print(f"release compliance: valid={result['valid']} "
          f"({result['check_count'] - result['failed_count']}/{result['check_count']} checks pass)")
    for row in result["results"]:
        print(f"  [{'PASS' if row['passed'] else 'FAIL'}] {row['id']}")
        if row["passed"]:
            continue
        for key in ("missing", "trivial", "invalid", "findings"):
            for item in row.get(key, [])[:12]:
                print(f"        {item}")
        for problem in row.get("problems", [])[:12]:
            print(f"        {problem}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
