"""Per-YAML statistical operations and persistent memory files.

Build-time requirement (2026-10-09): every canonical YAML definition — workflow
declarations, project-stream orchestration files, source skill manifests and
imported research ops — must spin up, for each subject it declares:

* a statistical operations file (``memory/stats.json``, derived through the
  T.I.E.-custodied usage-memory owner);
* a persistent memory file pair (``memory/usage.jsonl`` + ``memory/memory.md``);
* a binding file (``memory/bindings.json``) that ties the YAML to every process,
  agent, workflow, skill and template it declares or instantiates; and
* a global mapping artifact (``.px/usage-memory/subject-manifest.{json,md}``)
  that proves every YAML maps onto its subject files 1:1.

This owner never invents subjects, never writes an unattributed record, and
never bypasses custody: memory creation and stats reconciliation go through
``runtime.usage_memory`` (T.I.E. effect intents + scope leases); the markdown /
binding twins are content-addressed images written idempotently beside them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .json_io import read_bounded_bytes
from .usage_memory import (
    KIND_ROOT,
    ensure_subject_memory,
    rebuild_stats,
    read_stats,
    subject_memory_directory,
)

SCHEMA_VERSION = "px.yaml-subject-files/1.0"
MANIFEST_SCHEMA_VERSION = "px.yaml-subject-manifest/1.0"
MANIFEST_DIR = Path(".px/usage-memory")
MAX_YAML_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_SUBJECTS = 512

#: Bounded subject-id normalization, identical to the usage-memory bootstrap.
_WORKFLOW_ROOT = Path("orchestration/workflows")
_SKILL_ROOTS = (
    Path("registry/source_skill_manifests"),
    Path("registry/imported_research_ops"),
)


def _normalized_id(value: str) -> str | None:
    normalized = str(value).strip().lower().replace("_", "-")
    if not normalized or len(normalized) > 95:
        return None
    if any(not (char.isalnum() or char in ".-") for char in normalized):
        return None
    return normalized


def _parse_document(path: Path) -> dict[str, Any] | None:
    """Parse a bounded YAML-definition file: JSON-in-yaml first, then YAML."""
    if path.stat().st_size > MAX_YAML_BYTES:
        raise ValueError(f"yaml definition {path.name} exceeds its bounded size")
    text = bytes(read_bounded_bytes(path, max_bytes=MAX_YAML_BYTES)).decode("utf-8-sig")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        import yaml  # bounded: only for true-YAML definition files

        parsed = yaml.safe_load(text)
    return parsed if isinstance(parsed, dict) else None


def _strings(value: Any, limit: int = 64) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list):
        return tuple(str(item) for item in value[:limit] if isinstance(item, str) and item.strip())
    return ()


@dataclass(frozen=True, slots=True)
class YamlSubject:
    kind: str
    subject_id: str
    source_yaml: str
    yaml_sha256: str
    title: str
    bindings: dict[str, list[str]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "source_yaml": self.source_yaml,
            "yaml_sha256": self.yaml_sha256,
            "title": self.title,
            "bindings": {key: sorted(set(values)) for key, values in sorted(self.bindings.items())},
        }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(bytes(read_bounded_bytes(path, max_bytes=MAX_YAML_BYTES))).hexdigest()


def _skill_bindings(document: Mapping[str, Any]) -> dict[str, list[str]]:
    bindings: dict[str, list[str]] = {}
    for key in ("integrations", "requires", "provides", "agents", "workflows", "models"):
        values = _strings(document.get(key))
        if values:
            bindings[key] = list(values)
    return bindings


def _workflow_bindings(workflow: Mapping[str, Any]) -> dict[str, list[str]]:
    bindings: dict[str, list[str]] = {"skills": [], "workflow_steps": [], "agents": []}
    steps = workflow.get("steps")
    if isinstance(steps, list):
        for step in steps[:64]:
            if not isinstance(step, Mapping):
                continue
            step_id = step.get("id")
            if isinstance(step_id, str) and step_id.strip():
                bindings["workflow_steps"].append(step_id)
            skill = step.get("skill") or step.get("agent")
            if isinstance(skill, str) and skill.strip():
                bindings["skills"].append(skill)
    bounds = workflow.get("bounds")
    if isinstance(bounds, Mapping):
        for key in ("primary_agents", "agents", "approver", "processes"):
            values = _strings(bounds.get(key))
            if values:
                bindings["agents" if "agent" in key else "processes"] = bindings.get(
                    "agents" if "agent" in key else "processes", []
                ) + list(values)
    return {key: values for key, values in bindings.items() if values}


def canonical_yaml_subjects(root: Path) -> tuple[YamlSubject, ...]:
    """Enumerate every canonical YAML definition and the subjects it declares."""
    root = Path(root).resolve(strict=True)
    subjects: list[YamlSubject] = []
    seen: set[tuple[str, str, str]] = set()

    def add(kind: str, subject_id: str, path: Path, title: str, bindings: dict[str, list[str]]) -> None:
        normalized = _normalized_id(subject_id)
        if normalized is None:
            return
        key = (kind, normalized, path.relative_to(root).as_posix())
        if key in seen or len(seen) >= MAX_SUBJECTS:
            return
        seen.add(key)
        subjects.append(YamlSubject(
            kind=kind, subject_id=normalized, source_yaml=path.relative_to(root).as_posix(),
            yaml_sha256=_file_sha256(path), title=str(title or normalized)[:200],
            bindings=bindings,
        ))

    # Workflow declaration files: JSON-in-yaml documents declaring workflows[].
    for path in sorted((root / _WORKFLOW_ROOT).glob("*.yaml")):
        document = _parse_document(path)
        if document is None:
            continue
        workflows = document.get("workflows")
        if not isinstance(workflows, list):
            continue
        for workflow in workflows[:32]:
            if not isinstance(workflow, Mapping):
                continue
            workflow_id = workflow.get("id")
            if not isinstance(workflow_id, str):
                continue
            add("workflow", workflow_id, path, workflow.get("purpose") or workflow_id,
                _workflow_bindings(workflow))

    # Project-stream orchestration files: one workflow subject per file.
    stream_root = root / _WORKFLOW_ROOT / "project_stream"
    if stream_root.is_dir():
        for path in sorted(stream_root.glob("*.yaml")):
            document = _parse_document(path)
            if document is None:
                continue
            stream_id = document.get("orchestration_id") or path.stem
            bindings: dict[str, list[str]] = {}
            for key in ("skills", "agents", "required_context"):
                values = _strings(document.get(key))
                if values:
                    bindings["skills" if key == "skills" else key] = list(values)
            add("workflow", stream_id, path, document.get("title") or stream_id, bindings)

    # Skill manifests: source skill manifests and imported research ops.
    for skill_root in _SKILL_ROOTS:
        base = root / skill_root
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.yaml")):
            document = _parse_document(path)
            if document is None:
                continue
            skill_id = document.get("id") or document.get("skill_id") or path.stem
            add("skill", skill_id, path, document.get("purpose") or document.get("title") or skill_id,
                _skill_bindings(document))

    return tuple(subjects)


def _render_memory_md(subject: YamlSubject, stats: Mapping[str, Any], bindings: Mapping[str, Any],
                      paths: Mapping[str, str]) -> str:
    lines = [
        f"# Persistent memory — {subject.kind}:{subject.subject_id}",
        "",
        f"- Source YAML: `{subject.source_yaml}` (sha256 `{subject.yaml_sha256[:16]}…`)",
        f"- Title: {subject.title}",
        f"- Schema: `{SCHEMA_VERSION}`",
        "",
        "## Statistical operations snapshot",
        "",
        "```json",
        json.dumps({key: stats.get(key) for key in ("schema_version", "total_observations", "successful_observations",
                                                    "failed_observations", "stats_sha256") if key in stats},
                   sort_keys=True, indent=2),
        "```",
        "",
        "## Bindings (declared + instantiated)",
        "",
        "```json",
        json.dumps(bindings, sort_keys=True, indent=2),
        "```",
        "",
        "## Files in this memory directory",
        "",
        *[f"- `{name}` — {description}" for name, description in sorted(paths.items())],
        "",
        "_Derived rollups are non-canonical; the append-only `usage.jsonl` is the source of truth._",
        "",
    ]
    return "\n".join(lines)


def _write_idempotent(path: Path, image: str) -> None:
    """Write only when the content-addressed image actually changed."""
    encoded = image.encode("utf-8")
    try:
        if path.is_file() and path.read_bytes() == encoded:
            return
    except OSError:
        pass
    path.write_bytes(encoded)


def ensure_yaml_subject_files(root: Path, *, apply: bool = True) -> dict[str, Any]:
    """Spin up the statistical + persistent memory surface for every YAML subject."""
    root = Path(root).resolve(strict=True)
    subjects = canonical_yaml_subjects(root)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "yaml_files": len({subject.source_yaml for subject in subjects}),
        "subjects": [],
        "manifest": None,
        "applied": bool(apply),
    }
    manifest_rows: list[dict[str, Any]] = []
    for subject in subjects:
        row: dict[str, Any] = {**subject.as_dict(), "files": {}}
        if apply:
            subject_root = root / KIND_ROOT[subject.kind] / subject.subject_id
            subject_root.mkdir(parents=True, exist_ok=True)
            ensure_subject_memory(root, subject.kind, subject.subject_id)
            rebuild_stats(root, subject.kind, subject.subject_id)
            memory_dir = subject_memory_directory(root, subject.kind, subject.subject_id)
            stats = read_stats(root, subject.kind, subject.subject_id)
            bindings = {
                **subject.as_dict()["bindings"],
                "source_yaml": subject.source_yaml,
                "source_yaml_sha256": subject.yaml_sha256,
                "subject_kind": subject.kind,
                "subject_id": subject.subject_id,
                "instantiation_hook": "runtime.usage_memory.record_observation (custody-gated)",
            }
            bindings_image = json.dumps(bindings, indent=2, sort_keys=True) + "\n"
            _write_idempotent(memory_dir / "bindings.json", bindings_image)
            paths = {
                "usage.jsonl": "append-only attributed observation log (source of truth)",
                "stats.json": "derived statistical operations rollup (non-canonical)",
                "bindings.json": "declared + instantiated binding map for this subject",
                "memory.md": "persistent human-readable memory twin (this file)",
            }
            _write_idempotent(memory_dir / "memory.md",
                              _render_memory_md(subject, stats, bindings, paths))
            row["files"] = {
                "memory_dir": memory_dir.relative_to(root).as_posix(),
                "stats": (memory_dir / "stats.json").relative_to(root).as_posix(),
                "usage_log": (memory_dir / "usage.jsonl").relative_to(root).as_posix(),
                "bindings": (memory_dir / "bindings.json").relative_to(root).as_posix(),
                "memory_md": (memory_dir / "memory.md").relative_to(root).as_posix(),
            }
        manifest_rows.append(row)
        report["subjects"].append({
            "kind": subject.kind, "subject_id": subject.subject_id,
            "source_yaml": subject.source_yaml, "files": row["files"] or None,
        })

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_from": SCHEMA_VERSION,
        "yaml_file_count": report["yaml_files"],
        "subject_count": len(manifest_rows),
        "subjects": manifest_rows,
        "authority_granted": False,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps({key: value for key, value in manifest.items() if key != "manifest_sha256"},
                   sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    report["manifest"] = {
        "json": (MANIFEST_DIR / "subject-manifest.json").as_posix(),
        "md": (MANIFEST_DIR / "subject-manifest.md").as_posix(),
        "manifest_sha256": manifest["manifest_sha256"],
    }
    if apply:
        manifest_dir = root / MANIFEST_DIR
        manifest_dir.mkdir(parents=True, exist_ok=True)
        _write_idempotent(manifest_dir / "subject-manifest.json",
                          json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        md_lines = [
            "# YAML subject memory map",
            "",
            f"- Manifest sha256: `{manifest['manifest_sha256'][:16]}…`",
            f"- YAML files mapped: {manifest['yaml_file_count']}",
            f"- Subjects with statistical operations + persistent memory: {manifest['subject_count']}",
            "",
            "| Kind | Subject | Source YAML | Memory dir |",
            "|---|---|---|---|",
        ]
        for row in manifest_rows:
            files = row.get("files") or {}
            md_lines.append(
                f"| {row['kind']} | `{row['subject_id']}` | `{row['source_yaml']}` | "
                f"`{files.get('memory_dir', '-')}` |"
            )
        md_lines.append("")
        md_lines.append("_Per subject: `stats.json` (statistical operations), `usage.jsonl` + "
                        "`memory.md` (persistent memory), `bindings.json` (process/agent/workflow ties)._")
        _write_idempotent(manifest_dir / "subject-manifest.md", "\n".join(md_lines) + "\n")
    report["valid"] = report["yaml_files"] > 0
    return report
