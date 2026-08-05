"""Vendor-neutral backend-service capability discovery and validation."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


BACKEND_DOMAINS = (
    "data",
    "authentication",
    "storage",
    "functions",
    "hosting",
    "model_gateways",
    "observability",
    "payments",
)


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def validate_backend_capability_model(
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Validate a metadata-only catalog without granting provider authority."""
    ids: set[str] = set()
    covered: set[str] = set()
    errors: list[str] = []
    for record in records:
        identifier = str(record.get("id", "")).strip()
        domain = str(record.get("domain", "")).strip()
        if not identifier or identifier in ids:
            errors.append("capability identity missing or duplicated")
        ids.add(identifier)
        if domain not in BACKEND_DOMAINS:
            errors.append(f"{identifier}: unsupported backend domain")
        else:
            covered.add(domain)
        if not str(record.get("provider_adapter", "")).strip():
            errors.append(f"{identifier}: provider adapter missing")
        if not set(map(str, record.get("effects", ()))) <= {
            "read_local",
            "write_workspace",
            "network",
            "external_mutation",
        }:
            errors.append(f"{identifier}: undeclared effect vocabulary")
    missing = sorted(set(BACKEND_DOMAINS) - covered)
    if missing:
        errors.append(f"required domains missing: {missing}")
    result = {
        "valid": bool(records) and not errors,
        "record_count": len(records),
        "covered_domains": sorted(covered),
        "missing_domains": missing,
        "errors": errors,
        "metadata_only": True,
        "hydrated_bodies": 0,
        "authority_granted": False,
    }
    result["catalog_sha256"] = _stable(records)
    return result


def select_backend_capabilities(
    records: Sequence[Mapping[str, object]],
    required_domains: Sequence[str],
    *,
    allowed_effects: Sequence[str] = ("read_local",),
) -> dict[str, object]:
    """Select the least-effect capability for each required neutral domain."""
    required = tuple(dict.fromkeys(map(str, required_domains)))
    unknown = sorted(set(required) - set(BACKEND_DOMAINS))
    allowed = set(map(str, allowed_effects))
    selected = []
    unresolved = list(unknown)
    for domain in required:
        if domain in unknown:
            continue
        candidates = [
            record
            for record in records
            if record.get("domain") == domain
            and set(map(str, record.get("effects", ()))) <= allowed
        ]
        candidates.sort(
            key=lambda record: (
                len(set(map(str, record.get("effects", ())))),
                float(record.get("cost", 0.0)),
                str(record.get("id", "")),
            )
        )
        if not candidates:
            unresolved.append(domain)
            continue
        selected.append(
            {
                "domain": domain,
                "id": str(candidates[0]["id"]),
                "provider_adapter": str(candidates[0]["provider_adapter"]),
                "effects": sorted(set(map(str, candidates[0].get("effects", ())))),
            }
        )
    return {
        "valid": not unresolved,
        "selected": selected,
        "unresolved_domains": sorted(set(unresolved)),
        "metadata_only": True,
        "hydrated_bodies": 0,
        "authority_granted": False,
    }
