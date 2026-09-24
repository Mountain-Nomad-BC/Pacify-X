"""Create the governed usage-memory surface for every skill, agent, and workflow.

Owner requirement (2026-09-24): skill stats live in a memory file inside each skill; agents and
workflows get the same treatment in their own directories.

What this does:

  1. gives every existing ``.px/skills/<id>`` a ``memory/`` directory with an empty append-only log;
  2. creates the ``.px/agents`` and ``.px/workflows`` roots with a registry-backed membership set,
     so the same memory model applies to agents and workflows;
  3. writes a derived rollup for each subject;
  4. is idempotent: re-running changes nothing except where a subject is genuinely new.

It does **not** invent subjects. An agents or workflows entry is created only for an id that a
canonical registry already declares.

Usage:
    python scripts/bootstrap_usage_memory.py --root .
    python scripts/bootstrap_usage_memory.py --root . --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.usage_memory import (  # noqa: E402
    KIND_ROOT,
    ensure_subject_memory,
    list_subjects_with_memory,
)


def registry_subjects(root: Path, kind: str) -> list[str]:
    # Ids that a canonical registry already declares for this subject kind.
    candidates: list[str] = []
    if kind == "skill":
        base = root / ".px/skills"
        if base.is_dir():
            candidates = [d.name for d in base.iterdir() if d.is_dir()]
    elif kind == "agent":
        # Agents are declared by the agency-agent registry, each with a real body path.
        path = root / "registry/agency_agent_registry.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            for row in payload.get("agents", []):
                if isinstance(row, dict):
                    value = row.get("agent_id")
                    if isinstance(value, str):
                        candidates.append(value)
    elif kind == "workflow":
        path = root / "registry/workflow_execution_bindings.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            for row in payload.get("bindings", []):
                if isinstance(row, dict):
                    value = row.get("path") or row.get("workflow_id") or row.get("id")
                    if isinstance(value, str):
                        candidates.append(Path(value).stem)
        wf_dir = root / "orchestration/workflows"
        if wf_dir.is_dir():
            candidates.extend(p.stem for p in wf_dir.glob("*.yaml"))

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        # Agent ids are dotted namespaces; keep dots for agents, normalise for the rest.
        normalized = value.strip().lower()
        if kind != "agent":
            normalized = normalized.replace("_", "-")
        if not normalized or normalized in seen:
            continue
        if any(not (c.isalnum() or c in ".-") for c in normalized):
            continue
        if len(normalized) > (191 if kind == "agent" else 95):
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return sorted(cleaned)


def bootstrap(root: Path, *, apply: bool) -> dict:
    root = root.resolve(strict=True)
    report: dict[str, object] = {"schema_version": "px.usage-memory-bootstrap/1.0", "subjects": {}}

    for kind in ("skill", "agent", "workflow"):
        base = root / KIND_ROOT[kind]
        subjects = registry_subjects(root, kind)
        created: list[str] = []
        skipped: list[str] = []
        if apply:
            base.mkdir(parents=True, exist_ok=True)
        for subject_id in subjects:
            subject_root = base / subject_id
            if apply:
                subject_root.mkdir(parents=True, exist_ok=True)
                (subject_root / "memory").mkdir(parents=True, exist_ok=True)
                try:
                    ensure_subject_memory(root, kind, subject_id)
                except ValueError:
                    skipped.append(subject_id)
                    continue
                created.append(subject_id)
            else:
                if (subject_root / "memory" / "usage.jsonl").is_file():
                    created.append(subject_id)
                else:
                    skipped.append(subject_id)

        existing = list_subjects_with_memory(root, kind)
        report["subjects"][kind] = {
            "declared": len(subjects),
            "with_memory": len(existing),
            "missing_memory": [s for s in subjects if s not in existing][:12],
            "root": KIND_ROOT[kind].as_posix(),
        }
    report["valid"] = all(
        not entry["missing_memory"] for entry in report["subjects"].values()
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = bootstrap(args.root, apply=args.apply and not args.check)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
