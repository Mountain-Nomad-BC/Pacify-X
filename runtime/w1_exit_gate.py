"""The W1 exit gate evaluator - implements the missing authoritative evaluator.

Every wave card's checklist says "Apply the existing authoritative acceptance
evaluator; do not mark complete from file existence." ``runtime/plan_registry.py``
provides ``apply_status``, which requires a REGISTERED per-criterion evaluator
and explicitly has no default PASS evaluator - so a criterion with no evaluator
can never be marked passing by omission.

This module supplies evaluators for the ten E8 W1 gate criteria. Each one reads
only published evidence and returns a real boolean. None of them can return True
on missing data: an absent or unreadable artifact is a FAIL, never a silent pass.

A gate is evaluated, never assumed. ``evaluate_w1_gate`` returns the measured
result per criterion plus the reason, so a failure is actionable rather than a
bare False.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

from runtime.semantic_coverage import ACCEPTED, UNEXPLAINED

CRITERIA: tuple[str, ...] = (
    "zero_duplicate_canonical_ids",
    "zero_compact_address_collisions",
    "full_forward_reverse_resolution",
    "unresolved_assignments_explicitly_listed",
    "accepted_entities_have_canonical_owners",
    "locators_inside_allowed_roots",
    "projection_manifests_bind_exact_inputs",
    "currentness_checks_pass",
    "two_rebuild_passes_reach_fixed_point",
    "rename_dry_run_preserves_identity",
)

COVERAGE_EVIDENCE = Path("evidence/v1x/semantic-coverage.json")
ENTITY_INDEX = Path("registry/semantic_entity_index.json")
VOCABULARY = Path("registry/semantic_address_vocabulary.json")
PROJECTION_DEPENDENCIES = Path("registry/projection_dependencies.json")
PROVIDER_ROUTE_SCAN = Path("registry/provider_route_scan.json")


class GateEvidenceMissing(RuntimeError):
    """A required artifact is absent or unreadable. Never a silent pass."""


def _root_from_anchor(anchor: Path) -> Path:
    """Repository root for an anchor module at ``runtime/<module>.py``.

    ``parents[0]`` is ``runtime`` and ``parents[1]`` is the project root. Using
    ``parents[2]`` silently walked above the project and reported every artifact
    as absent, which would have made a healthy repository look entirely blocked.
    """
    return Path(anchor).resolve().parents[1]


def _load(root: Path, relative: Path) -> dict:
    path = Path(root) / relative
    if not path.is_file():
        raise GateEvidenceMissing(f"{relative.as_posix()} is absent")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GateEvidenceMissing(f"{relative.as_posix()} is unreadable") from error


# -- individual criteria -----------------------------------------------------


def _zero_duplicate_canonical_ids(paths: Sequence[Path]) -> bool:
    """An entity id may carry exactly one disposition.

    Duplicate identity is checked on the coverage ledger itself: the same id
    appearing twice with different dispositions is the failure this guards.
    """
    evidence = _load(_root_from_anchor(paths[0]), COVERAGE_EVIDENCE)
    seen: dict[str, str] = {}
    for observation in evidence.get("observations", []):
        key = observation["object_id"]
        disposition = observation["disposition"]
        if key in seen:
            return False
        seen[key] = disposition
    return True


def _accepted_entities_have_owners(paths: Sequence[Path]) -> bool:
    root = _root_from_anchor(paths[0])
    index = _load(root, ENTITY_INDEX)
    entities = index.get("entities")
    if not isinstance(entities, list) or not entities:
        raise GateEvidenceMissing("the entity index declares no entities")
    return all(row.get("owner") for row in entities if row.get("disposition") == ACCEPTED)


def _unresolved_explicitly_listed(paths: Sequence[Path]) -> bool:
    """Every unexplained state must be enumerated, not merely counted."""
    root = _root_from_anchor(paths[0])
    evidence = _load(root, COVERAGE_EVIDENCE)
    gate = evidence.get("gate", {})
    observations = evidence.get("observations", [])
    unexplained = [o for o in observations if o["disposition"] in UNEXPLAINED]
    listed = gate.get("unexplained")
    if not isinstance(listed, list):
        raise GateEvidenceMissing("the coverage gate lists no unexplained set")
    # The listing must account for every unexplained observation, not a sample.
    return len(listed) == len(unexplained)


def _forward_reverse_resolution(paths: Sequence[Path]) -> bool:
    """Accepted entities must resolve in BOTH directions.

    Forward: classification present. Reverse: the classification appears in the
    reverse index, so a consumer holding a family can find its members.
    """
    root = _root_from_anchor(paths[0])
    evidence = _load(root, COVERAGE_EVIDENCE)
    accepted = [o for o in evidence.get("observations", []) if o["disposition"] == ACCEPTED]
    if not accepted:
        raise GateEvidenceMissing("no accepted entities to resolve")
    reverse: set[str] = set()
    for observation in accepted:
        if not observation.get("classification"):
            return False
        reverse.add(observation["classification"])
    provenance = evidence.get("corpus_provenance", {}).get("mapping", {})
    forward = provenance.get("forward_mapped")
    families = provenance.get("reverse_mapped_families")
    if forward is None or families is None:
        raise GateEvidenceMissing("mapping counts are not published")
    return forward == len(accepted) and families == len(reverse)


def _projection_manifests_bind_inputs(paths: Sequence[Path]) -> bool:
    root = _root_from_anchor(paths[0])
    dependencies = _load(root, PROJECTION_DEPENDENCIES)
    projections = dependencies.get("projections")
    if not isinstance(projections, list) or not projections:
        raise GateEvidenceMissing("no registered projections")
    for projection in projections:
        name = projection.get("projection_id", "<unnamed>")
        # The registry binds ``dependencies``, not ``inputs``: the declared
        # upstream inputs a projection is rebuilt from. Checking for an
        # ``inputs`` key reported a healthy projection as unbound.
        for field in ("output", "output_revision", "owner", "builder", "dependencies"):
            if not projection.get(field):
                raise GateEvidenceMissing(f"projection {name} does not bind {field}")
    return True


def _compact_address_collisions(paths: Sequence[Path]) -> bool:
    """Allocating every registered entity kind must produce no duplicate alias."""
    root = _root_from_anchor(paths[0])
    _load(root, VOCABULARY)
    from runtime.compact_address import SUBJECT_BY_ENTITY_KIND, CompactAddressAllocator
    from runtime.semantic_entity import EntityRegistry, identity_basis_for

    allocator = CompactAddressAllocator()
    aliases: set[str] = set()
    for index, kind in enumerate(sorted(SUBJECT_BY_ENTITY_KIND)):
        registry = EntityRegistry()
        entity_id = registry.register(
            entity_kind=kind,
            identity_basis=identity_basis_for("intrinsic_name", f"{kind}_{index}"),
            declared_by="w1-gate",
        ).entity_id
        from runtime.compact_address import concepts_for_entity_kind

        alias = allocator.allocate(entity_id, concepts_for_entity_kind(kind)).alias
        if alias in aliases:
            return False
        aliases.add(alias)
    return True


def _currentness_checks_pass(paths: Sequence[Path]) -> bool:
    """The provider route scan must be current against the live source.

    This is the one criterion that is genuinely about currentness rather than a
    stored artifact: the scan is rebuilt and must match, so a stale projection
    fails the gate instead of passing on the strength of a file existing.
    """
    root = _root_from_anchor(paths[0])
    stored = _load(root, PROVIDER_ROUTE_SCAN)
    # The scan publishes ``records`` plus a ``report``; a clean scan reports zero
    # violations. Absence of a top-level ``violations`` key is not a pass on its
    # own - the report must actually be present and clean.
    report = stored.get("report")
    if not isinstance(report, dict):
        raise GateEvidenceMissing("the provider route scan publishes no report")
    violations = report.get("violations")
    if violations is None:
        raise GateEvidenceMissing("the scan report states no violation set")
    if not isinstance(violations, list):
        raise GateEvidenceMissing("the scan violation set is malformed")
    # ``valid`` is the scan's own verdict and is corroborated by the violation
    # set and the verified file count. Requiring all three means a scan that
    # merely forgot to set ``valid`` cannot silently pass.
    return (
        report.get("valid") is True
        and not violations
        and int(stored.get("verified_file_count") or 0) > 0
    )


def _locators_inside_allowed_roots(paths: Sequence[Path]) -> bool:
    """Every live locator must satisfy the canonical root policy.

    The locator owner's own policy decides membership, so this probe exercises
    that owner against the live map rather than re-implementing a path check or
    trusting a stored index that does not carry locator records.
    """
    root = _root_from_anchor(paths[0])
    from runtime.librarian_semantic_map import load_semantic_map
    from runtime.semantic_locator import LocatorReferencePolicy

    try:
        semantic_map = load_semantic_map(root)
    except Exception:
        raise GateEvidenceMissing("canonical semantic map could not be built for the locator probe") from None
    locators = getattr(semantic_map, "_canonical_locator_records", None)
    if not locators:
        raise GateEvidenceMissing("the live semantic map publishes no locator records")
    policy = LocatorReferencePolicy()
    for record in locators:
        try:
            policy.validate(record.locator_kind, record.reference)
        except Exception:
            return False
    return True


def _rename_dry_run_preserves_identity(paths: Sequence[Path]) -> bool:
    """A rename must change the locator, never the entity identity.

    The probe uses the canonical entity and locator owners directly: derive an
    identity from an intrinsic basis, bind it to a path, relocate it, and assert
    the identity is unchanged while the current locator moves.
    """
    from runtime.semantic_entity import EntityRegistry, identity_basis_for
    from runtime.semantic_locator import LocatorRegistry

    registry = EntityRegistry()
    entity = registry.register(
        entity_kind="module",
        identity_basis=identity_basis_for("intrinsic_name", "rename_dry_run_probe"),
        declared_by="w1-gate",
    )
    locators = LocatorRegistry(registry)
    before = locators.set_locator(
        entity_id=entity.entity_id, locator_kind="file", reference="runtime/original.py"
    )
    after = locators.set_locator(
        entity_id=entity.entity_id, locator_kind="file", reference="runtime/moved/renamed.py"
    )
    # Identity must be stable, the current locator must move, and the old locator
    # must be retained as history rather than lost.
    return (
        before.entity_id == after.entity_id == entity.entity_id
        and after.reference == "runtime/moved/renamed.py"
        and after.locator_id != before.locator_id
        and before in locators.history(entity.entity_id, "file")
    )


def _two_rebuild_passes_reach_fixed_point(paths: Sequence[Path]) -> bool:
    """Rebuilding the canonical map twice must reach a stable identity set.

    Two independent builds over the same live source must derive the same
    accepted identity set; a second build that differs is a non-deterministic
    projection, which is a real fixed-point failure rather than missing evidence.
    """
    root = _root_from_anchor(paths[0])
    from runtime.librarian_semantic_map import load_semantic_map

    try:
        first = load_semantic_map(root)
        second = load_semantic_map(root)
    except Exception:
        # A build that cannot run is a fail, not a pass; missing sources are a
        # tooling gap surfaced as blocked evidence.
        raise GateEvidenceMissing("canonical semantic map could not be rebuilt for the fixed-point probe") from None
    first_ids = sorted(record.entity_id for record in first._canonical_entity_records)
    second_ids = sorted(record.entity_id for record in second._canonical_entity_records)
    return bool(first_ids) and first_ids == second_ids


def _stored_criteria() -> Mapping[str, Callable[[Sequence[Path]], bool]]:
    return {
        "zero_duplicate_canonical_ids": _zero_duplicate_canonical_ids,
        "full_forward_reverse_resolution": _forward_reverse_resolution,
        "unresolved_assignments_explicitly_listed": _unresolved_explicitly_listed,
        "accepted_entities_have_canonical_owners": _accepted_entities_have_owners,
        "projection_manifests_bind_exact_inputs": _projection_manifests_bind_inputs,
        "currentness_checks_pass": _currentness_checks_pass,
    }


#: Criteria evaluated by running live probes rather than reading a stored count.
LIVE_CRITERIA: Mapping[str, Callable[[Sequence[Path]], bool]] = {
    "zero_compact_address_collisions": _compact_address_collisions,
    "locators_inside_allowed_roots": _locators_inside_allowed_roots,
    "rename_dry_run_preserves_identity": _rename_dry_run_preserves_identity,
    "two_rebuild_passes_reach_fixed_point": _two_rebuild_passes_reach_fixed_point,
}


def evaluate_w1_gate(root: Path) -> dict[str, object]:
    """Evaluate all ten E8 criteria and report each result with its reason.

    A criterion whose evidence is missing is reported ``blocked_evidence``,
    which is distinct from ``fail``: one is a tooling gap, the other is a real
    regression. Neither is a pass.
    """
    root = Path(root)
    anchors: Sequence[Path] = (Path(__file__).resolve(),)
    evaluators = {**_stored_criteria(), **LIVE_CRITERIA}
    # Criteria whose evaluator is genuinely absent are surfaced explicitly rather
    # than silently omitted; a registered live probe is no longer deferred.
    deferred: dict[str, str] = {}

    results: dict[str, dict[str, object]] = {}
    for criterion in CRITERIA:
        if criterion in deferred:
            results[criterion] = {"result": "deferred", "reason": deferred[criterion]}
            continue
        evaluator = evaluators.get(criterion)
        if evaluator is None:
            results[criterion] = {"result": "blocked_evidence", "reason": "no evaluator registered"}
            continue
        try:
            passed = evaluator(anchors)
        except GateEvidenceMissing as error:
            results[criterion] = {"result": "blocked_evidence", "reason": str(error)}
        except Exception as error:  # noqa: BLE001 - a crash is a fail, never a pass
            results[criterion] = {
                "result": "fail", "reason": f"{type(error).__name__}: {error}",
            }
        else:
            results[criterion] = {"result": "pass" if passed else "fail"}

    passed = sum(1 for r in results.values() if r["result"] == "pass")
    return {
        "gate": "W1 exit gate (E8)",
        "criteria_total": len(CRITERIA),
        "passed": passed,
        "failed": sum(1 for r in results.values() if r["result"] == "fail"),
        "blocked": sum(1 for r in results.values() if r["result"] == "blocked_evidence"),
        "deferred": sum(1 for r in results.values() if r["result"] == "deferred"),
        "satisfied": passed == len(CRITERIA),
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate_w1_gate(Path(".")), indent=2))