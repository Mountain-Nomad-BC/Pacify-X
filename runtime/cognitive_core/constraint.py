"""Bounded finite-domain constraint reasoning with explicit, data-only constraints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .common import stable_hash

_UNKNOWN = object()
_SUPPORTED = {
    "all_different",
    "sum_eq",
    "sum_lte",
    "sum_gte",
    "in",
    "not_in",
    "implies",
    "eq",
    "neq",
    "lt",
    "lte",
    "gt",
    "gte",
}


def _term(term: object, assignment: Mapping[str, Any]) -> object:
    if isinstance(term, Mapping) and "var" in term:
        return assignment.get(str(term["var"]), _UNKNOWN)
    if isinstance(term, Mapping) and "value" in term:
        return term["value"]
    return term


def _check(constraint: Mapping[str, Any], assignment: Mapping[str, Any]) -> bool | None:
    kind = str(constraint.get("type", ""))
    if kind not in _SUPPORTED:
        raise ValueError(f"unsupported constraint type: {kind}")
    if kind == "all_different":
        values = [
            _term({"var": name}, assignment) for name in constraint.get("vars", ())
        ]
        known = [value for value in values if value is not _UNKNOWN]
        return (
            False
            if len(known) != len(set(map(repr, known)))
            else (True if len(known) == len(values) else None)
        )
    if kind.startswith("sum_"):
        values = [
            _term({"var": name}, assignment) for name in constraint.get("vars", ())
        ]
        if any(value is _UNKNOWN for value in values):
            return None
        total = sum(float(value) for value in values)
        target = float(constraint["target"])
        if kind == "sum_eq":
            return total == target
        if kind == "sum_lte":
            return total <= target
        return total >= target
    if kind == "in":
        left = _term(constraint.get("left"), assignment)
        return None if left is _UNKNOWN else left in constraint.get("values", ())
    if kind == "not_in":
        left = _term(constraint.get("left"), assignment)
        return None if left is _UNKNOWN else left not in constraint.get("values", ())
    if kind == "implies":
        antecedent = _check(constraint.get("if", {}), assignment)
        if antecedent is False:
            return True
        if antecedent is None:
            return None
        return _check(constraint.get("then", {}), assignment)
    left = _term(constraint.get("left"), assignment)
    right = _term(constraint.get("right"), assignment)
    if left is _UNKNOWN or right is _UNKNOWN:
        return None
    if kind == "eq":
        return left == right
    if kind == "neq":
        return left != right
    if kind == "lt":
        return left < right
    if kind == "lte":
        return left <= right
    if kind == "gt":
        return left > right
    return left >= right


def _validate_constraint(
    constraint: Mapping[str, Any], variables: set[str], path: str
) -> None:
    kind = str(constraint.get("type", ""))
    if kind not in _SUPPORTED:
        raise ValueError(f"{path}: unsupported constraint type: {kind}")
    referenced: set[str] = set()
    for field in ("left", "right"):
        term = constraint.get(field)
        if isinstance(term, Mapping) and "var" in term:
            referenced.add(str(term["var"]))
    referenced.update(map(str, constraint.get("vars", ())))
    unknown = sorted(referenced - variables)
    if unknown:
        raise ValueError(f"{path}: unknown variables: {unknown}")
    if kind == "implies":
        if not isinstance(constraint.get("if"), Mapping) or not isinstance(
            constraint.get("then"), Mapping
        ):
            raise ValueError(f"{path}: implies requires object-valued if and then")
        _validate_constraint(constraint["if"], variables, f"{path}.if")
        _validate_constraint(constraint["then"], variables, f"{path}.then")


def solve(payload: Mapping[str, Any]) -> dict[str, Any]:
    variables = payload.get("variables", {})
    if not isinstance(variables, Mapping) or not variables:
        raise ValueError("variables must be a non-empty object of finite domains")
    domains: dict[str, tuple[Any, ...]] = {}
    for name, values in variables.items():
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or not values
        ):
            raise ValueError(f"{name}: domain must be a non-empty list")
        domain = tuple(values)
        if len(set(map(repr, domain))) != len(domain):
            raise ValueError(f"{name}: domain values must be unique")
        domains[str(name)] = domain
    constraints = tuple(
        item for item in payload.get("constraints", ()) if isinstance(item, Mapping)
    )
    for index, constraint in enumerate(constraints):
        _validate_constraint(constraint, set(domains), f"constraint[{index}]")
    max_solutions = max(1, min(int(payload.get("max_solutions", 25)), 1000))
    max_nodes = max(1, min(int(payload.get("max_nodes", 100000)), 2_000_000))
    search_limit = max_solutions + 1
    order = sorted(domains, key=lambda name: (len(domains[name]), name))
    assignment: dict[str, Any] = {}
    found: list[dict[str, Any]] = []
    rejected: dict[int, int] = {}
    nodes = 0
    exhausted = False

    def consistent() -> bool:
        for index, constraint in enumerate(constraints):
            result = _check(constraint, assignment)
            if result is False:
                rejected[index] = rejected.get(index, 0) + 1
                return False
        return True

    def search(depth: int) -> None:
        nonlocal nodes, exhausted
        if exhausted or len(found) >= search_limit:
            return
        if nodes >= max_nodes:
            exhausted = True
            return
        if depth == len(order):
            if all(
                _check(constraint, assignment) is True for constraint in constraints
            ):
                found.append(dict(sorted(assignment.items())))
            return
        name = order[depth]
        for value in domains[name]:
            if nodes >= max_nodes:
                exhausted = True
                break
            nodes += 1
            assignment[name] = value
            if consistent():
                search(depth + 1)
            assignment.pop(name, None)
            if exhausted or len(found) >= search_limit:
                break

    search(0)
    truncated = len(found) > max_solutions
    solutions = found[:max_solutions]
    result = {
        "valid": True,
        "satisfiable": bool(solutions),
        "solutions": solutions,
        "solution_count_returned": len(solutions),
        "search_nodes": nodes,
        "node_budget_exhausted": exhausted,
        "truncated": truncated,
        "variable_order": order,
        "constraint_rejection_counts": {
            str(key): value for key, value in sorted(rejected.items())
        },
        "method": "bounded finite-domain backtracking with partial constraint pruning",
    }
    return {**result, "result_sha256": stable_hash(result)}
