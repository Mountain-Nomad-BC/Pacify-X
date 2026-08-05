"""Portable, evidence-preserving transcript intake and canonical export.

The runtime does not infer queue-specific diagnoses.  It owns immutable ingest,
typed records, queue isolation, source-span validation, and deterministic export;
an admitted queue adapter may perform extraction behind those boundaries.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Iterable, Mapping, Sequence
import uuid

from .contracts import ContractValidationError, validate_instance
from .json_io import load_json_object


PROFILE_SCHEMA = Path("contracts/transcripts/transcript-profile.schema.json")
SOURCE_SCHEMA = Path("contracts/transcripts/transcript-source.schema.json")
RECORD_SCHEMA = Path("contracts/transcripts/transcript-record.schema.json")
ONTOLOGY_SCHEMA = Path("contracts/transcripts/transcript-ontology.schema.json")
SUPPORTED_INPUTS = {".txt", ".json", ".csv"}
COMPLETED_ACTIONS = {"REPORTED_COMPLETED", "VERIFIED_COMPLETED"}
UNCONFIRMED_ACTIONS = {
    "RECOMMENDED",
    "REQUESTED",
    "INSTRUCTED",
    "COMMITTED",
    "PERFORMING",
}
SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _safe_id(value: str, label: str) -> str:
    result = SAFE_ID.sub("-", value.strip()).strip(".-")
    if not result or result != value:
        raise ValueError(
            f"{label} must contain only letters, numbers, dot, underscore, or hyphen"
        )
    return result


def default_profile(queue_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "profile_id": f"canonical-{_safe_id(queue_id, 'queue_id')}",
        "queue_id": queue_id,
        "adapter": "canonical-import",
        "tool_root": None,
        "runner": None,
        "input_formats": ["txt", "json", "csv"],
        "canonical_formats": ["jsonl", "csv"],
        "publish_latest": False,
    }


def load_profile(
    root: Path,
    *,
    profile: Path | None = None,
    project: Path | None = None,
    queue_id: str | None = None,
) -> dict[str, Any]:
    """Load explicit/project configuration; never commit a host-specific default."""
    candidates = [
        profile,
        project / ".engineering-bootstrap" / "transcript-analysis.json"
        if project
        else None,
    ]
    selected = next(
        (path for path in candidates if path is not None and path.is_file()), None
    )
    value = (
        load_json_object(selected)
        if selected
        else default_profile(queue_id or "default")
    )
    validate_instance(value, root / PROFILE_SCHEMA, contract_root=root / "contracts")
    if queue_id and value["queue_id"] != queue_id:
        raise ValueError("profile queue_id does not match the requested queue")
    tool_root = value.get("tool_root")
    if tool_root:
        tool = Path(str(tool_root)).expanduser().resolve(strict=True)
        if not tool.is_dir():
            raise ValueError("configured transcript tool_root is not a directory")
        value = {**value, "tool_root": tool.as_posix()}
    return value


def build_queue_adapter_plan(
    profile: Mapping[str, Any], input_dir: Path, output_dir: Path
) -> dict[str, Any]:
    """Prepare an argv-only adapter plan; planning never executes a tool."""
    if output_dir.name.casefold() == "latest" or output_dir.exists():
        raise ValueError("adapter output must be a new non-latest run directory")
    if profile.get("adapter") == "canonical-import":
        return {
            "valid": True,
            "adapter": "canonical-import",
            "command": None,
            "required_action": "write validated canonical records through the transcript record boundary",
            "execution_authorized": False,
        }
    tool_value = profile.get("tool_root")
    runner_value = profile.get("runner")
    if not tool_value or not runner_value:
        raise ValueError("external-command profile requires tool_root and runner")
    tool_root = Path(str(tool_value)).resolve(strict=True)
    runner = Path(str(runner_value))
    if runner.is_absolute() or ".." in runner.parts:
        raise ValueError("external adapter runner must be relative to tool_root")
    runner_path = (tool_root / runner).resolve(strict=True)
    if not runner_path.is_file() or not runner_path.is_relative_to(tool_root):
        raise ValueError("external adapter runner escapes tool_root or is missing")
    command = [
        str(runner_path),
        "--input",
        str(input_dir.resolve(strict=True)),
        "--output",
        str(output_dir.resolve()),
    ]
    return {
        "valid": True,
        "adapter": "external-command",
        "tool_root": tool_root.as_posix(),
        "runner_sha256": _sha(runner_path),
        "command": command,
        "shell": False,
        "execution_authorized": False,
    }


def _source_files(
    inputs: Sequence[Path], *, max_files: int, max_bytes: int
) -> list[Path]:
    paths: list[Path] = []
    for value in inputs:
        resolved = value.resolve(strict=True)
        if resolved.is_symlink():
            raise ValueError(f"symlinked transcript input is not allowed: {value}")
        if resolved.is_dir():
            paths.extend(
                path
                for path in sorted(
                    resolved.iterdir(), key=lambda item: item.name.casefold()
                )
                if path.is_file()
                and not path.is_symlink()
                and path.suffix.casefold() in SUPPORTED_INPUTS
            )
        elif resolved.is_file() and resolved.suffix.casefold() in SUPPORTED_INPUTS:
            paths.append(resolved)
        else:
            raise ValueError(f"unsupported transcript input: {value}")
    unique = list(dict.fromkeys(path.resolve(strict=True) for path in paths))
    if not unique or len(unique) > max_files:
        raise ValueError(f"transcript input count must be between 1 and {max_files}")
    total = sum(path.stat().st_size for path in unique)
    if total > max_bytes:
        raise ValueError(
            f"transcript input byte budget exceeded: {total} > {max_bytes}"
        )
    return unique


def plan_ingest(
    root: Path,
    inputs: Sequence[Path],
    output_root: Path,
    *,
    queue_id: str,
    run_id: str | None = None,
    source_dates: Mapping[str, str] | None = None,
    max_files: int = 10_000,
    max_bytes: int = 2 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    queue = _safe_id(queue_id, "queue_id")
    files = _source_files(inputs, max_files=max_files, max_bytes=max_bytes)
    output_root = output_root.resolve()
    run = _safe_id(
        run_id
        or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8],
        "run_id",
    )
    target = output_root / queue / "runs" / run
    if target.exists():
        raise FileExistsError(f"transcript run already exists: {target}")
    dates = source_dates or {}
    records = []
    for index, path in enumerate(files, 1):
        digest = _sha(path)
        conversation_id = _safe_id(path.stem, "conversation_id")
        copied_name = f"{index:05d}-{path.name}"
        records.append(
            {
                "source_id": f"src-{digest[:20]}",
                "conversation_id": conversation_id,
                "source_file": path.as_posix(),
                "source_date": dates.get(path.name),
                "source_sha256": digest,
                "bytes": path.stat().st_size,
                "ingested_copy": f"sources/{copied_name}",
            }
        )
    payload = {
        "schema_version": "1.0",
        "queue_id": queue,
        "run_id": run,
        "target": target.as_posix(),
        "source_count": len(records),
        "byte_count": sum(item["bytes"] for item in records),
        "publish_latest": False,
        "sources": records,
    }
    payload["plan_sha256"] = _stable(payload)
    return payload


def ingest_transcripts(
    root: Path,
    inputs: Sequence[Path],
    output_root: Path,
    *,
    queue_id: str,
    run_id: str | None = None,
    source_dates: Mapping[str, str] | None = None,
    apply: bool = False,
    max_files: int = 10_000,
    max_bytes: int = 2 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    plan = plan_ingest(
        root,
        inputs,
        output_root,
        queue_id=queue_id,
        run_id=run_id,
        source_dates=source_dates,
        max_files=max_files,
        max_bytes=max_bytes,
    )
    if not apply:
        return {"valid": True, "applied": False, **plan}
    target = Path(plan["target"])
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        (stage / "sources").mkdir()
        (stage / "data").mkdir()
        for receipt in plan["sources"]:
            source = Path(receipt["source_file"])
            destination = stage / receipt["ingested_copy"]
            shutil.copyfile(source, destination)
            if _sha(destination) != receipt["source_sha256"]:
                raise ValueError(f"source copy hash mismatch: {source}")
        manifest = {
            key: value
            for key, value in plan.items()
            if key not in {"target", "plan_sha256"}
        }
        manifest["created_at"] = datetime.now(timezone.utc).isoformat()
        manifest["records_path"] = "data/records.jsonl"
        manifest["records_sha256"] = None
        manifest["run_manifest_sha256"] = _stable(manifest)
        (stage / "run.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(stage, target)
    except Exception:
        if stage.exists():
            failure = target.parent / f"{stage.name}.failed"
            os.replace(stage, failure)
        raise
    return {"valid": True, "applied": True, **plan}


def validate_canonical_record(root: Path, record: Mapping[str, Any]) -> None:
    value = dict(record)
    validate_instance(value, root / RECORD_SCHEMA, contract_root=root / "contracts")
    span = value["source_span"]
    if span["end_line"] < span["start_line"]:
        raise ValueError("source_span end_line precedes start_line")
    kind = value["record_kind"]
    action = value.get("action_state", "NONE")
    outcome = value.get("outcome_state", "NONE")
    evidence = value["evidence_state"]
    validation = value.get("validation_evidence", [])
    if kind == "action" and action == "NONE":
        raise ValueError("action record requires a non-NONE action_state")
    if kind == "outcome" and outcome == "NONE":
        raise ValueError("outcome record requires a non-NONE outcome_state")
    if action in UNCONFIRMED_ACTIONS and outcome == "VERIFIED":
        raise ValueError(
            "recommendation, request, commitment, or in-progress work cannot be a verified outcome"
        )
    if action == "VERIFIED_COMPLETED" or outcome == "VERIFIED":
        if evidence != "ASSERTED" or not validation:
            raise ValueError(
                "verified completion requires asserted evidence and validation evidence"
            )
    if (
        evidence == "UNCERTAIN"
        and kind in {"component", "serial", "measurement", "outcome"}
        and value["review_required"] is not True
    ):
        raise ValueError("uncertain domain facts must be marked for review")


def load_ontology(root: Path, path: Path) -> dict[str, Any]:
    ontology = load_json_object(path)
    validate_instance(
        ontology, root / ONTOLOGY_SCHEMA, contract_root=root / "contracts"
    )
    return ontology


def normalize_queue_term(
    ontology: Mapping[str, Any],
    *,
    queue_id: str,
    term: str,
    from_queue: str | None = None,
) -> str:
    if ontology.get("queue_id") != queue_id:
        raise ValueError("ontology is owned by another queue")
    if from_queue and from_queue != queue_id:
        approved = any(
            item.get("from_queue") == from_queue
            and item.get("term", "").casefold() == term.casefold()
            for item in ontology.get("reviewed_transfers", [])
        )
        if not approved:
            raise ValueError(
                "cross-queue ontology transfer requires an explicit reviewed transfer"
            )
    aliases = {
        str(key).casefold(): str(value)
        for key, value in ontology.get("aliases", {}).items()
    }
    return aliases.get(term.casefold(), term)


def write_canonical_records(
    root: Path,
    run_dir: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    manifest_path = run_dir / "run.json"
    manifest = load_json_object(manifest_path)
    sources = {item["source_id"]: item for item in manifest["sources"]}
    ordered = sorted(
        (dict(item) for item in records), key=lambda item: item["record_id"]
    )
    seen: set[str] = set()
    for record in ordered:
        validate_canonical_record(root, record)
        if record["record_id"] in seen:
            raise ValueError(f"duplicate transcript record_id: {record['record_id']}")
        seen.add(record["record_id"])
        source = sources.get(record["source_id"])
        if source is None or source["source_sha256"] != record["source_sha256"]:
            raise ValueError(
                f"record source provenance mismatch: {record['record_id']}"
            )
        if record["conversation_id"] != source["conversation_id"]:
            raise ValueError(
                f"record conversation identity mismatch: {record['record_id']}"
            )
        if record["queue_id"] != manifest["queue_id"]:
            raise ValueError(f"record queue boundary mismatch: {record['record_id']}")
    target = run_dir / "data" / "records.jsonl"
    if target.exists():
        raise FileExistsError(
            "canonical record file already exists; runs are append-free and immutable"
        )
    rendered = "".join(
        json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n" for item in ordered
    )
    result = {
        "valid": True,
        "applied": apply,
        "record_count": len(ordered),
        "records_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "target": target.as_posix(),
    }
    if not apply:
        return result
    target.write_text(rendered, encoding="utf-8", newline="\n")
    manifest["records_sha256"] = result["records_sha256"]
    manifest["run_manifest_sha256"] = _stable(
        {key: value for key, value in manifest.items() if key != "run_manifest_sha256"}
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def _records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "data" / "records.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_run(root: Path, run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    run_dir = run_dir.resolve(strict=True)
    try:
        manifest = load_json_object(run_dir / "run.json")
        for source in manifest["sources"]:
            validate_instance(
                source, root / SOURCE_SCHEMA, contract_root=root / "contracts"
            )
            copy = run_dir / source["ingested_copy"]
            if not copy.is_file() or _sha(copy) != source["source_sha256"]:
                errors.append(f"source copy integrity mismatch: {source['source_id']}")
        records = _records(run_dir)
        for record in records:
            validate_canonical_record(root, record)
        records_path = run_dir / "data" / "records.jsonl"
        actual_records_sha = _sha(records_path) if records_path.is_file() else None
        if manifest.get("records_sha256") != actual_records_sha:
            errors.append("canonical record digest mismatch")
        expected_manifest = _stable(
            {
                key: value
                for key, value in manifest.items()
                if key != "run_manifest_sha256"
            }
        )
        if manifest.get("run_manifest_sha256") != expected_manifest:
            errors.append("run manifest digest mismatch")
    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        ContractValidationError,
    ) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        manifest = {}
        records = []
    return {
        "valid": not errors,
        "queue_id": manifest.get("queue_id"),
        "run_id": manifest.get("run_id"),
        "source_count": len(manifest.get("sources", [])),
        "record_count": len(records),
        "errors": errors,
    }


def export_selected_summary(
    root: Path,
    run_dir: Path,
    conversation_ids: Sequence[str],
    output: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    validation = validate_run(root, run_dir)
    if not validation["valid"]:
        raise ValueError(f"invalid transcript run: {validation['errors']}")
    wanted = list(dict.fromkeys(conversation_ids))
    grouped: dict[str, list[dict[str, Any]]] = {item: [] for item in wanted}
    for record in _records(run_dir.resolve(strict=True)):
        if record["conversation_id"] in grouped:
            grouped[record["conversation_id"]].append(record)
    source_by_conversation = {
        item["conversation_id"]: item
        for item in load_json_object(run_dir / "run.json")["sources"]
    }
    fields = [
        "source_date",
        "conversation_id",
        "source_file",
        "source_sha256",
        "serials",
        "issues",
        "components",
        "actions",
        "outcomes",
        "resolution_status",
    ]
    rows = []
    for conversation_id in wanted:
        records = grouped.get(conversation_id, [])
        source = source_by_conversation.get(conversation_id, {})
        by_kind = {
            kind: [item for item in records if item["record_kind"] == kind]
            for kind in ("serial", "issue", "component", "action", "outcome")
        }
        actions = " | ".join(
            f"{item.get('action_state', 'NONE')}: {item['text']}"
            for item in by_kind["action"]
        )
        outcomes = " | ".join(
            f"{item.get('outcome_state', 'NONE')}: {item['text']}"
            for item in by_kind["outcome"]
        )
        verified = any(
            item.get("outcome_state") == "VERIFIED"
            or item.get("action_state") == "VERIFIED_COMPLETED"
            for item in records
        )
        reported = any(
            item.get("action_state") in COMPLETED_ACTIONS for item in records
        )
        rows.append(
            {
                "source_date": source.get("source_date") or "",
                "conversation_id": conversation_id,
                "source_file": source.get("source_file", ""),
                "source_sha256": source.get("source_sha256", ""),
                "serials": " | ".join(
                    str(item.get("value") or item["label"])
                    for item in by_kind["serial"]
                ),
                "issues": " | ".join(item["label"] for item in by_kind["issue"]),
                "components": " | ".join(
                    item["label"] for item in by_kind["component"]
                ),
                "actions": actions,
                "outcomes": outcomes,
                "resolution_status": "verified outcome"
                if verified
                else (
                    "reported completed; not independently verified"
                    if reported
                    else (
                        "action or recommendation documented; outcome unconfirmed"
                        if actions
                        else "no resolution captured"
                    )
                ),
            }
        )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    rendered = stream.getvalue()
    if output.exists():
        raise FileExistsError(f"transcript export already exists: {output}")
    if apply:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
    return {
        "valid": True,
        "applied": apply,
        "row_count": len(rows),
        "output": output.resolve().as_posix(),
        "sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "csv": rendered if not apply else None,
    }


def validate_transcript_orchestration(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    path = root / "orchestration" / "workflows" / "transcript-evidence-extraction.yaml"
    try:
        payload = load_json_object(path)
        workflow = payload["workflows"][0]
        ids = {str(item["id"]) for item in workflow["steps"]}
        expected = {
            "profile",
            "ingest",
            "separate-lifecycle",
            "normalize-queue-terms",
            "extract",
            "validate",
            "export",
        }
        if ids != expected:
            errors.append("transcript workflow lifecycle is incomplete")
        for step in workflow["steps"]:
            unknown = set(step.get("depends_on", ())) - ids
            if unknown:
                errors.append(f"{step['id']}: unknown dependencies {sorted(unknown)}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        errors.append(f"transcript workflow unavailable: {type(exc).__name__}: {exc}")
    return {
        "valid": not errors,
        "workflow": "transcript-evidence-extraction",
        "errors": errors,
    }
