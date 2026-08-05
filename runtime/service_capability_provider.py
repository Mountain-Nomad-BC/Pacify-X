"""Lazy, policy-bound routing for n8n and Supabase capability skills."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
from pathlib import Path
import re

from .json_io import load_json_object


TOKEN = re.compile(r"[a-z0-9][a-z0-9_+.#/-]*", re.IGNORECASE)


def _terms(value: object) -> set[str]:
    return {
        item.casefold().strip("./-")
        for item in TOKEN.findall(str(value))
        if len(item.strip("./-")) > 1
    }


def load_service_catalog(root: Path) -> dict[str, object]:
    catalog = load_json_object(root / "registry/service_capability_catalog.json")
    records = catalog.get("records")
    if catalog.get(
        "loading_rule"
    ) != "metadata_only_at_startup_body_after_selection" or not isinstance(
        records, list
    ):
        raise ValueError("invalid service capability catalog")
    if catalog.get("record_count") != len(records) or len(
        {item.get("id") for item in records}
    ) != len(records):
        raise ValueError("service capability catalog count or identity mismatch")
    if any(item.get("status") != "active" for item in records):
        raise ValueError("service capability catalog contains inactive records")
    return {
        "valid": True,
        "records": tuple(records),
        "record_count": len(records),
        "metadata_only": True,
        "hydrated_bodies": 0,
    }


def _boundary_denial(query: str) -> list[str]:
    normalized = " ".join(_terms(query))
    reasons = []
    if (
        "service-role" in normalized
        or "service_role" in normalized
        or "service role" in query.casefold()
    ):
        if any(
            term in normalized for term in ("client", "browser", "frontend", "mobile")
        ):
            reasons.append("service_role_forbidden_in_client")
    if any(
        phrase in query.casefold()
        for phrase in ("disable rls", "bypass rls", "skip rls")
    ):
        reasons.append("rls_boundary_bypass_requested")
    if any(
        phrase in query.casefold()
        for phrase in ("plaintext secret", "commit credentials", "log password")
    ):
        reasons.append("secret_boundary_violation")
    return sorted(set(reasons))


def route_service_capabilities(
    root: Path, query: str, *, limit: int = 6
) -> dict[str, object]:
    if not query.strip() or not 1 <= limit <= 20:
        raise ValueError("nonblank query and a limit from 1 through 20 are required")
    catalog = load_service_catalog(root)
    denials = _boundary_denial(query)
    query_terms = _terms(query)
    normalized = query.casefold()
    mentions_n8n = "n8n" in query_terms
    mentions_supabase = "supabase" in query_terms
    avoid_n8n = any(
        phrase in normalized
        for phrase in (
            "trivial script",
            "simple deterministic script",
            "ultra-low-latency",
            "high-frequency stream",
        )
    )
    semantic_boosts: dict[str, float] = {}
    if (
        any(
            term in normalized
            for term in ("duplicate", "idempotent", "idempotency", "retry", "delivery")
        )
        and "n8n" in normalized
        and "supabase" in normalized
    ):
        semantic_boosts["design-n8n-supabase-reliability"] = 12.0
    hits = []
    for record in catalog["records"]:
        fields = _terms(
            " ".join(
                [
                    str(record.get("id", "")),
                    str(record.get("description", "")),
                    " ".join(map(str, record.get("domains", ()))),
                    " ".join(map(str, record.get("intents", ()))),
                    " ".join(map(str, record.get("concepts", ()))),
                    " ".join(map(str, record.get("tools", ()))),
                ]
            )
        )
        overlap = query_terms & fields
        score = len(overlap) * 3.0
        identifier = str(record["id"])
        if mentions_n8n and not mentions_supabase and "n8n" not in fields:
            continue
        if mentions_supabase and not mentions_n8n and "supabase" not in fields:
            continue
        for token in identifier.split("-"):
            if token in query_terms:
                score += 1.5
        score += semantic_boosts.get(identifier, 0.0)
        if avoid_n8n and "n8n" in fields:
            score -= 100
        if denials and identifier not in {
            "secure-supabase-rls",
            "design-n8n-supabase-security-boundaries",
            "manage-n8n-credentials",
        }:
            score -= 100
        if score > 0:
            hits.append(
                {
                    "id": identifier,
                    "score": round(score, 6),
                    "matched_terms": sorted(overlap),
                    "effects": record.get("effects", []),
                    "approval_required": any(
                        effect != "read_local" for effect in record.get("effects", ())
                    ),
                    "authority_granted": False,
                }
            )
    hits.sort(key=lambda item: (-float(item["score"]), item["id"]))
    selected = hits[:limit]
    return {
        "valid": bool(selected) and not denials,
        "query": query,
        "selected": selected,
        "denials": denials,
        "metadata_only": True,
        "hydrated_bodies": 0,
        "authority_granted": False,
        "outcome_verification_required": True,
        "errors": denials or ([] if selected else ["no applicable service capability"]),
    }


def hydrate_service_skills(
    root: Path,
    skill_ids: Iterable[str],
    *,
    max_records: int = 3,
    max_bytes: int = 65_536,
) -> dict[str, object]:
    catalog = load_service_catalog(root)
    by_id = {str(item["id"]): item for item in catalog["records"]}
    selected = []
    used = 0
    for identifier in tuple(dict.fromkeys(map(str, skill_ids)))[:max_records]:
        record = by_id.get(identifier)
        if record is None:
            raise KeyError(f"unknown service skill: {identifier}")
        body = root / ".agents/skills" / identifier / "SKILL.md"
        data = body.read_bytes()
        if hashlib.sha256(data).hexdigest() != record.get("body_sha256"):
            raise ValueError(f"service skill body hash drift: {identifier}")
        if used + len(data) > max_bytes:
            break
        selected.append(
            {"id": identifier, "body": data.decode("utf-8"), "bytes": len(data)}
        )
        used += len(data)
    return {
        "valid": bool(selected),
        "skills": selected,
        "bytes_loaded": used,
        "max_bytes": max_bytes,
        "authority_granted": False,
    }


def validate_service_workflows(root: Path) -> dict[str, object]:
    document = load_json_object(root / "registry/service_capability_workflows.json")
    workflows = document.get("workflows", ())
    active = {str(item["id"]) for item in load_service_catalog(root)["records"]}
    framework = {
        str(item.get("id"))
        for item in load_json_object(root / "registry/admission_ledger.json").get(
            "records", ()
        )
        if item.get("status") == "active"
    }
    framework.update(
        str(item.get("id"))
        for item in load_json_object(root / "registry/capability_map.json").get(
            "active_capabilities", ()
        )
    )
    errors = []
    if document.get("workflow_count") != len(workflows):
        errors.append("workflow count mismatch")
    ids = set()
    for workflow in workflows:
        identifier = str(workflow.get("id", ""))
        if not identifier or identifier in ids:
            errors.append(f"invalid or duplicate workflow: {identifier}")
        ids.add(identifier)
        orders = []
        for stage in workflow.get("stages", ()):
            orders.append(int(stage.get("order", 0)))
            capability = str(stage.get("capability", ""))
            if capability not in active | framework:
                errors.append(f"{identifier}: unresolved capability {capability}")
        if orders != list(range(1, len(orders) + 1)):
            errors.append(f"{identifier}: non-contiguous stage order")
        if workflow.get("admission") != "preview_then_apply":
            errors.append(f"{identifier}: unsafe admission mode")
    return {
        "valid": not errors,
        "workflow_count": len(workflows),
        "errors": errors,
        "authority_granted": False,
    }


def evaluate_service_golden_queries(root: Path) -> dict[str, object]:
    cases = load_json_object(
        root / "registry/service_capability_golden_queries.json"
    ).get("cases", ())
    results = []
    for case in cases:
        routed = route_service_capabilities(
            root, str(case["goal"]), limit=int(case.get("max_candidates", 6))
        )
        selected = {item["id"] for item in routed["selected"]}
        missing = sorted(set(map(str, case.get("must_include", ()))) - selected)
        forbidden = sorted(set(map(str, case.get("must_exclude", ()))) & selected)
        results.append(
            {
                "id": case["id"],
                "valid": not missing and not forbidden,
                "missing": missing,
                "forbidden": forbidden,
                "selected": sorted(selected),
            }
        )
    failures = [item for item in results if not item["valid"]]
    return {
        "valid": not failures,
        "case_count": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "results": results,
    }
