"""Governed metadata-first cybersecurity capability provider.

The provider catalog is untrusted reference material.  Discovery and bounded
body hydration do not grant tool authority, admit a skill, or authorize a
security action.  Authority is evaluated before ranking and again before an
execution package can be considered eligible.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Mapping, Sequence
import zipfile

from .archive_io import preflight_zip_directory
from .json_io import bounded_strings, decode_json_object, load_json_object, read_bounded_bytes


PROVIDER_DIR = Path("registry/security_capabilities")
CATALOG_PATH = PROVIDER_DIR / "capabilities.jsonl"
GRAPH_PATH = PROVIDER_DIR / "graph.jsonl"
DOMAINS_PATH = PROVIDER_DIR / "domains.json"
RISKS_PATH = PROVIDER_DIR / "risk_classes.json"
ALIASES_PATH = PROVIDER_DIR / "intent_aliases.json"
PROVIDER_PATH = PROVIDER_DIR / "provider.json"
SOURCE_PATH = PROVIDER_DIR / "source.json"
EXPECTED_RECORDS = 817
EXPECTED_EDGES = 14_595
EXPECTED_SOURCE_CATALOG_SHA256 = "89414cdd740d5d442db2ae7206c99bc848b182c947ce7295c7d04b7607c9e877"
EXPECTED_PROJECTED_CATALOG_SHA256 = "3cb4557f547903501fee07e1a0d6aa0137668962157f3b9cad6ea7042e91bd4a"
EXPECTED_GRAPH_SHA256 = "80ff41da7ba8d327112280894eacc30647cd8111614a6a38bf0f29c9eca207ae"
EXPECTED_ARCHIVE_SHA256 = (
    "460f2ed54dac3bc96a453d2fd30c098234df80d3840fda475ba95b1e3983a08f"
)
TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:+/-]*")
STOP = {
    "the",
    "and",
    "or",
    "for",
    "with",
    "from",
    "into",
    "when",
    "use",
    "using",
    "security",
    "skill",
}
RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}
HIGH_RISK = {"R3", "R4"}
_EXECUTION_POLICIES = dict(zip(RISK_ORDER, ("advisory_only", "read_only_defensive", "controlled_change", "gated_active_test", "lab_only_knowledge_by_default")))
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_000
MAX_HYDRATION_BYTES = 1024 * 1024
_RECORD_BOOLEANS = frozenset({"credential_access_potential", "destructive_potential", "requires_explicit_scope", "requires_human_approval", "requires_written_authorization"})
_RECORD_LISTS = frozenset({"avoid_when", "conflicts_with", "negative_matches", "related_skills", "risk_reasons", "tags"})
_RECORD_STRINGS = frozenset({
    "author", "body_hydration", "body_sha256", "canonical_domain", "description", "execution_policy",
    "id", "kind", "license", "lifecycle_state", "name", "network_egress_default", "production_execution_default",
    "risk_class", "source_affiliation_note", "source_path", "source_project_name", "source_provider", "source_subdomain", "version",
})
_FRAMEWORKS = frozenset({"atlas_techniques", "d3fend_techniques", "mitre_attack", "mitre_f3", "nist_ai_rmf", "nist_csf"})


def _string_array(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise ValueError("security metadata collection must be an array")
    return bounded_strings(value, max_items=256)


def _framework_ids(framework: str, value: object) -> tuple[str, ...]:
    if type(value) is list:
        return _string_array(value)
    if framework != "mitre_f3" or type(value) is not dict or set(value) != {"tactics", "techniques", "version"}:
        raise ValueError("invalid security framework mapping")
    _string_array(value["tactics"])
    bounded_strings((value["version"],), max_item_bytes=128)
    techniques = value["techniques"]
    if type(techniques) is not list or len(techniques) > 256:
        raise ValueError("invalid security framework techniques")
    identifiers = []
    for item in techniques:
        if type(item) is not dict or set(item) != {"id", "name", "source", "tactic"}:
            raise ValueError("invalid security framework technique")
        bounded_strings(item.values())
        identifiers.append(item["id"])
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate security framework technique")
    return tuple(identifiers)


def validate_security_metadata(records: Sequence[dict], graph: Sequence[dict] | None = None) -> None:
    """Shared producer/consumer contract for the provider's complete metadata."""
    if len(records) != EXPECTED_RECORDS:
        raise ValueError("security catalog record denominator mismatch")
    names = set()
    expected_edges = set()
    for row in records:
        if type(row) is not dict or set(row) != _RECORD_BOOLEANS | _RECORD_LISTS | _RECORD_STRINGS | {"files", "frameworks"}:
            raise ValueError("invalid complete security capability record")
        for key in _RECORD_BOOLEANS:
            if type(row[key]) is not bool:
                raise ValueError(f"security capability flag must be boolean: {key}")
        for key in _RECORD_STRINGS:
            bounded_strings((row[key],), max_item_bytes=32_768)
        for key in _RECORD_LISTS:
            _string_array(row[key])
        name = row["name"]
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None or name in names:
            raise ValueError("invalid or duplicate security capability name")
        names.add(name)
        if row["id"] != "external.cybersecurity." + name or row["source_path"] != "skills/" + name:
            raise ValueError("security capability source identity mismatch")
        if row["source_provider"] != "anthropic-cybersecurity-skills-community" or row["kind"] != "external_skill":
            raise ValueError("security capability provider identity mismatch")
        risk = row["risk_class"]
        if risk not in RISK_ORDER or row["execution_policy"] != _EXECUTION_POLICIES[risk]:
            raise ValueError("security capability risk/execution contract mismatch")
        if row["lifecycle_state"] != "candidate_external" or row["body_hydration"] != "on_demand_after_selection":
            raise ValueError("external security capability is not deferred reference material")
        if risk in HIGH_RISK and (row["requires_human_approval"] is not True or row["requires_written_authorization"] is not True):
            raise ValueError("high-risk security capability lacks required gates")
        if len(row["description"]) < 20 or not row["canonical_domain"] or not row["source_subdomain"]:
            raise ValueError("security capability descriptive contract is incomplete")
        files = row["files"]
        if type(files) is not list or not 1 <= len(files) <= 64:
            raise ValueError("security capability file denominator is invalid")
        file_paths = set()
        for item in files:
            if type(item) is not dict or set(item) != {"path", "sha256", "size_bytes"}:
                raise ValueError("invalid security capability file record")
            path = item["path"]
            bounded_strings((path,))
            if (path in file_paths or "\\" in path or ".." in PurePosixPath(path).parts
                    or not path.startswith(row["source_path"] + "/")):
                raise ValueError("duplicate or uncontained capability file path")
            file_paths.add(path)
            if type(item["size_bytes"]) is not int or not 0 <= item["size_bytes"] <= 64 * 1024 * 1024:
                raise ValueError("invalid security capability file size")
            if type(item["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None:
                raise ValueError("invalid security capability file hash")
        body = next((item for item in files if item["path"] == row["source_path"] + "/SKILL.md"), None)
        if body is None or body["sha256"] != row["body_sha256"]:
            raise ValueError("security capability body/file identity mismatch")
        frameworks = row["frameworks"]
        if type(frameworks) is not dict or set(frameworks) != _FRAMEWORKS:
            raise ValueError("invalid security capability framework denominator")
        source = "skill:" + name
        if graph is not None:
            expected_edges.add((source, "member_of", "security-domain:" + row["canonical_domain"], "normalized-frontmatter"))
            expected_edges.update((source, "tagged_with", "concept:" + tag, "frontmatter") for tag in row["tags"])
            expected_edges.update((source, "related_to", "skill:" + other, "related-skills-section") for other in row["related_skills"])
        for framework, values in frameworks.items():
            identifiers = _framework_ids(framework, values)
            if graph is not None:
                expected_edges.update((source, "mapped_to", framework + ":" + value, "frontmatter") for value in identifiers)
    if any(set(row["related_skills"]) - names for row in records):
        raise ValueError("unknown related security capability")
    if graph is not None:
        actual = set()
        if len(graph) != EXPECTED_EDGES:
            raise ValueError("security graph edge denominator mismatch")
        for edge in graph:
            if type(edge) is not dict or set(edge) != {"from", "to", "type", "source"}:
                raise ValueError("invalid security graph edge schema")
            bounded_strings(edge.values())
            key = (edge["from"], edge["type"], edge["to"], edge["source"])
            if key in actual:
                raise ValueError("duplicate security graph edge")
            actual.add(key)
        if actual != expected_edges:
            raise ValueError("security graph relationships do not match capability metadata")


def validate_security_declarations(records: Sequence[dict], domains: dict, risks: dict) -> None:
    """Keep builder and runtime domain/risk denominators on the same contract."""
    raw = Counter(row["source_subdomain"] for row in records)
    canonical = Counter(row["canonical_domain"] for row in records)
    for field, expected in (("raw_counts", raw), ("canonical_counts", canonical)):
        counts = domains.get(field)
        if (type(counts) is not dict or any(type(v) is not int or v < 1 for v in counts.values())
                or counts != dict(expected)):
            raise ValueError(f"security domain declaration mismatch: {field}")
    for field, expected in (("source_raw_domain_count", len(raw)), ("canonical_domain_count", len(canonical))):
        if type(domains.get(field)) is not int or domains[field] != expected:
            raise ValueError(f"security domain count mismatch: {field}")
    if set(risks) != set(RISK_ORDER):
        raise ValueError("security risk class denominator mismatch")
    for risk, row in risks.items():
        if type(row) is not dict or set(row) != {"authority", "default_execution", "examples", "name"}:
            raise ValueError("invalid security risk class declaration")
        bounded_strings((row["authority"], row["name"]))
        _string_array(row["examples"])
        if row["default_execution"] != _EXECUTION_POLICIES[risk]:
            raise ValueError("security risk execution declaration mismatch")


def decode_security_jsonl(raw: bytes | bytearray, *, expected_sha256: str | None = None) -> tuple[dict[str, object], ...]:
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("security JSONL byte budget exceeded")
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("security metadata pinned source hash mismatch")
    rows: list[dict[str, object]] = []
    used = 0
    with io.BytesIO(raw) as stream:
        for number in range(20_001):
            line = stream.readline(min(65_537, 16 * 1024 * 1024 + 1 - used))
            if not line:
                break
            used += len(line)
            if number >= 20_000 or len(line) > 65_536 or used > 16 * 1024 * 1024:
                raise ValueError("security JSONL byte, line or record budget exceeded")
            if not line.strip():
                continue
            value = decode_json_object(line, max_bytes=65_536)
            rows.append(value)
    return tuple(rows)


def _jsonl(path: Path, *, expected_sha256: str | None = None) -> tuple[dict[str, object], ...]:
    return decode_security_jsonl(read_bounded_bytes(path, max_bytes=16 * 1024 * 1024), expected_sha256=expected_sha256)


def _terms(value: str) -> list[str]:
    return [
        term
        for term in TOKEN.findall(value.casefold())
        if len(term) > 1 and term not in STOP
    ]


def _stable(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_security_provider(
    root: Path, *, load_graph: bool = False
) -> dict[str, object]:
    """Load and reconcile the provider without reading any source skill body."""
    root = root.resolve(strict=True)
    provider = load_json_object(root / PROVIDER_PATH, max_bytes=1024 * 1024)
    source = load_json_object(root / SOURCE_PATH, max_bytes=1024 * 1024)
    domains = load_json_object(root / DOMAINS_PATH, max_bytes=1024 * 1024)
    risks = load_json_object(root / RISKS_PATH, max_bytes=1024 * 1024)
    aliases = load_json_object(root / ALIASES_PATH, max_bytes=1024 * 1024)
    records = _jsonl(root / CATALOG_PATH, expected_sha256=EXPECTED_PROJECTED_CATALOG_SHA256)
    validate_security_metadata(records)
    validate_security_declarations(records, domains, risks)
    identifiers = [str(row.get("id", "")) for row in records]
    errors: list[str] = []
    if provider.get("provider_id") != "anthropic-cybersecurity-skills-community":
        errors.append("provider identity mismatch")
    if source.get("archive_sha256") != EXPECTED_ARCHIVE_SHA256:
        errors.append("source archive hash declaration mismatch")
    if source.get("catalog_sha256") != EXPECTED_SOURCE_CATALOG_SHA256 or source.get("graph_sha256") != EXPECTED_GRAPH_SHA256:
        errors.append("pinned provider source declaration mismatch")
    if (provider.get("activation") != "candidate_only" or provider.get("execution_enabled") is not False
            or type(provider.get("provider_scripts_admitted")) is not int or provider["provider_scripts_admitted"] != 0):
        errors.append("provider cannot declare execution admission")
    if (
        len(records) != EXPECTED_RECORDS
        or len(set(identifiers)) != EXPECTED_RECORDS
        or not all(identifiers)
    ):
        errors.append("catalog must contain 817 unique nonempty IDs")
    raw = Counter(str(row.get("source_subdomain", "")) for row in records)
    canonical = Counter(str(row.get("canonical_domain", "")) for row in records)
    risk_counts = Counter(str(row.get("risk_class", "")) for row in records)
    for field, expected in (("canonical_domain_count", len(canonical)), ("source_raw_domain_count", len(raw))):
        if type(domains.get(field)) is not int or domains[field] != expected:
            errors.append(f"domain count mismatch: {field}")
    for field in ("raw_counts", "canonical_counts"):
        counts = domains.get(field)
        if type(counts) is not dict or any(type(v) is not int or v < 1 for v in counts.values()):
            errors.append(f"invalid domain count declarations: {field}")
    if set(risks) != set(RISK_ORDER) or any(type(risks.get(risk)) is not dict or risks[risk].get("default_execution") != _EXECUTION_POLICIES[risk] for risk in RISK_ORDER):
        errors.append("risk class declaration mismatch")
    if sum(raw.values()) != EXPECTED_RECORDS or dict(
        sorted(raw.items())
    ) != domains.get("raw_counts"):
        errors.append("raw domain reconciliation failed")
    if sum(canonical.values()) != EXPECTED_RECORDS or dict(
        sorted(canonical.items())
    ) != domains.get("canonical_counts"):
        errors.append("canonical domain reconciliation failed")
    if sum(risk_counts.values()) != EXPECTED_RECORDS or set(risk_counts) != set(
        RISK_ORDER
    ):
        errors.append("risk reconciliation failed")
    for row in records:
        risk = str(row.get("risk_class", ""))
        if row.get("lifecycle_state") != "candidate_external":
            errors.append(f"active external record: {row.get('id')}")
        if risk in HIGH_RISK and (
            row.get("requires_human_approval") is not True
            or row.get("requires_written_authorization") is not True
        ):
            errors.append(f"ungated high-risk record: {row.get('id')}")
        if (
            risk == "R4"
            and row.get("execution_policy") != "lab_only_knowledge_by_default"
        ):
            errors.append(f"R4 record is not lab/knowledge only: {row.get('id')}")
        body_hash = str(row.get("body_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", body_hash):
            errors.append(f"invalid body hash: {row.get('id')}")
    graph: tuple[dict[str, object], ...] = ()
    if load_graph:
        graph = _jsonl(root / GRAPH_PATH, expected_sha256=EXPECTED_GRAPH_SHA256)
        validate_security_metadata(records, graph)
        if len(graph) != EXPECTED_EDGES:
            errors.append("security graph edge count mismatch")
    if errors:
        raise ValueError("; ".join(errors[:25]))
    return {
        "valid": True,
        "provider": provider,
        "source": source,
        "domains": domains,
        "risks": risks,
        "aliases": aliases,
        "records": records,
        "graph": graph,
        "record_count": len(records),
        "edge_count": len(graph) if load_graph else None,
        "expected_edge_count": EXPECTED_EDGES,
        "graph_loaded": load_graph,
        "raw_domain_count": len(raw),
        "canonical_domain_count": len(canonical),
        "raw_counts": dict(sorted(raw.items())),
        "canonical_counts": dict(sorted(canonical.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "metadata_only": True,
        "provider_scripts_executable": False,
        "authority_granted": False,
    }


def security_provider_status(root: Path) -> dict[str, object]:
    state = load_security_provider(root)
    return {
        key: value
        for key, value in state.items()
        if key not in {"records", "graph", "aliases", "domains", "risks"}
    }


def _document(record: Mapping[str, object]) -> str:
    frameworks = record.get("frameworks", {})
    framework_values: list[str] = []
    if isinstance(frameworks, Mapping):
        for values in frameworks.values():
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                framework_values.extend(map(str, values))
    return " ".join(
        [
            str(record.get("id", "")),
            str(record.get("name", "")),
            str(record.get("description", "")),
            str(record.get("source_subdomain", "")),
            str(record.get("canonical_domain", "")),
            " ".join(map(str, record.get("tags", ()) or ())),
            " ".join(framework_values),
        ]
    )


def search_security_capabilities(
    root: Path,
    query: str,
    *,
    limit: int = 10,
    provider_enabled: bool = True,
    include_descriptions: bool = False,
) -> dict[str, object]:
    """Search independent metadata paths and return candidate-only explanations.

    External descriptions participate in ranking but stay out of the default
    result payload.  Callers must explicitly opt in before placing untrusted,
    potentially security-sensitive prose in an interactive transcript.
    """
    if not query.strip() or not 1 <= limit <= 100:
        raise ValueError("nonblank query and limit between 1 and 100 are required")
    if not provider_enabled:
        return {
            "valid": True,
            "query": query,
            "results": [],
            "provider_disabled": True,
            "source_bodies_loaded": 0,
            "authority_granted": False,
        }
    state = load_security_provider(root)
    records = list(state["records"])
    aliases = state["aliases"]
    query_terms = _terms(query)
    expanded = set(query_terms)
    alias_matches: set[str] = set()
    if isinstance(aliases, Mapping):
        for domain, values in aliases.items():
            phrases = [
                str(domain),
                *map(str, values if isinstance(values, list) else []),
            ]
            if any(phrase.casefold() in query.casefold() for phrase in phrases):
                expanded.update(_terms(str(domain)))
                alias_matches.add(str(domain))
    documents = [_terms(_document(row)) for row in records]
    frequency: Counter[str] = Counter()
    for terms in documents:
        frequency.update(set(terms))
    average = max(1.0, sum(map(len, documents)) / len(documents))
    hits: list[dict[str, object]] = []
    for row, terms in zip(records, documents):
        counts = Counter(terms)
        components = {"text": 0.0, "domain": 0.0, "framework": 0.0, "alias": 0.0}
        for term in expanded:
            tf = counts.get(term, 0)
            if tf:
                df = frequency.get(term, 0)
                inverse = math.log(1 + (len(records) - df + 0.5) / (df + 0.5))
                components["text"] += (
                    inverse
                    * (tf * 2.5)
                    / (tf + 1.5 * (1 - 0.72 + 0.72 * len(terms) / average))
                )
        domain = str(row.get("canonical_domain", ""))
        source_domain = str(row.get("source_subdomain", ""))
        query_words = set(re.findall(r"[a-z0-9]+", query.casefold()))
        domain_terms = set(re.findall(r"[a-z0-9]+", domain.casefold()))
        source_domain_terms = set(re.findall(r"[a-z0-9]+", source_domain.casefold()))
        if (
            domain.casefold() in query.casefold()
            or source_domain.casefold() in query.casefold()
            or (domain_terms and domain_terms <= query_words)
            or (source_domain_terms and source_domain_terms <= query_words)
        ):
            components["domain"] = 8.0
        if domain in alias_matches:
            components["alias"] = 6.0
        framework_ids = {
            str(value).casefold()
            for values in (row.get("frameworks", {}) or {}).values()
            for value in (values or [])
        }
        if any(value in query.casefold() for value in framework_ids):
            components["framework"] = 10.0
        score = sum(components.values())
        if score <= 0:
            continue
        hit = {
                "id": row["id"],
                "name": row.get("name"),
                "source_subdomain": source_domain,
                "canonical_domain": domain,
                "risk_class": row.get("risk_class"),
                "execution_policy": row.get("execution_policy"),
                "score": round(score, 6),
                "score_components": {
                    key: round(value, 6) for key, value in components.items()
                },
                "matched_terms": sorted(set(expanded) & set(terms)),
                "lifecycle_state": "candidate_external",
                "metadata_untrusted": True,
                "authority_granted": False,
                "admission_required": True,
            }
        if include_descriptions:
            hit["description"] = row.get("description")
        hits.append(hit)
    hits.sort(key=lambda item: (-float(item["score"]), str(item["id"])))
    return {
        "valid": True,
        "query": query,
        "results": hits[:limit],
        "independent_paths": ["text", "domain", "alias", "framework"],
        "source_bodies_loaded": 0,
        "descriptions_included": include_descriptions,
        "authority_granted": False,
    }


def evaluate_security_golden_queries(root: Path) -> dict[str, object]:
    cases = load_json_object(
        root.resolve(strict=True) / PROVIDER_DIR / "golden_queries.json"
    ).get("cases", [])
    results = []
    for case in cases:
        routed = search_security_capabilities(
            root, str(case["query"]), limit=int(case.get("top_k", 10))
        )
        domains = [str(item["canonical_domain"]) for item in routed["results"]]
        expected = str(case["expected_domain"])
        results.append(
            {
                "id": case["id"],
                "passed": expected in domains,
                "expected_domain": expected,
                "returned_domains": domains,
            }
        )
    passed = sum(bool(item["passed"]) for item in results)
    return {
        "valid": passed == len(results) and bool(results),
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    decision: str
    risk_class: str
    reasons: tuple[str, ...]
    required_gates: tuple[str, ...]
    authority_granted: bool = False


def evaluate_security_authority(
    risk_class: str,
    engagement: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> SecurityDecision:
    """Evaluate authority before semantic ranking; never grant runtime authority."""
    if risk_class not in RISK_ORDER:
        return SecurityDecision(
            "abstain", risk_class, ("unknown_risk_class",), ("risk_classification",)
        )
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    mode = str(engagement.get("mode", ""))
    environment = str(engagement.get("environment", ""))
    targets = set(map(str, engagement.get("targets", ()) or ()))
    allowlist = set(map(str, engagement.get("target_allowlist", ()) or ()))
    denylist = set(map(str, engagement.get("target_denylist", ()) or ()))
    authorization = engagement.get("authorization", {})
    if not isinstance(authorization, Mapping):
        authorization = {}
    reasons: list[str] = []
    gates: list[str] = []
    if not targets:
        reasons.append("targets_missing")
    if targets & denylist:
        reasons.append("target_denied")
    if risk_class == "R0":
        return (
            SecurityDecision("allow", risk_class, tuple(reasons), tuple(gates))
            if not reasons
            else SecurityDecision(
                "abstain", risk_class, tuple(reasons), ("target_context",)
            )
        )
    if not allowlist or not targets <= allowlist:
        reasons.append("target_outside_allowlist")
        gates.append("target_allowlist")
    if risk_class == "R1":
        if mode not in {"advisory", "read_only"}:
            reasons.append("read_only_mode_required")
        decision = "allow_read_only" if not reasons else "deny"
        return SecurityDecision(
            decision, risk_class, tuple(sorted(set(reasons))), tuple(sorted(set(gates)))
        )
    if authorization.get("status") != "approved":
        reasons.append("written_authorization_not_approved")
    for field in ("artifact_id", "approved_by", "valid_from", "valid_until"):
        if not authorization.get(field):
            reasons.append(f"authorization_{field}_missing")
    valid_from = _parse_time(authorization.get("valid_from"))
    valid_until = _parse_time(authorization.get("valid_until"))
    if (
        valid_from is None
        or valid_until is None
        or not (valid_from <= now <= valid_until)
    ):
        reasons.append("authorization_outside_valid_window")
    if engagement.get("human_approval") is not True:
        reasons.append("human_approval_missing")
    gates.extend(["written_authorization", "human_approval", "target_allowlist"])
    if risk_class == "R2":
        if mode != "controlled_change":
            reasons.append("controlled_change_mode_required")
        for field in (
            "change_window",
            "rollback_plan",
            "cleanup_plan",
            "evidence_root",
        ):
            if not engagement.get(field):
                reasons.append(f"{field}_missing")
                gates.append(field)
        return SecurityDecision(
            "allow" if not reasons else "deny",
            risk_class,
            tuple(sorted(set(reasons))),
            tuple(sorted(set(gates))),
        )
    rules = authorization.get("rules_of_engagement", ())
    if not isinstance(rules, list) or not rules:
        reasons.append("rules_of_engagement_missing")
    if not engagement.get("cleanup_plan"):
        reasons.append("cleanup_plan_missing")
    if not engagement.get("kill_switch"):
        reasons.append("kill_switch_missing")
    gates.extend(["rules_of_engagement", "cleanup", "kill_switch"])
    if (
        environment == "production"
        and engagement.get("exceptional_production_approval") is not True
    ):
        reasons.append("active_production_denied_by_default")
    if risk_class == "R3":
        if mode not in {"active_test", "lab_simulation"}:
            reasons.append("active_test_or_lab_mode_required")
        return SecurityDecision(
            "allow" if not reasons else "deny",
            risk_class,
            tuple(sorted(set(reasons))),
            tuple(sorted(set(gates))),
        )
    if environment != "isolated_lab" or mode != "lab_simulation":
        reasons.append("R4_isolated_lab_only")
    return SecurityDecision(
        "allow_lab_only" if not reasons else "deny",
        risk_class,
        tuple(sorted(set(reasons))),
        tuple(sorted(set(gates))),
    )


def expand_security_graph(
    root: Path,
    skill_names: Iterable[str],
    *,
    depth: int = 2,
    max_nodes: int = 250,
    max_edges: int = 1000,
) -> dict[str, object]:
    if (type(depth) is not int or not 0 <= depth <= 4
            or type(max_nodes) is not int or not 1 <= max_nodes <= 10_000
            or type(max_edges) is not int or not 1 <= max_edges <= 20_000):
        raise ValueError("invalid graph bounds")
    seeds = sorted(bounded_strings(skill_names, max_items=4096, max_item_bytes=256, max_bytes=262_144))
    edges = load_security_provider(root, load_graph=True)["graph"]
    adjacency: dict[str, list[dict[str, object]]] = defaultdict(list)
    for edge in edges:
        adjacency[str(edge.get("from", ""))].append(edge)
    queue = deque((f"skill:{name}", 0) for name in seeds[:max_nodes])
    seen = {node for node, _ in queue}
    selected: list[dict[str, object]] = []
    truncated = len(seeds) > max_nodes
    while queue:
        node, level = queue.popleft()
        if level >= depth:
            continue
        for edge in adjacency.get(node, ()):
            if len(selected) >= max_edges:
                truncated = True
                queue.clear()
                break
            target = str(edge.get("to", ""))
            if target not in seen:
                if len(seen) >= max_nodes:
                    truncated = True
                    continue
                seen.add(target)
                queue.append((target, level + 1))
            selected.append(edge)
    return {
        "valid": True,
        "nodes": sorted(seen),
        "edges": selected,
        "depth": depth,
        "truncated": truncated,
        "budgets": {"max_nodes": max_nodes, "max_edges": max_edges},
    }


def build_security_execution_package(
    root: Path,
    query: str,
    engagement: Mapping[str, object],
    *,
    max_bodies: int = 5,
    max_risk: str = "R4",
) -> dict[str, object]:
    """Filter authority first, then rank and form a candidate context package."""
    if max_risk not in RISK_ORDER or not 1 <= max_bodies <= 15:
        raise ValueError("max_risk must be R0-R4 and max_bodies must be 1-15")
    state = load_security_provider(root)
    rows = {str(row["id"]): row for row in state["records"]}
    ranked = search_security_capabilities(root, query, limit=100)["results"]
    selected: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for hit in ranked:
        record = rows[str(hit["id"])]
        risk = str(record["risk_class"])
        if RISK_ORDER[risk] > RISK_ORDER[max_risk]:
            rejected.append(
                {"id": record["id"], "reasons": ["risk_above_request_limit"]}
            )
            continue
        decision = evaluate_security_authority(risk, engagement)
        if decision.decision not in {"allow", "allow_read_only", "allow_lab_only"}:
            rejected.append({"id": record["id"], "reasons": list(decision.reasons)})
            continue
        selected.append({**hit, "authority_decision": asdict(decision)})
        if len(selected) >= max_bodies:
            break
    package = {
        "query": query,
        "engagement_id": engagement.get("engagement_id"),
        "selected": selected,
        "rejected": rejected,
        "max_bodies": max_bodies,
        "candidate_context_only": True,
        "runtime_authority_granted": False,
        "provider_scripts_executable": False,
    }
    package["package_id"] = "sec_pkg_" + _stable(package)[:24]
    package["valid"] = bool(selected)
    package["decision"] = "candidate_package" if selected else "deny_or_abstain"
    return package


def _preflight_archive(raw: bytes | bytearray) -> None:
    """Use the shared bounded directory check with the pinned provider limits."""
    preflight_zip_directory(raw, max_members=MAX_ARCHIVE_ENTRIES)


def hydrate_security_bodies(
    root: Path,
    archive: Path,
    capability_ids: Iterable[str],
    *,
    max_bodies: int = 5,
    max_bytes: int = 262_144,
) -> dict[str, object]:
    """Read selected Markdown bodies from a verified archive without extracting files."""
    if (type(max_bodies) is not int or not 1 <= max_bodies <= 15
            or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_HYDRATION_BYTES):
        raise ValueError("invalid hydration bounds")
    requested = bounded_strings(capability_ids, max_item_bytes=256)
    if not requested:
        raise ValueError("security hydration requires a nonempty selection")
    if len(requested) > max_bodies:
        raise ValueError("hydration body limit exceeded")
    archive = archive.resolve(strict=True)
    if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("provider archive byte budget exceeded or not a regular file")
    raw = read_bounded_bytes(archive, max_bytes=MAX_ARCHIVE_BYTES)
    archive_hash = hashlib.sha256(raw).hexdigest()
    if archive_hash != EXPECTED_ARCHIVE_SHA256:
        raise ValueError("provider archive hash mismatch")
    records = {str(row["id"]): row for row in load_security_provider(root)["records"]}
    missing = sorted(set(requested) - set(records))
    if missing:
        raise ValueError("unknown security capability IDs: " + ", ".join(missing))
    hydrated: list[dict[str, object]] = []
    used = 0
    _preflight_archive(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        infos = source.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise ValueError("provider archive entry budget exceeded")
        selected_members = []
        declared_bytes = 0
        for identifier in requested:
            record = records[identifier]
            relative = PurePosixPath(str(record["source_path"])) / "SKILL.md"
            if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
                raise ValueError("invalid provider body source path")
            matches = [
                info
                for info in infos
                if (PurePosixPath(info.filename).parts[-len(relative.parts):] == relative.parts)
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"provider body path is ambiguous or missing: {identifier}"
                )
            info = matches[0]
            if info.is_dir() or info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError("unsupported provider ZIP member encoding")
            declared_bytes += info.file_size
            if declared_bytes > max_bytes:
                raise ValueError("hydration byte limit exceeded before decompression")
            selected_members.append((identifier, record, info))
        for identifier, record, info in selected_members:
            body = bytearray()
            remaining = max_bytes - used
            with source.open(info) as stream:
                while len(body) <= remaining:
                    chunk = stream.read(min(65_536, remaining + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
            if len(body) > remaining or len(body) != info.file_size:
                raise ValueError("hydration byte limit or declared size mismatch")
            if hashlib.sha256(body).hexdigest() != record["body_sha256"]:
                raise ValueError(f"provider body hash mismatch: {identifier}")
            if used + len(body) > max_bytes:
                raise ValueError("hydration byte limit exceeded")
            used += len(body)
            hydrated.append(
                {
                    "id": identifier,
                    "body": body.decode("utf-8"),
                    "body_sha256": record["body_sha256"],
                    "untrusted_reference": True,
                    "authority_granted": False,
                }
            )
    return {
        "valid": True,
        "records": hydrated,
        "hydrated_count": len(hydrated),
        "used_bytes": used,
        "archive_sha256": archive_hash,
        "provider_scripts_loaded": 0,
        "authority_granted": False,
    }


def validate_security_finding(finding: Mapping[str, object]) -> dict[str, object]:
    required = (
        "finding_id",
        "title",
        "severity",
        "confidence",
        "evidence",
        "affected_assets",
        "recommended_actions",
    )
    errors = [f"{field}_missing" for field in required if field not in finding]
    status = str(finding.get("validation_status", "unverified"))
    evidence = finding.get("evidence", ())
    if status == "verified":
        if not isinstance(evidence, list) or not evidence:
            errors.append("verified_finding_requires_evidence")
        elif any(
            not isinstance(item, Mapping)
            or not item.get("sha256")
            or not item.get("reference")
            for item in evidence
        ):
            errors.append("verified_finding_requires_hashed_evidence_references")
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "validation_status": status,
        "canonical_promotion": False,
    }


def validate_security_orchestration(root: Path) -> dict[str, object]:
    workflow = (
        root.resolve(strict=True)
        / "orchestration/workflows/cybersecurity-capability-operations.yaml"
    )
    if not workflow.is_file():
        return {"valid": False, "errors": ["workflow missing"]}
    text = workflow.read_text(encoding="utf-8")
    required = (
        "normalize",
        "authority-filter",
        "discover",
        "rank",
        "hydrate",
        "validate-outcome",
        "record-learning",
    )
    missing = [step for step in required if f'"{step}"' not in text]
    try:
        status = security_provider_status(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "valid": False,
            "errors": [f"provider invalid: {type(error).__name__}: {error}"],
        }
    return {
        "valid": not missing,
        "errors": [f"missing step: {step}" for step in missing],
        "provider": status,
        "effects": ["read_local"],
        "authority_granted": False,
    }
