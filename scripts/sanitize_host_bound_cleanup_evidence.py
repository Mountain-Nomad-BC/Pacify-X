"""Redact workstation locators from the four retained cleanup receipts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.evidence_portability import rewrite_reference_literals  # noqa: E402


RECEIPTS = (
    "evidence/owned-test-cache-cleanup-20260813.json",
    "evidence/pytest-ephemeral-cleanup-20260813.json",
    "evidence/pytest-ephemeral-cleanup-final-20260813.json",
    "evidence/px-generated-test-fixture-cleanup-20260813.json",
)


def sanitize(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    user_home = Path.home().resolve()
    user_temp = Path(tempfile.gettempdir()).resolve()
    replacements = {
        str(root): "${PROJECT_ROOT}",
        str(root).replace("\\", "\\\\"): "${PROJECT_ROOT}",
        str(user_temp): "${USER_TEMP}",
        str(user_temp).replace("\\", "\\\\"): "${USER_TEMP}",
        str(user_home): "${USER_HOME}",
        str(user_home).replace("\\", "\\\\"): "${USER_HOME}",
    }
    changed: list[str] = []
    for relative in RECEIPTS:
        path = root / relative
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        rewritten = rewrite_reference_literals(value, replacements)
        if not isinstance(rewritten, dict):
            raise ValueError(f"cleanup receipt must be an object: {relative}")
        rewritten["locator_redaction"] = {
            "schema_version": "px.host-locator-redaction/1.0",
            "host_paths_removed": True,
            "portable_tokens": ["${PROJECT_ROOT}", "${USER_HOME}", "${USER_TEMP}"],
            "semantic_fields_preserved": True,
        }
        rewritten["evidence_classification"] = {
            "class": "historical_forensic_cleanup_record",
            "current_release_authority": False,
            "accounting_independently_validated": False,
            "limitation": "Retained/remaining objects and filesystem logical-byte accounting prevent this historical receipt from proving a clean current release tree.",
        }
        path.write_text(
            json.dumps(rewritten, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        changed.append(relative)
    return {"valid": True, "changed": changed, "changed_count": len(changed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(sanitize(args.root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
