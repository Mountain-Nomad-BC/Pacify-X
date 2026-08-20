"""Run the canonical bootstrap audit and optionally write machine/human reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from runtime.release_audit import audit_framework  # noqa: E402 -- local source bootstrap


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Bootstrap audit",
        "",
        f"Result: {'PASS' if report['valid'] else 'FAIL'}",
        f"Checks: {report['passed']}/{report['check_count']}",
        "",
    ]
    for item in report["checks"]:
        lines.append(
            f"- [{'x' if item['passed'] else ' '}] `{item['id']}` - {item['detail']}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--strict-external-evidence", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    report = audit_framework(
        args.root, require_external_manifests=args.strict_external_evidence
    )
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["valid"] else 1)
