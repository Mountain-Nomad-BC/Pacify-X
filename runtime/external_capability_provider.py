"""Governed metadata-first external capability intake and staging.

External candidates are never canonical merely because they rank well or ship
with this framework.  This module searches metadata, plans project-local staged
bindings, governs hooks, normalizes session snapshots, and evaluates routing
economics without executing imported source material.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

from .json_io import load_json_object


CATALOG_PATH = Path("registry/external_capability_catalog.json")
CANDIDATE_PATH = Path("registry/external_capability_candidates.json")
BUNDLE_PATH = Path("registry/external_skill_bundles.json")
LICENSE_PATH = Path("registry/external_capability_licenses.json")
TOKEN = re.compile(r"[a-z0-9][a-z0-9_./+-]*")
STOP = {
    "the",
    "and",
    "or",
    "a",
    "an",
    "to",
    "of",
    "for",
    "in",
    "on",
    "with",
    "when",
    "use",
    "using",
    "skill",
    "agent",
    "code",
    "system",
}
SENSITIVE_KEYS = re.compile(
    r"(?i)(secret|token|password|credential|api[_-]?key|cookie|private[_-]?key)"
)


def _stable(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _terms(value: str) -> list[str]:
    return [
        item
        for item in TOKEN.findall(value.casefold())
        if item not in STOP and len(item) > 1
    ]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def load_external_catalog(root: Path) -> dict[str, object]:
    """Load and validate the non-canonical metadata catalog without hydration."""
    root = root.resolve(strict=True)
    catalog = load_json_object(root / CATALOG_PATH)
    candidates = load_json_object(root / CANDIDATE_PATH)
    bundles = load_json_object(root / BUNDLE_PATH)
    licenses = load_json_object(root / LICENSE_PATH)
    records = catalog.get("records")
    candidate_rows = candidates.get("capabilities")
    bundle_rows = bundles.get("packages")
    if catalog.get("schema_version") != "pacifyx.external-intake.v1" or not isinstance(
        records, list
    ):
        raise ValueError("unsupported external catalog schema")
    if not isinstance(candidate_rows, list) or candidates.get(
        "capability_count"
    ) != len(candidate_rows):
        raise ValueError("external candidate capability count mismatch")
    if not isinstance(bundle_rows, list) or bundles.get("package_count") != len(
        bundle_rows
    ):
        raise ValueError("external bundle count mismatch")
    identifiers = [str(item.get("id", "")) for item in records]
    if not all(identifiers) or len(identifiers) != len(set(identifiers)):
        raise ValueError("external catalog IDs must be nonempty and unique")
    if any(
        item.get("activation") not in {None, "candidate_only", "requires_admission"}
        for item in [*candidate_rows, *bundle_rows]
    ):
        raise ValueError("external candidate attempts active admission")
    if any(
        item.get("status") not in {None, "mapped_deferred", "reference_only"}
        for item in [*candidate_rows, *bundle_rows]
    ):
        raise ValueError("external candidate lifecycle is not deferred")
    return {
        "valid": True,
        "records": tuple(records),
        "candidates": tuple(candidate_rows),
        "bundles": tuple(bundle_rows),
        "licenses": licenses,
        "record_count": len(records),
        "candidate_count": len(candidate_rows),
        "bundle_count": len(bundle_rows),
        "metadata_only": True,
        "canonical": False,
        "active_registry_mutation": False,
    }


def external_catalog_status(root: Path) -> dict[str, object]:
    catalog = load_external_catalog(root)
    statuses = Counter(
        str(item.get("status", "reference_only")) for item in catalog["records"]
    )
    return {
        "valid": True,
        "record_count": catalog["record_count"],
        "candidate_count": catalog["candidate_count"],
        "bundle_count": catalog["bundle_count"],
        "lifecycle_counts": dict(sorted(statuses.items())),
        "metadata_only": True,
        "canonical": False,
        "authority": "none",
        "active_registry_mutation": False,
    }


def search_external_candidates(
    root: Path,
    query: str,
    *,
    limit: int = 8,
    kinds: Iterable[str] = (),
) -> dict[str, object]:
    if not query.strip() or not 1 <= limit <= 100:
        raise ValueError("nonblank query and limit between 1 and 100 are required")
    catalog = load_external_catalog(root)
    selected_kinds = set(map(str, kinds))
    records = [
        item
        for item in catalog["records"]
        if not selected_kinds or str(item.get("kind")) in selected_kinds
    ]
    query_terms = _terms(query)
    query_counts = Counter(query_terms)
    documents = [
        _terms(
            " ".join(
                [
                    str(item.get("id", "")),
                    str(item.get("title", "")),
                    str(item.get("summary", "")),
                    " ".join(map(str, item.get("keywords", ()) or ())),
                    " ".join(map(str, item.get("aliases", ()) or ())),
                    str(item.get("category", "")),
                    str(item.get("owner", "")),
                ]
            )
        )
        for item in records
    ]
    frequency: Counter[str] = Counter()
    for terms in documents:
        frequency.update(set(terms))
    average = max(1.0, sum(map(len, documents)) / max(1, len(documents)))
    phrase = query.strip().casefold()
    hits = []
    for record, terms in zip(records, documents):
        counts = Counter(terms)
        score = 0.0
        for term, weight in query_counts.items():
            tf = counts.get(term, 0)
            if not tf:
                continue
            df = frequency.get(term, 0)
            inverse = math.log(1 + (len(records) - df + 0.5) / (df + 0.5))
            score += (
                inverse
                * (tf * 2.5)
                / (tf + 1.5 * (1 - 0.72 + 0.72 * len(terms) / average))
                * weight
            )
        identifier = str(record.get("id", "")).casefold()
        title = str(record.get("title", "")).casefold()
        aliases = {str(value).casefold() for value in record.get("aliases", ()) or ()}
        if phrase in {identifier, title}:
            score += 16
        elif phrase in identifier or phrase in title:
            score += 7
        if phrase in aliases:
            score += 12
        if score <= 0:
            continue
        hits.append(
            {
                "id": record["id"],
                "kind": record.get("kind"),
                "title": record.get("title"),
                "summary": record.get("summary"),
                "owner": record.get("owner"),
                "status": record.get("status", "reference_only"),
                "score": round(score, 6),
                "matched_terms": sorted(set(query_terms) & set(terms)),
                "admission_required": True,
                "authority": "none",
                "metadata_only": True,
            }
        )
    hits.sort(key=lambda item: (-float(item["score"]), str(item["id"])))
    return {
        "valid": True,
        "query": query,
        "results": hits[:limit],
        "canonical": False,
        "active_registry_mutation": False,
    }


def hydrate_external_metadata(
    root: Path,
    candidate_ids: Iterable[str],
    *,
    max_records: int = 3,
    max_bytes: int = 32768,
) -> dict[str, object]:
    """Hydrate bounded registry metadata only; never read imported source bodies."""
    if max_records < 1 or max_bytes < 1:
        raise ValueError("positive hydration bounds are required")
    catalog = load_external_catalog(root)
    by_id = {str(item["id"]): item for item in catalog["records"]}
    selected = []
    used = 0
    missing = []
    for identifier in tuple(dict.fromkeys(map(str, candidate_ids)))[:max_records]:
        record = by_id.get(identifier)
        if record is None:
            missing.append(identifier)
            continue
        sanitized = {
            key: value
            for key, value in record.items()
            if key not in {"body", "content", "raw_source"}
        }
        size = len(json.dumps(sanitized, ensure_ascii=False).encode("utf-8"))
        if used + size > max_bytes:
            break
        selected.append(sanitized)
        used += size
    return {
        "valid": not missing,
        "records": selected,
        "missing": missing,
        "used_bytes": used,
        "max_bytes": max_bytes,
        "metadata_only": True,
        "source_bodies_loaded": 0,
        "authority_granted": False,
    }


@dataclass(frozen=True, slots=True)
class SelectiveStagePlan:
    plan_id: str
    project_id: str
    bundle_ids: tuple[str, ...]
    body_sha256: Mapping[str, str]
    collisions: tuple[str, ...]
    unresolved_dependencies: tuple[str, ...]
    active_registry_mutation: bool = False
    authority_granted: bool = False
    apply_requires_review: bool = True


def plan_selective_stage(
    root: Path, project: Path, *, project_id: str, bundle_ids: Iterable[str]
) -> SelectiveStagePlan:
    root = root.resolve(strict=True)
    project = project.resolve(strict=True)
    if not (project / ".engineering-bootstrap/project-management/state.json").is_file():
        raise ValueError("target project is not commissioned")
    catalog = load_external_catalog(root)
    bundles = {str(item["id"]): item for item in catalog["bundles"]}
    selected_ids = tuple(sorted(set(map(str, bundle_ids))))
    if not selected_ids:
        raise ValueError("at least one external bundle is required")
    missing = sorted(set(selected_ids) - set(bundles))
    if missing:
        raise ValueError("unknown external bundles: " + ", ".join(missing))
    hashes: dict[str, str] = {}
    collisions = []
    dependencies = []
    candidate_ids = {str(item["id"]) for item in catalog["candidates"]}
    selected_capability_ids = {
        str(capability_id)
        for identifier in selected_ids
        for capability_id in bundles[identifier].get("candidate_capabilities", ())
    }
    for identifier in selected_ids:
        bundle = bundles[identifier]
        body = root / str(bundle["body"])
        if not body.is_file() or not _inside(body, root):
            raise ValueError(f"external bundle body is unavailable: {identifier}")
        hashes[identifier] = hashlib.sha256(body.read_bytes()).hexdigest()
        if (project / ".px/skills" / identifier).exists():
            collisions.append(identifier)
        for capability_id in bundle.get("candidate_capabilities", ()):
            capability = next(
                (
                    item
                    for item in catalog["candidates"]
                    if item.get("id") == capability_id
                ),
                None,
            )
            if capability is None:
                dependencies.append(str(capability_id))
                continue
            for dependency in capability.get("dependencies", ()):
                if (
                    dependency in candidate_ids
                    and dependency not in selected_capability_ids
                ):
                    dependencies.append(str(dependency))
    payload = {
        "project_id": project_id,
        "bundle_ids": selected_ids,
        "body_sha256": hashes,
        "collisions": sorted(collisions),
        "unresolved_dependencies": sorted(set(dependencies)),
    }
    return SelectiveStagePlan(
        "xcp_" + _stable(payload)[:24],
        project_id,
        selected_ids,
        hashes,
        tuple(sorted(collisions)),
        tuple(sorted(set(dependencies))),
    )


def apply_selective_stage(
    project: Path,
    plan: SelectiveStagePlan,
    *,
    approval_evidence: Iterable[str],
    apply: bool = False,
) -> dict[str, object]:
    """Persist a project binding receipt; active registries and skill bodies remain untouched."""
    project = project.resolve(strict=True)
    evidence = tuple(sorted(set(filter(None, map(str, approval_evidence)))))
    errors = []
    if plan.collisions:
        errors.append("project skill collision")
    if plan.unresolved_dependencies:
        errors.append("candidate dependency remains unresolved")
    if not evidence:
        errors.append("review evidence is required")
    result = {
        "valid": not errors,
        "applied": False,
        "plan": asdict(plan),
        "errors": errors,
        "hard_delete": False,
        "active_registry_mutation": False,
    }
    if not apply or errors:
        return result
    directory = project / ".engineering-bootstrap/external-capabilities/staged"
    target = directory / f"{plan.plan_id}.json"
    receipt = {
        "schema_version": "1.0",
        "plan": asdict(plan),
        "approval_evidence": list(evidence),
        "state": "staged_candidate",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "active_registry_mutation": False,
        "authority_granted": False,
    }
    rendered = json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        existing = load_json_object(target)
        comparable = {
            key: value for key, value in existing.items() if key != "created_utc"
        }
        planned = {key: value for key, value in receipt.items() if key != "created_utc"}
        if comparable != planned:
            raise ValueError("selective stage receipt drift")
    elif not target.exists():
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
    return {
        **result,
        "valid": True,
        "applied": True,
        "receipt": target.relative_to(project).as_posix(),
        "errors": [],
    }


def revoke_selective_stage(
    project: Path, plan_id: str, *, evidence: Iterable[str], apply: bool = False
) -> dict[str, object]:
    project = project.resolve(strict=True)
    source = (
        project
        / ".engineering-bootstrap/external-capabilities/staged"
        / f"{plan_id}.json"
    )
    evidence_ids = tuple(sorted(set(filter(None, map(str, evidence)))))
    if not source.is_file() or not evidence_ids:
        raise ValueError("existing staged plan and revocation evidence are required")
    target = (
        project
        / ".engineering-bootstrap/external-capabilities/revocations"
        / f"{plan_id}.json"
    )
    result = {
        "valid": True,
        "applied": False,
        "plan_id": plan_id,
        "source_preserved": True,
        "hard_delete": False,
    }
    if apply and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {
                    "schema_version": "1.0",
                    "plan_id": plan_id,
                    "state": "revoked",
                    "evidence": list(evidence_ids),
                    "source_receipt": source.relative_to(project).as_posix(),
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                },
                stream,
                indent=2,
            )
            stream.write("\n")
        result.update(
            {"applied": True, "receipt": target.relative_to(project).as_posix()}
        )
    return result


@dataclass(frozen=True, slots=True)
class HookDecision:
    allowed: bool
    reason_codes: tuple[str, ...]
    invocation_token: str
    depth: int
    authority_granted: bool = False


def govern_hook_invocation(
    profile: Mapping[str, object],
    *,
    event: str,
    granted_authorities: Iterable[str],
    invocation_chain: Sequence[str] = (),
) -> HookDecision:
    hook_id = str(profile.get("id", ""))
    max_depth = int(profile.get("max_depth", 1))
    reasons = []
    if not hook_id or profile.get("enabled") is not True:
        reasons.append("hook_disabled_or_invalid")
    if event not in set(map(str, profile.get("events", ()))):
        reasons.append("event_not_allowed")
    required = set(map(str, profile.get("required_authorities", ())))
    if not required <= set(map(str, granted_authorities)):
        reasons.append("authority_missing")
    if hook_id in invocation_chain:
        reasons.append("reentrant_hook")
    if len(invocation_chain) >= max_depth:
        reasons.append("depth_limit")
    token = (
        "hook_"
        + _stable({"id": hook_id, "event": event, "chain": list(invocation_chain)})[:24]
    )
    return HookDecision(
        not reasons,
        tuple(sorted(set(reasons))),
        token,
        len(invocation_chain) + 1,
        False,
    )


def normalize_session_snapshot(
    adapter_id: str, payload: Mapping[str, object]
) -> dict[str, object]:
    """Normalize adapter metadata while excluding raw prompts and secret-bearing values."""
    required = (
        "project_id",
        "session_id",
        "agent_id",
        "state",
        "artifact_refs",
        "evidence_refs",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError("session snapshot is missing: " + ", ".join(missing))
    if any(SENSITIVE_KEYS.search(str(key)) for key in payload):
        raise ValueError("session adapter payload contains prohibited sensitive fields")
    if payload.get("state") not in {
        "active",
        "paused",
        "completed",
        "failed",
        "blocked",
    }:
        raise ValueError("unsupported session state")
    snapshot = {
        "schema_version": "1.0",
        "adapter_id": adapter_id,
        "project_id": str(payload["project_id"]),
        "session_id": str(payload["session_id"]),
        "agent_id": str(payload["agent_id"]),
        "state": str(payload["state"]),
        "branch": str(payload.get("branch", "")) or None,
        "worktree": str(payload.get("worktree", "")) or None,
        "checkpoint": str(payload.get("checkpoint", "")) or None,
        "artifact_refs": sorted(set(map(str, payload.get("artifact_refs", ())))),
        "evidence_refs": sorted(set(map(str, payload.get("evidence_refs", ())))),
        "pending_actions": sorted(set(map(str, payload.get("pending_actions", ())))),
        "authority_granted": False,
    }
    snapshot["snapshot_sha256"] = _stable(snapshot)
    return snapshot


def compare_session_parity(
    left: Mapping[str, object], right: Mapping[str, object]
) -> dict[str, object]:
    fields = (
        "project_id",
        "session_id",
        "agent_id",
        "state",
        "branch",
        "worktree",
        "checkpoint",
        "artifact_refs",
        "evidence_refs",
        "pending_actions",
    )
    differences = [field for field in fields if left.get(field) != right.get(field)]
    return {
        "valid": not differences,
        "differences": differences,
        "adapter_ids": [left.get("adapter_id"), right.get("adapter_id")],
        "authority_equal": left.get("authority_granted") is False
        and right.get("authority_granted") is False,
    }


def rank_execution_routes(
    routes: Iterable[Mapping[str, object]],
    *,
    minimum_quality: float,
    maximum_cost: float,
    maximum_latency_ms: float,
    privacy_class: str,
) -> dict[str, object]:
    """Apply hard safety/quality/privacy gates before cost and latency preference."""
    eligible = []
    rejected = []
    for route in routes:
        reasons = []
        if float(route.get("quality", 0.0)) < minimum_quality:
            reasons.append("quality_below_minimum")
        if float(route.get("cost", float("inf"))) > maximum_cost:
            reasons.append("cost_over_budget")
        if float(route.get("latency_ms", float("inf"))) > maximum_latency_ms:
            reasons.append("latency_over_budget")
        if route.get("authority_valid") is not True:
            reasons.append("authority_invalid")
        if route.get("safety_valid") is not True:
            reasons.append("safety_invalid")
        if privacy_class not in set(map(str, route.get("privacy_classes", ()))):
            reasons.append("privacy_incompatible")
        if reasons:
            rejected.append(
                {"id": str(route.get("id", "")), "reasons": sorted(reasons)}
            )
            continue
        quality = float(route["quality"])
        cost = float(route["cost"])
        latency = float(route["latency_ms"])
        score = (
            quality * 70
            + (1 - cost / max(maximum_cost, 1e-9)) * 15
            + (1 - latency / max(maximum_latency_ms, 1e-9)) * 15
        )
        eligible.append(
            {
                "id": str(route["id"]),
                "score": round(score, 6),
                "quality": quality,
                "cost": cost,
                "latency_ms": latency,
            }
        )
    eligible.sort(key=lambda item: (-float(item["score"]), str(item["id"])))
    return {
        "valid": bool(eligible),
        "selected": eligible[0] if eligible else None,
        "eligible": eligible,
        "rejected": sorted(rejected, key=lambda item: item["id"]),
        "quality_precedes_economics": True,
    }


def validate_external_capability_orchestration(root: Path) -> dict[str, object]:
    path = root / "orchestration/workflows/external-capability-intake.yaml"
    if not path.is_file():
        return {"valid": False, "errors": ["workflow missing"]}
    text = path.read_text(encoding="utf-8")
    required = (
        "inventory",
        "license",
        "search-metadata",
        "overlap",
        "plan-stage",
        "admission",
        "certify",
    )
    missing = [item for item in required if f'"{item}"' not in text]
    try:
        status = external_catalog_status(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [f"catalog invalid: {type(error).__name__}"]}
    return {
        "valid": not missing and status["valid"],
        "errors": [f"missing step: {item}" for item in missing],
        "catalog": status,
        "effects": ["read_local", "write_project_staging"],
    }
