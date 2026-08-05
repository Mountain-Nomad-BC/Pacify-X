"""Canonical governed knowledge intake, novelty, graph, and merge planning.

The refinery reuses PACIFY-X inventory, routing, graph, evidence, and project
control boundaries. It never writes canon directly: approved plans are staged
as hash-bound proposals for the existing isolated apply and certification flow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import re

from .bounded_walk import WalkLimits, bounded_walk
from .memory_intelligence import sanitize_capture


TOKEN = re.compile(r"[a-z0-9][a-z0-9_+.#/-]*", re.IGNORECASE)
DECISIONS = (
    "DUPLICATE",
    "ENRICH",
    "VARIANT",
    "CONFLICT",
    "SUPERSEDE",
    "NOVEL",
    "REVIEW",
)


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _terms(value: object) -> set[str]:
    return {
        token.casefold().strip("./-")
        for token in TOKEN.findall(str(value))
        if len(token.strip("./-")) > 1
    }


def _list(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = record.get(key, ())
    if isinstance(value, str):
        value = (value,)
    return (
        tuple(sorted({str(item).strip() for item in value if str(item).strip()}))
        if isinstance(value, Iterable)
        else ()
    )


def _identity(record: Mapping[str, object]) -> str:
    return str(record.get("id") or record.get("artifact_id") or "").strip()


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    return 0.0 if not a and not b else len(a & b) / max(1, len(a | b))


def portable_inventory(
    source: Path,
    *,
    max_files: int = 100_000,
    max_depth: int = 40,
    max_bytes: int = 4 * 1024 * 1024 * 1024,
    max_text_bytes: int = 2 * 1024 * 1024,
) -> dict[str, object]:
    root = source.resolve(strict=True)
    walk = bounded_walk(
        root,
        limits=WalkLimits(
            max_files=max_files, max_depth=max_depth, max_bytes=max_bytes
        ),
        symlink_policy="reject",
    )
    records = []
    secret_findings = []
    for item in walk.files:
        path = item.path
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {"path": item.relative, "bytes": item.size, "sha256": digest}
        records.append(record)
        if item.size <= max_text_bytes:
            text = path.read_text(encoding="utf-8", errors="replace")
            result = sanitize_capture(text)
            if result.secret_finding_codes:
                secret_findings.append(
                    {
                        "path": item.relative,
                        "finding_codes": list(result.secret_finding_codes),
                        "values_redacted": True,
                    }
                )
    portable = [
        {"path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
        for item in records
    ]
    return {
        "valid": not secret_findings,
        "source_name": root.name,
        "file_count": len(records),
        "byte_count": sum(int(item["bytes"]) for item in records),
        "content_sha256": _stable(portable),
        "files": records,
        "secret_findings": secret_findings,
        "secret_values_recorded": False,
        "canonical_writes_performed": False,
    }


def similarity(
    candidate: Mapping[str, object], existing: Mapping[str, object]
) -> dict[str, float]:
    candidate_text = _terms(
        " ".join(
            str(candidate.get(key, ""))
            for key in ("id", "artifact_id", "title", "description")
        )
    )
    existing_text = _terms(
        " ".join(
            str(existing.get(key, ""))
            for key in ("id", "artifact_id", "title", "description")
        )
    )
    components = {
        "identity": 1.0
        if _identity(candidate).casefold() == _identity(existing).casefold()
        and _identity(candidate)
        else 0.0,
        "aliases": _jaccard(
            {x.casefold() for x in _list(candidate, "aliases")},
            {x.casefold() for x in _list(existing, "aliases")},
        ),
        "lexical": _jaccard(candidate_text, existing_text),
        "capabilities": _jaccard(
            _list(candidate, "capabilities"), _list(existing, "capabilities")
        ),
        "mechanisms": _jaccard(
            _list(candidate, "mechanisms"), _list(existing, "mechanisms")
        ),
        "io": _jaccard(
            (*_list(candidate, "inputs"), *_list(candidate, "outputs")),
            (*_list(existing, "inputs"), *_list(existing, "outputs")),
        ),
        "failure_modes": _jaccard(
            _list(candidate, "failure_modes"), _list(existing, "failure_modes")
        ),
        "invariants": _jaccard(
            _list(candidate, "invariants"), _list(existing, "invariants")
        ),
    }
    weights = {
        "identity": 0.20,
        "aliases": 0.08,
        "lexical": 0.12,
        "capabilities": 0.20,
        "mechanisms": 0.15,
        "io": 0.10,
        "failure_modes": 0.07,
        "invariants": 0.08,
    }
    components["aggregate"] = round(
        sum(components[key] * weights[key] for key in weights), 6
    )
    return {key: round(value, 6) for key, value in components.items()}


def _quality(record: Mapping[str, object]) -> float:
    declared = (
        sum(
            bool(record.get(key))
            for key in (
                "description",
                "capabilities",
                "mechanisms",
                "inputs",
                "outputs",
                "failure_modes",
                "invariants",
            )
        )
        / 7
    )
    evidence = float(record.get("evidence_quality", 0.0))
    validation = float(record.get("validation_coverage", 0.0))
    return min(1.0, max(0.0, declared * 0.6 + evidence * 0.2 + validation * 0.2))


def classify_novelty(
    candidates: Iterable[Mapping[str, object]],
    canonical: Iterable[Mapping[str, object]],
    *,
    ambiguity_margin: float = 0.04,
) -> dict[str, object]:
    candidate_rows = tuple(candidates)
    canonical_rows = tuple(canonical)
    candidate_ids = [_identity(item) for item in candidate_rows]
    if not all(candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate IDs must be nonempty and unique")
    decisions = []
    for candidate in candidate_rows:
        ranked = sorted(
            ((similarity(candidate, target), target) for target in canonical_rows),
            key=lambda item: (-item[0]["aggregate"], _identity(item[1])),
        )
        top = ranked[0] if ranked else None
        runner_up = ranked[1] if len(ranked) > 1 else None
        target = top[1] if top else None
        score = top[0]["aggregate"] if top else 0.0
        explicit_conflict = target is not None and (
            _identity(target) in _list(candidate, "conflicts_with")
            or _identity(candidate) in _list(target, "conflicts_with")
        )
        ambiguous = (
            runner_up is not None
            and score >= 0.45
            and score - runner_up[0]["aggregate"] <= ambiguity_margin
        )
        if explicit_conflict:
            decision = "CONFLICT"
        elif ambiguous:
            decision = "REVIEW"
        elif top and (top[0]["identity"] == 1.0 or score >= 0.92):
            decision = "DUPLICATE"
        elif (
            target is not None
            and _identity(target) in _list(candidate, "supersedes")
            and _quality(candidate) >= _quality(target) + 0.12
        ):
            decision = "SUPERSEDE"
        elif score >= 0.65:
            decision = "ENRICH"
        elif score >= 0.45:
            decision = "VARIANT"
        elif score < 0.30:
            decision = "NOVEL"
        else:
            decision = "REVIEW"
        decisions.append(
            {
                "candidate_id": _identity(candidate),
                "decision": decision,
                "target_id": _identity(target) if target is not None else None,
                "confidence": round(
                    max(score, 1 - score)
                    if decision != "REVIEW"
                    else 1
                    - (abs(score - (runner_up[0]["aggregate"] if runner_up else 0.5))),
                    6,
                ),
                "similarity": top[0] if top else None,
                "alternatives": [
                    {"target_id": _identity(item[1]), "score": item[0]["aggregate"]}
                    for item in ranked[:3]
                ],
                "manual_review_required": decision
                in {"REVIEW", "CONFLICT", "SUPERSEDE", "ENRICH"},
            }
        )
    return {
        "valid": len(decisions) == len(candidate_rows),
        "candidate_count": len(candidate_rows),
        "decision_count": len(decisions),
        "decisions": decisions,
        "decision_classes": list(DECISIONS),
    }


def plan_merges(
    novelty: Mapping[str, object], canonical_fingerprints: Mapping[str, str]
) -> dict[str, object]:
    action_by_decision = {
        "DUPLICATE": "retain-canonical",
        "ENRICH": "propose-enrichment",
        "VARIANT": "propose-variant",
        "CONFLICT": "hold-for-review",
        "SUPERSEDE": "propose-reversible-supersession",
        "NOVEL": "propose-admission",
        "REVIEW": "hold-for-review",
    }
    actions = []
    for decision in novelty.get("decisions", ()):
        target = decision.get("target_id")
        actions.append(
            {
                "candidate_id": decision["candidate_id"],
                "decision": decision["decision"],
                "action": action_by_decision[str(decision["decision"])],
                "target_id": target,
                "target_fingerprint": canonical_fingerprints.get(str(target))
                if target
                else None,
                "requires_approval": decision["decision"] != "DUPLICATE",
                "canonical_write": False,
                "hard_delete": False,
            }
        )
    payload = {
        "candidate_count": novelty.get("candidate_count", 0),
        "decision_count": novelty.get("decision_count", 0),
        "action_count": len(actions),
        "actions": actions,
        "canonical_writes_performed": False,
    }
    payload["plan_sha256"] = _stable(payload)
    payload["valid"] = (
        payload["candidate_count"]
        == payload["decision_count"]
        == payload["action_count"]
    )
    return payload


def audit_graph(
    nodes: Iterable[str],
    edges: Iterable[Mapping[str, object]],
    *,
    permitted_external_prefixes: Iterable[str] = (),
) -> dict[str, object]:
    node_set = set(map(str, nodes))
    prefixes = tuple(map(str, permitted_external_prefixes))
    edge_rows = tuple(edges)
    errors = []
    seen = set()
    graph: dict[str, list[str]] = {}
    for edge in edge_rows:
        source, relation, target = (
            str(edge.get("source", "")),
            str(edge.get("relation", "")),
            str(edge.get("target", "")),
        )
        key = (source, relation, target)
        if key in seen:
            errors.append(f"duplicate edge: {source}:{relation}:{target}")
        seen.add(key)
        if source == target:
            errors.append(f"illegal self edge: {source}:{relation}")
        if source not in node_set:
            errors.append(f"missing source: {source}")
        if target not in node_set and not target.startswith(prefixes):
            errors.append(f"missing target: {target}")
        if relation in {"depends-on", "supersedes"}:
            graph.setdefault(source, []).append(target)
        if edge.get("assertion") == "suggested" and edge.get("reviewed") is True:
            errors.append(f"suggested edge cannot be pre-reviewed: {source}:{target}")
    active: list[str] = []
    visited = set()

    def visit(node: str) -> None:
        if node in active:
            errors.append(
                "forbidden cycle: " + " -> ".join(active[active.index(node) :] + [node])
            )
            return
        if node in visited:
            return
        active.append(node)
        for target in sorted(graph.get(node, ())):
            if target in node_set:
                visit(target)
        active.pop()
        visited.add(node)

    for node in sorted(node_set):
        visit(node)
    incoming = {str(edge.get("target")) for edge in edge_rows}
    outgoing = {str(edge.get("source")) for edge in edge_rows}
    return {
        "valid": not errors,
        "node_count": len(node_set),
        "edge_count": len(seen),
        "orphans": sorted(node_set - incoming - outgoing),
        "errors": sorted(set(errors)),
    }


def evaluate_retrieval(
    cases: Iterable[Mapping[str, object]], rankings: Mapping[str, Sequence[str]]
) -> dict[str, object]:
    rows = tuple(cases)
    per_case = []
    reciprocal = []
    ndcg_values = []
    forbidden_hits = 0
    for case in rows:
        identifier = str(case.get("id", ""))
        expected = tuple(map(str, case.get("expected_ids", ())))
        forbidden = set(map(str, case.get("forbidden_ids", ())))
        returned = tuple(map(str, rankings.get(identifier, ())))
        first = next(
            (index + 1 for index, item in enumerate(returned) if item in expected), None
        )
        rr = 0.0 if first is None else 1.0 / first
        reciprocal.append(rr)
        dcg = sum(
            (1.0 if item in expected else 0.0) / math.log2(index + 2)
            for index, item in enumerate(returned)
        )
        ideal = sum(
            1.0 / math.log2(index + 2)
            for index in range(min(len(expected), len(returned)))
        )
        ndcg = 0.0 if not ideal else dcg / ideal
        ndcg_values.append(ndcg)
        hits = sorted(forbidden & set(returned))
        forbidden_hits += len(hits)
        no_result_ok = bool(case.get("expect_no_result")) and not returned
        per_case.append(
            {
                "id": identifier,
                "reciprocal_rank": round(rr, 6),
                "ndcg": round(ndcg, 6),
                "forbidden_hits": hits,
                "no_result_ok": no_result_ok,
            }
        )
    count = len(rows)
    return {
        "valid": forbidden_hits == 0,
        "case_count": count,
        "mrr": round(sum(reciprocal) / max(1, count), 6),
        "ndcg": round(sum(ndcg_values) / max(1, count), 6),
        "forbidden_hit_count": forbidden_hits,
        "cases": per_case,
    }


def assess_calibration_proposal(
    baseline_train: Mapping[str, object],
    baseline_holdout: Mapping[str, object],
    candidate_train: Mapping[str, object],
    candidate_holdout: Mapping[str, object],
    *,
    train_case_ids: Iterable[str],
    holdout_case_ids: Iterable[str],
    minimum_improvement: float = 0.0,
) -> dict[str, object]:
    train_ids, holdout_ids = (
        set(map(str, train_case_ids)),
        set(map(str, holdout_case_ids)),
    )
    overlap = sorted(train_ids & holdout_ids)

    def objective(value: Mapping[str, object]) -> float:
        return (
            float(value.get("mrr", 0.0)) * 0.5
            + float(value.get("ndcg", 0.0)) * 0.5
            - float(value.get("forbidden_hit_count", 0))
        )

    base_train, base_holdout = objective(baseline_train), objective(baseline_holdout)
    proposed_train, proposed_holdout = (
        objective(candidate_train),
        objective(candidate_holdout),
    )
    accepted = (
        not overlap
        and proposed_train >= base_train + minimum_improvement
        and proposed_holdout >= base_holdout
        and int(candidate_holdout.get("forbidden_hit_count", 0))
        <= int(baseline_holdout.get("forbidden_hit_count", 0))
    )
    return {
        "valid": not overlap,
        "accepted": accepted,
        "train_holdout_overlap": overlap,
        "baseline": {"train": base_train, "holdout": base_holdout},
        "candidate": {"train": proposed_train, "holdout": proposed_holdout},
        "automatic_deployment": False,
        "manual_review_required": True,
        "rollback_required_if_rejected": not accepted,
    }


def certify_refinery_run(
    components: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    required = (
        "inventory",
        "novelty",
        "merge_plan",
        "graph",
        "retrieval",
        "calibration",
    )
    missing = [key for key in required if key not in components]
    failures = [
        key
        for key in required
        if key in components and components[key].get("valid") is not True
    ]
    plan = components.get("merge_plan", {})
    if plan and not (
        plan.get("candidate_count")
        == plan.get("decision_count")
        == plan.get("action_count")
    ):
        failures.append("count_parity")
    if components.get("retrieval", {}).get("forbidden_hit_count", 0):
        failures.append("forbidden_hits")
    if components.get("calibration", {}).get("accepted") is not True:
        failures.append("calibration_not_accepted")
    payload = {
        "valid": not missing and not failures,
        "status": "PASS" if not missing and not failures else "FAIL",
        "missing": missing,
        "failures": sorted(set(failures)),
        "canonical_writes_performed": False,
    }
    payload["evidence_sha256"] = _stable(components)
    return payload


def stage_merge_plan(
    project: Path,
    plan: Mapping[str, object],
    *,
    approval_evidence: Iterable[str],
    apply: bool = False,
) -> dict[str, object]:
    project = project.resolve(strict=True)
    if not (project / ".engineering-bootstrap/project-management/state.json").is_file():
        raise ValueError("project is not commissioned")
    if plan.get("valid") is not True or plan.get("plan_sha256") != _stable(
        {
            key: value
            for key, value in plan.items()
            if key not in {"plan_sha256", "valid"}
        }
    ):
        raise ValueError("invalid or stale merge plan")
    evidence = sorted(set(filter(None, map(str, approval_evidence))))
    result = {
        "valid": bool(evidence),
        "applied": False,
        "plan_sha256": plan["plan_sha256"],
        "canonical_writes_performed": False,
        "hard_delete": False,
        "errors": [] if evidence else ["approval evidence required"],
    }
    if not apply or not evidence:
        return result
    target = (
        project
        / ".engineering-bootstrap/knowledge-refinery/staged"
        / f"{plan['plan_sha256']}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": "1.0",
        "state": "staged-proposal",
        "plan": plan,
        "approval_evidence": evidence,
        "canonical_writes_performed": False,
        "authority_granted": False,
    }
    rendered = json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise ValueError("staged refinery receipt drift")
    if not target.exists():
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
    return {
        **result,
        "valid": True,
        "applied": True,
        "receipt": target.relative_to(project).as_posix(),
    }


def validate_refinery_orchestration(root: Path) -> dict[str, object]:
    path = root / "orchestration/workflows/knowledge-refinery.yaml"
    if not path.is_file():
        return {"valid": False, "errors": ["workflow missing"]}
    text = path.read_text(encoding="utf-8")
    required = (
        "inventory",
        "admission",
        "extract",
        "classify",
        "merge-plan",
        "graph-audit",
        "simulate",
        "calibrate",
        "certify",
        "stage-approved",
    )
    missing = [item for item in required if f'"{item}"' not in text]
    return {
        "valid": not missing,
        "errors": [f"missing step: {item}" for item in missing],
        "canonical_writes_performed": False,
    }
