"""Import an external Markdown finding register into a bound remediation ledger."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


FINDING = re.compile(
    r"^\|\s*([A-Z]-\d{3})\s*\|\s*\*\*(BLOCKER|HIGH|MEDIUM|LOW)\*\*\s*\|"
    r"\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$"
)
EXPECTED_SEVERITIES = {"BLOCKER": 19, "HIGH": 45, "MEDIUM": 38, "LOW": 11}
EXPECTED_FAMILIES = {
    "R": 31,
    "A": 16,
    "W": 12,
    "S": 12,
    "M": 6,
    "G": 6,
    "K": 2,
    "U": 17,
    "D": 11,
}


def _portable_text(value: str) -> str:
    home = str(Path.home().resolve())
    return value.replace(home, "${USER_HOME}").replace(
        home.replace("\\", "\\\\"), "${USER_HOME}"
    )


def parse_report(path: Path) -> dict[str, object]:
    data = path.resolve(strict=True).read_bytes()
    text = data.decode("utf-8")
    findings: list[dict[str, object]] = []
    for line in text.splitlines():
        match = FINDING.match(line)
        if match is None:
            continue
        finding_id, severity, finding, evidence, correction = match.groups()
        findings.append(
            {
                "id": finding_id,
                "family": finding_id[0],
                "severity": severity,
                "finding": _portable_text(finding),
                "evidence": _portable_text(evidence),
                "required_correction": _portable_text(correction),
                "status": "open",
                "owners": [],
                "acceptance_checks": [],
                "evidence_refs": [],
                "notes": [],
            }
        )
    ids = [str(item["id"]) for item in findings]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate finding IDs in re-audit report")
    severities = Counter(str(item["severity"]) for item in findings)
    families = Counter(str(item["family"]) for item in findings)
    if len(findings) != 113:
        raise ValueError(f"expected 113 findings, found {len(findings)}")
    if dict(severities) != EXPECTED_SEVERITIES:
        raise ValueError(f"severity denominator differs: {dict(severities)}")
    if dict(families) != EXPECTED_FAMILIES:
        raise ValueError(f"family denominator differs: {dict(families)}")
    return {
        "schema_version": "px.adversarial-reaudit-remediation/1.0",
        "source": {
            "name": path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        },
        "denominator": {
            "total": len(findings),
            "severity": EXPECTED_SEVERITIES,
            "family": EXPECTED_FAMILIES,
        },
        "status_counts": {
            "open": len(findings),
            "in_progress": 0,
            "fixed_pending_independent_verification": 0,
            "accepted": 0,
            "blocked": 0,
        },
        "release_claim": {
            "complete": False,
            "certified": False,
            "reason": "All external re-audit findings begin open and require executable acceptance evidence.",
        },
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = parse_report(args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload["denominator"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
