"""Bounded read-only generic helpers for declared-suite metadata.

Declared contracts are hydrated and generic operations evaluated; authoritative
implementation_target scripts are not imported or executed. Supplied constraints
do not grant effect authority. Each outer request owns its bounded input context.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Mapping
from .numeric_inputs import (
    bounded_text,
    bounded_sequence,
    bounded_mapping,
    bounded_json_value,
    bounded_integer,
    finite_number,
)
from .input_files import (
    contained_file,
    read_file_image,
    relative_source_path,
    check_deadline,
)
from .archive_io import member_identity, reject_path_links
from .json_io import decode_json_object
from .bounded_walk import bounded_walk, WalkLimits

_ACTIVE_INPUTS = ContextVar("declared_suite_inputs", default=None)
_KINDS = {"skill", "script", "orchestration"}


def _text(value, name, maximum=512):
    value = bounded_text(value, name, maximum=maximum, strip=False)
    if not value.strip():
        raise ValueError(name + " must not be whitespace only")
    return value


def _labels(value, name, maximum=256):
    bounded_sequence(value, name, maximum=maximum)
    result = [_text(item, name) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(name + " must not contain duplicates")
    return result


def _prose(value, name):
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 65536
        or len(value.encode("utf-8")) > 65536
    ):
        raise ValueError(name + " must be bounded nonempty text")
    return value


def _payload(value):
    bounded_mapping(value, "declared-suite payload", maximum=256)
    bounded_json_value(value)
    return value


class _Inputs:
    def __init__(self, root=None):
        self.deadline = time.monotonic() + 60.0
        if root is not None:
            if not isinstance(root, Path):
                raise ValueError("declared-suite metadata root must be a Path")
            _text(str(root), "metadata root", maximum=4096)
        self.root = root
        self.images = {}
        self.metadata = {}
        self.lookups = {}
        self.source_bytes = 0
        self.output_bytes = 0

    def image(self, boundary, relative, limit):
        check_deadline(self.deadline)
        path, info = contained_file(boundary, relative)
        if info.st_size > limit:
            raise ValueError("declared-suite file byte budget exceeded before read")
        key = path.resolve(strict=True)
        signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if key in self.images:
            raw, previous = self.images[key]
            if previous != signature:
                raise ValueError("declared-suite source changed within one request")
            return raw
        if (
            len(self.images) >= 10000
            or self.source_bytes + info.st_size > 64 * 1024 * 1024
        ):
            raise ValueError("declared-suite aggregate source budget exhausted")
        self.source_bytes += info.st_size
        raw = read_file_image(path, info, limit=limit, deadline=self.deadline)
        self.images[key] = (raw, signature)
        return raw

    def output_row(self, value):
        check_deadline(self.deadline)
        bounded_json_value(value)
        self.output_bytes += (
            len(
                json.dumps(
                    value, ensure_ascii=True, separators=(",", ":"), allow_nan=False
                )
            )
            + 16
        )
        if self.output_bytes > 8 * 1024 * 1024:
            raise ValueError("declared-suite output byte budget exhausted")
        check_deadline(self.deadline)


@contextmanager
def _request(root=None):
    current = _ACTIVE_INPUTS.get()
    if current is not None:
        if root is not None and current.root != root:
            raise ValueError("nested declared-suite metadata roots must agree")
        check_deadline(current.deadline)
        yield current
        return
    current = _Inputs(root)
    token = _ACTIVE_INPUTS.set(current)
    try:
        yield current
    finally:
        _ACTIVE_INPUTS.reset(token)


def _root_request(function):
    @wraps(function)
    def run(root, *args, **kwargs):
        with _request(root) as inputs:
            result = function(root, *args, **kwargs)
            bounded_json_value(result)
            check_deadline(inputs.deadline)
            return result

    return run


def _local_request(function):
    @wraps(function)
    def run(*args, **kwargs):
        with _request() as inputs:
            result = function(*args, **kwargs)
            bounded_json_value(result)
            check_deadline(inputs.deadline)
            return result

    return run


def _load(root: Path, relative: str) -> dict:
    current = _ACTIVE_INPUTS.get()
    if current is None or current.root != root:
        raise ValueError("declared-suite metadata requires its bounded request context")
    relative = relative_source_path(relative)
    if relative not in current.metadata:
        raw = current.image(root, relative, 1024 * 1024)
        current.metadata[relative] = decode_json_object(
            raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000
        )
    check_deadline(current.deadline)
    return current.metadata[relative]


def _owner(value):
    value = relative_source_path(_text(value, "declared owner"))
    if "/" in value:
        raise ValueError("declared owner must be one portable path component")
    return value


def _kind(value):
    value = _text(value, "declared kind")
    if value not in _KINDS:
        raise ValueError("unknown declared-suite kind")
    return value


def _owners(root):
    current = _ACTIVE_INPUTS.get()
    key = "owners"
    if key not in current.lookups:
        registry = _load(root, "registry/declared_outcome_owners.json")
        records = bounded_sequence(
            registry.get("records"), "owner records", maximum=10000
        )
        count = bounded_integer(
            registry.get("record_count"), "owner count", minimum=0, maximum=10000
        )
        if count != len(records):
            raise ValueError("declared owner count differs from records")
        seen = set()
        aliases = {}
        for record in records:
            check_deadline(current.deadline)
            bounded_mapping(record, "owner record", maximum=16)
            kind = _kind(record.get("kind"))
            owner = _owner(record.get("owner"))
            source_id = _text(record.get("source_id"), "outcome identity")
            _text(record.get("state"), "declared state")
            identity = (kind, source_id)
            if identity in seen:
                raise ValueError("duplicate declared outcome identity")
            seen.add(identity)
            alias = member_identity(owner, allow_directory=False)
            if alias in aliases and aliases[alias] != owner:
                raise ValueError("declared owners have ambiguous portable aliases")
            aliases[alias] = owner
        current.lookups[key] = (
            registry,
            {(r["kind"], r["source_id"]): r for r in records},
        )
    return current.lookups[key]


def _contract_rows(root, record):
    current = _ACTIVE_INPUTS.get()
    kind, owner = record["kind"], record["owner"]
    key = ("contracts", kind, owner if kind != "orchestration" else "")
    if key in current.lookups:
        return current.lookups[key]
    if kind == "orchestration":
        data = _load(root, "orchestration/workflows/declared-suite.yaml")
        rows = bounded_sequence(
            data.get("workflows"), "declared workflows", maximum=10000
        )
        if bounded_integer(
            data.get("workflow_count"), "workflow count", minimum=0, maximum=10000
        ) != len(rows):
            raise ValueError("workflow count differs from records")
    else:
        name = (
            "capability-contracts.json" if kind == "skill" else "script-contracts.json"
        )
        data = _load(root, f".px/skills/{owner}/references/{name}")
        rows = bounded_sequence(
            data.get("contracts"), "declared contracts", maximum=10000
        )
    lookup = {}
    for row in rows:
        check_deadline(current.deadline)
        bounded_mapping(row, "declared contract", maximum=64)
        identity = _text(row.get("id"), "contract identity")
        if identity in lookup:
            raise ValueError("duplicate declared contract identity")
        if "owner" in row:
            _owner(row["owner"])
            if kind != "orchestration" and row["owner"] != owner:
                raise ValueError("contract owner differs from selected owner")
        if "kind" in row and row["kind"] != kind:
            raise ValueError("contract kind differs from selected kind")
        _prose(row.get("failure_policy"), "failure policy")
        if kind == "orchestration":
            _prose(row.get("rollback_or_compensation"), "compensation")
            evidence = _labels(row.get("evidence_outputs"), "evidence obligations")
            steps = bounded_sequence(
                row.get("steps"), "workflow steps", minimum=1, maximum=256
            )
            step_ids = []
            for step in steps:
                bounded_mapping(step, "workflow step", maximum=16)
                step_ids.append(_text(step.get("id"), "step identity"))
                _labels(step.get("depends_on", []), "step dependencies")
            if len(step_ids) != len(set(step_ids)):
                raise ValueError("duplicate workflow step identity")
            seen = set()
            for step in steps:
                if not set(step.get("depends_on", [])) <= seen:
                    raise ValueError(
                        "workflow step dependency is not earlier in declared order"
                    )
                seen.add(step["id"])
        else:
            procedure = _labels(row.get("procedure"), "procedure steps")
            if not procedure:
                raise ValueError("declared procedure must not be empty")
            _prose(row.get("recovery"), "recovery")
            evidence = _labels(row.get("evidence"), "evidence obligations")
        if not evidence:
            raise ValueError("declared evidence obligations must not be empty")
        lookup[identity] = row
    current.lookups[key] = lookup
    return lookup


def _stable_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


@_root_request
def list_outcomes(
    root: Path, *, kind: str | None = None, owner: str | None = None
) -> dict:
    if kind is not None:
        kind = _kind(kind)
    if owner is not None:
        owner = _owner(owner)
    registry, _ = _owners(root)
    records = [
        r
        for r in registry["records"]
        if (kind is None or r["kind"] == kind)
        and (owner is None or r["owner"] == owner)
    ]
    return {
        "valid": True,
        "metadata_only": True,
        "count": len(records),
        "records": records,
    }


@_root_request
def describe_outcome(root: Path, kind: str, outcome_id: str) -> dict:
    kind = _kind(kind)
    outcome_id = _text(outcome_id, "outcome identity")
    _, owners = _owners(root)
    record = owners.get((kind, outcome_id))
    if record is None:
        return {
            "valid": False,
            "errors": [f"unknown declared outcome: {kind}/{outcome_id}"],
        }
    contract = _contract_rows(root, record).get(outcome_id)
    if contract is None:
        return {
            "valid": False,
            "errors": [f"declared contract missing: {kind}/{outcome_id}"],
        }
    if "owner" in contract and contract["owner"] != record["owner"]:
        raise ValueError("selected contract owner differs from registry owner")
    return {
        "valid": True,
        "metadata_only": False,
        "owner": record["owner"],
        "contract": contract,
    }


@_root_request
def plan_outcome(
    root: Path, kind: str, outcome_id: str, payload: Mapping[str, Any]
) -> dict:
    _payload(payload)
    _kind(kind)
    _text(outcome_id, "outcome identity")
    target = payload.get("target")
    constraints = payload.get("constraints")
    if target in (None, "", []) or type(constraints) is not dict:
        return {
            "valid": False,
            "errors": ["target and object-valued constraints are required"],
            "outcome": outcome_id,
        }
    described = describe_outcome(root, kind, outcome_id)
    if not described["valid"]:
        return described
    contract = described["contract"]
    procedure = contract.get("procedure") or [step["id"] for step in contract["steps"]]
    return {
        "valid": True,
        "dry_run": True,
        "kind": kind,
        "outcome": outcome_id,
        "owner": described["owner"],
        "target": target,
        "constraints": dict(constraints),
        "ordered_steps": procedure,
        "failure_policy": contract["failure_policy"],
        "recovery": contract.get("recovery")
        or contract.get("rollback_or_compensation"),
        "evidence_required": contract.get("evidence")
        or contract.get("evidence_outputs"),
        "request_sha256": _stable_hash(payload),
    }


@_local_request
def _walk_inventory(target: Path, maximum_files: int) -> list[dict]:
    maximum_files = bounded_integer(
        maximum_files, "inventory file limit", maximum=10000
    )
    if not isinstance(target, Path):
        raise ValueError("inventory target must be a Path")
    _text(str(target), "inventory target", maximum=4096)
    if any(
        part.casefold() in {"quarantine", ".quarantine", "_quarantine"}
        for part in target.parts
    ):
        raise ValueError("inventory target is excluded from acquisition")
    current = _ACTIVE_INPUTS.get()
    check_deadline(current.deadline)
    reject_path_links(target)
    if not target.exists():
        raise ValueError(f"target does not exist: {target}")
    if target.is_file():
        base = target.parent
        locators = [relative_source_path(target.name)]
    else:
        if not target.is_dir():
            raise ValueError("inventory target must be a regular file or directory")
        base = target
        walk = bounded_walk(
            target,
            limits=WalkLimits(
                max_files=maximum_files,
                max_depth=64,
                max_bytes=64 * 1024 * 1024,
                max_entries=20000,
                max_directories=10000,
                max_duration_seconds=max(0.000001, current.deadline - time.monotonic()),
            ),
            symlink_policy="reject",
            exclude=lambda relative: any(
                part.casefold() in {"quarantine", ".quarantine", "_quarantine"}
                for part in relative.split("/")
            ),
        )
        # Match the original bounded Path ordering; no pre-budget global rglob.
        locators = [
            entry.relative for entry in sorted(walk.files, key=lambda entry: entry.path)
        ]
    preflight = []
    total_bytes = 0
    new_images = set()
    for relative in locators:
        check_deadline(current.deadline)
        path, info = contained_file(base, relative)
        if info.st_size > 8 * 1024 * 1024:
            raise ValueError(
                "inventory file byte budget exceeded before body acquisition"
            )
        key = path.resolve(strict=True)
        if key not in current.images and key not in new_images:
            new_images.add(key)
            total_bytes += info.st_size
        if total_bytes + current.source_bytes > 64 * 1024 * 1024:
            raise ValueError(
                "inventory aggregate byte budget exceeded before body acquisition"
            )
        if len(current.images) + len(new_images) > 10000:
            raise ValueError(
                "inventory shared image count exceeded before body acquisition"
            )
        current.output_row(
            {"path": relative, "bytes": info.st_size, "sha256": "0" * 64}
        )
        preflight.append(
            (relative, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
        )
    records = []
    for relative, expected in preflight:
        _, current_info = contained_file(base, relative)
        if (
            current_info.st_dev,
            current_info.st_ino,
            current_info.st_size,
            current_info.st_mtime_ns,
        ) != expected:
            raise ValueError("inventory source changed after preflight")
        raw = current.image(base, relative, 8 * 1024 * 1024)
        row = {
            "path": relative,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        records.append(row)
    return records


@_local_request
def _compare(payload: Mapping[str, Any]) -> dict:
    _payload(payload)
    baseline, candidate = payload.get("baseline"), payload.get("candidate")
    if baseline is None or candidate is None:
        raise ValueError("comparison operations require baseline and candidate")
    if type(baseline) is bool or type(candidate) is bool:
        raise ValueError("numeric comparison cannot coerce booleans")
    if type(baseline) in (int, float) and type(candidate) in (int, float):
        finite_number(baseline, "comparison baseline")
        finite_number(candidate, "comparison candidate")
        delta = candidate - baseline
        finite_number(delta, "comparison delta")
        relative = None if baseline == 0 else delta / abs(baseline)
        if relative is not None:
            finite_number(relative, "relative comparison delta")
        return {
            "baseline": baseline,
            "candidate": candidate,
            "delta": delta,
            "relative_delta": relative,
        }
    left = json.dumps(baseline, sort_keys=True)
    right = json.dumps(candidate, sort_keys=True)
    return {
        "equal": left == right,
        "baseline_sha256": _stable_hash(baseline),
        "candidate_sha256": _stable_hash(candidate),
    }


@_local_request
def _rank(payload: Mapping[str, Any]) -> dict:
    _payload(payload)
    candidates = bounded_sequence(
        payload.get("candidates"), "ranking candidates", minimum=1, maximum=10000
    )
    weights = bounded_mapping(payload.get("weights"), "ranking weights", maximum=256)
    if not weights:
        raise ValueError("ranking weights must not be empty")
    for name, value in weights.items():
        _text(name, "weight identity")
        finite_number(value, "ranking weight")
    current = _ACTIVE_INPUTS.get()
    ranked = []
    seen = set()
    for index, item in enumerate(candidates):
        check_deadline(current.deadline)
        bounded_mapping(item, "ranking candidate", maximum=64)
        identity = _text(item.get("id"), "candidate identity")
        if identity in seen:
            raise ValueError("duplicate candidate identity")
        seen.add(identity)
        metrics = bounded_mapping(item.get("metrics"), "candidate metrics", maximum=256)
        for name, value in metrics.items():
            _text(name, "metric identity")
            finite_number(value, "candidate metric")
        products = [
            finite_number(
                finite_number(metrics.get(name, 0), "weighted metric")
                * finite_number(weight, "ranking weight"),
                "weighted score",
            )
            for name, weight in weights.items()
        ]
        try:
            score = math.fsum(products)
        except OverflowError as error:
            raise ValueError("ranking score is not representable") from error
        finite_number(score, "ranking score")
        row = {"id": identity, "score": score, "input_index": index}
        current.output_row(row)
        ranked.append(row)
    ranked.sort(key=lambda item: (-item["score"], item["id"], item["input_index"]))
    return {"ranked": ranked, "winner": ranked[0]["id"]}


@_local_request
def _scan(payload: Mapping[str, Any]) -> dict:
    _payload(payload)
    text = payload.get("text")
    if type(text) is not str:
        raise ValueError("scan text must be actual text")
    # Generic JSON admission already bounds raw text and escaped serialization.
    patterns = bounded_sequence(payload.get("patterns"), "scan patterns", maximum=256)
    for pattern in patterns:
        if (
            type(pattern) is not str
            or not pattern
            or len(pattern) > 256
            or len(pattern.encode("utf-8")) > 256
        ):
            raise ValueError("scan patterns must be nonempty bounded literal text")
    if len(patterns) != len(set(patterns)):
        raise ValueError("scan patterns must not contain duplicates")
    current = _ACTIVE_INPUTS.get()
    matches = []
    for pattern in patterns:
        check_deadline(current.deadline)
        for match in re.finditer(re.escape(pattern), text, flags=re.IGNORECASE):
            if len(matches) >= 10000:
                raise ValueError("scan match budget exhausted")
            row = {"pattern": pattern, "start": match.start(), "end": match.end()}
            current.output_row(row)
            matches.append(row)
    return {"match_count": len(matches), "matches": matches}


@_local_request
def _validate(payload: Mapping[str, Any]) -> dict:
    _payload(payload)
    record = bounded_mapping(payload.get("record"), "validated record", maximum=10000)
    required = _labels(
        payload.get("required", []), "required field names", maximum=10000
    )
    allowed = (
        None
        if payload.get("allowed") is None
        else _labels(payload["allowed"], "allowed field names", maximum=10000)
    )
    missing = sorted(name for name in required if name not in record)
    allowed_set = None if allowed is None else set(allowed)
    unknown = sorted(
        name for name in record if allowed_set is not None and name not in allowed_set
    )
    return {
        "accepted": not missing and not unknown,
        "missing": missing,
        "unknown": unknown,
    }


@_local_request
def _generate_cases(payload: Mapping[str, Any]) -> dict:
    _payload(payload)
    seed = payload.get("seed")
    if seed is None:
        raise ValueError("case-generation operations require seed")
    cases = [seed, None, {}, [], "", 0, {"unexpected": True}]
    unique, seen = [], set()
    for case in cases:
        fingerprint = _stable_hash(case)
        if fingerprint not in seen:
            seen.add(fingerprint)
            row = {"case": case, "sha256": fingerprint}
            _ACTIVE_INPUTS.get().output_row(row)
            unique.append(row)
    return {"case_count": len(unique), "cases": unique}


@_root_request
def run_script_outcome(root: Path, outcome_id: str, payload: Mapping[str, Any]) -> dict:
    _payload(payload)
    _text(outcome_id, "outcome identity")
    if "maximum_files" in payload:
        bounded_integer(payload["maximum_files"], "inventory file limit", maximum=10000)
    plan = plan_outcome(root, "script", outcome_id, payload)
    if not plan["valid"]:
        return plan
    described = describe_outcome(root, "script", outcome_id)
    if not described["valid"]:
        return described
    words = set(outcome_id.split("-"))
    try:
        if words & {
            "map",
            "mapper",
            "index",
            "inventory",
            "bom",
            "manifest",
            "archive",
            "provenance",
        }:
            target = Path(_text(payload["target"], "inventory target", maximum=4096))
            result = {
                "files": _walk_inventory(target, payload.get("maximum_files", 10000))
            }
        elif words & {"compare", "differential", "regression"}:
            result = _compare(payload)
        elif words & {
            "route",
            "router",
            "rank",
            "planner",
            "calibrator",
            "scorer",
            "budget",
        }:
            result = _rank(payload)
        elif words & {"scan", "scanner", "secret", "injection", "contamination"}:
            result = _scan(payload)
        elif words & {"validate", "validator", "guard", "enforcer", "policy"}:
            result = _validate(payload)
        elif words & {"fuzz", "mutation", "metamorphic", "scenario", "property"}:
            result = _generate_cases(payload)
        else:
            result = {
                "normalized_record": dict(sorted(payload.items())),
                "record_sha256": _stable_hash(payload),
            }
        bounded_json_value(result)
    except (OSError, TypeError, ValueError) as error:
        return {
            "valid": False,
            "outcome": outcome_id,
            "errors": [str(error)],
            "request_sha256": plan.get("request_sha256"),
        }
    return {
        "valid": True,
        "outcome": outcome_id,
        "owner": described["owner"],
        "read_only": True,
        "result": result,
        "result_sha256": _stable_hash(result),
        "plan": plan,
    }


@_root_request
def validate_declared_suite(root: Path) -> dict:
    owners, _ = _owners(root)
    workflows = _load(root, "orchestration/workflows/declared-suite.yaml")
    errors = []
    for record in owners["records"]:
        described = describe_outcome(root, record["kind"], record["source_id"])
        if not described["valid"]:
            errors.extend(described["errors"])
    if owners["record_count"] != 257:
        errors.append(
            f"owner denominator mismatch: declared={owners['record_count']} unique={len(owners['records'])}"
        )
    counts = {
        kind: sum(row["kind"] == kind for row in owners["records"]) for kind in _KINDS
    }
    if counts != {"skill": 134, "script": 61, "orchestration": 62}:
        errors.append(
            "declared outcome kind denominators differ from the registered suite"
        )
    workflow_count = bounded_integer(
        workflows.get("workflow_count"), "workflow count", minimum=0, maximum=10000
    )
    rows = bounded_sequence(workflows.get("workflows"), "workflows", maximum=10000)
    if workflow_count != 62 or workflow_count != len(rows):
        errors.append(f"workflow denominator mismatch: {workflow_count}")
    return {
        "valid": not errors,
        "outcomes": len(owners["records"]),
        "workflows": workflow_count,
        "errors": errors,
    }
