"""Safe formula registry, dimensional analysis, evaluation, sensitivity, and uncertainty.

The engine intentionally rejects expressions it cannot verify. Formula metadata may still
be indexed as reference-only without becoming executable.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from .common import stable_hash


@dataclass(frozen=True, slots=True)
class Dimension:
    powers: tuple[tuple[str, float], ...] = ()

    @classmethod
    def parse(cls, value: str | Mapping[str, float] | None) -> "Dimension":
        if value is None:
            return cls()
        if isinstance(value, Mapping):
            return cls(
                tuple(
                    sorted(
                        (str(key), float(power))
                        for key, power in value.items()
                        if float(power) != 0
                    )
                )
            )
        if str(value) in {"", "1", "dimensionless"}:
            return cls()
        # Compact dimension grammar: M^1 L^2 T^-2 or M*L^2/T^2.
        text = str(value).replace("*", " ").replace("/", " / ")
        sign = 1.0
        powers: dict[str, float] = {}
        for token in text.split():
            if token == "/":
                sign = -1.0
                continue
            if "^" in token:
                name, exponent = token.split("^", 1)
                power = float(exponent) * sign
            else:
                name, power = token, sign
            powers[name] = powers.get(name, 0.0) + power
        return cls(
            tuple(
                sorted(
                    (name, power)
                    for name, power in powers.items()
                    if abs(power) > 1e-12
                )
            )
        )

    def __mul__(self, other: "Dimension") -> "Dimension":
        values = dict(self.powers)
        for key, value in other.powers:
            values[key] = values.get(key, 0.0) + value
        return Dimension.parse(values)

    def __truediv__(self, other: "Dimension") -> "Dimension":
        values = dict(self.powers)
        for key, value in other.powers:
            values[key] = values.get(key, 0.0) - value
        return Dimension.parse(values)

    def __pow__(self, power: float) -> "Dimension":
        return Dimension.parse({key: value * power for key, value in self.powers})

    def render(self) -> str:
        return (
            "1"
            if not self.powers
            else " ".join(f"{key}^{power:g}" for key, power in self.powers)
        )


@dataclass(frozen=True, slots=True)
class Variable:
    name: str
    dimension: Dimension
    minimum: float | None = None
    maximum: float | None = None

    @classmethod
    def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "Variable":
        minimum = float(value["minimum"]) if value.get("minimum") is not None else None
        maximum = float(value["maximum"]) if value.get("maximum") is not None else None
        if minimum is not None and not math.isfinite(minimum):
            raise ValueError(f"{name}: minimum must be finite")
        if maximum is not None and not math.isfinite(maximum):
            raise ValueError(f"{name}: maximum must be finite")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"{name}: minimum exceeds maximum")
        return cls(str(name), Dimension.parse(value.get("dimension")), minimum, maximum)


@dataclass(frozen=True, slots=True)
class FormulaDefinition:
    formula_id: str
    expression: str
    variables: Mapping[str, Variable]
    output_dimension: Dimension
    assumptions: tuple[str, ...] = ()
    status: str = "executable"
    source: str = "candidate"
    authoritative_source: str = ""
    expected_examples: tuple[Mapping[str, Any], ...] = ()
    property_cases: tuple[str, ...] = ()
    validation: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FormulaDefinition":
        formula_id = str(value.get("id", "")).strip()
        expression = str(value.get("expression", value.get("equation", ""))).strip()
        if not formula_id or not expression:
            raise ValueError("formula id and expression are required")
        variables_raw = value.get("variables", {})
        if not isinstance(variables_raw, Mapping):
            raise ValueError("formula variables must be an object")
        variables = {
            str(name): Variable.from_mapping(str(name), spec)
            for name, spec in variables_raw.items()
        }
        examples = value.get("expected_examples", ())
        if not isinstance(examples, Sequence) or isinstance(examples, (str, bytes)):
            raise ValueError("expected_examples must be an array")
        return cls(
            formula_id,
            expression,
            variables,
            Dimension.parse(value.get("output_dimension")),
            tuple(map(str, value.get("assumptions", ()))),
            str(value.get("status", "executable")),
            str(value.get("source", "candidate")),
            str(value.get("authoritative_source", "")),
            tuple(item for item in examples if isinstance(item, Mapping)),
            tuple(map(str, value.get("property_cases", ()))),
            str(value.get("validation", "")),
        )


_ALLOWED_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "min": min,
    "max": max,
}
_ALLOWED_NODES = {
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Call,
}


def _validate_ast(tree: ast.Expression, variables: set[str]) -> None:
    nodes = list(ast.walk(tree))
    if len(nodes) > 128:
        raise ValueError("formula exceeds AST node budget")
    for node in nodes:
        if type(node) not in _ALLOWED_NODES:
            raise ValueError(f"unsupported formula syntax: {type(node).__name__}")
        if (
            isinstance(node, ast.Name)
            and node.id not in variables
            and node.id not in _ALLOWED_FUNCTIONS
        ):
            raise ValueError(f"undeclared formula symbol: {node.id}")
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in _ALLOWED_FUNCTIONS
            ):
                raise ValueError("only approved scalar functions may be called")
            if node.keywords:
                raise ValueError("formula function keyword arguments are forbidden")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("formula constants must be numeric")
            if not math.isfinite(float(node.value)) or abs(float(node.value)) > 1e100:
                raise ValueError("formula constant is out of bounds")


def _constant_number(node: ast.AST) -> float:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _constant_number(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    raise ValueError("dimensioned powers require a numeric constant exponent")


def _dimension(node: ast.AST, variables: Mapping[str, Variable]) -> Dimension:
    if isinstance(node, ast.Expression):
        return _dimension(node.body, variables)
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_FUNCTIONS:
            return Dimension()
        return variables[node.id].dimension
    if isinstance(node, ast.Constant):
        return Dimension()
    if isinstance(node, ast.UnaryOp):
        return _dimension(node.operand, variables)
    if isinstance(node, ast.BinOp):
        left, right = (
            _dimension(node.left, variables),
            _dimension(node.right, variables),
        )
        if isinstance(node.op, (ast.Add, ast.Sub, ast.Mod)):
            if left != right:
                raise ValueError(
                    f"dimension mismatch in additive operation: {left.render()} vs {right.render()}"
                )
            return left
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            if right != Dimension():
                raise ValueError("formula exponent must be dimensionless")
            if left == Dimension():
                return Dimension()
            exponent = _constant_number(node.right)
            return left**exponent
    if isinstance(node, ast.Call):
        name = node.func.id  # validated before this function
        dimensions = [_dimension(argument, variables) for argument in node.args]
        if name in {"log", "log10", "exp"}:
            if any(item != Dimension() for item in dimensions):
                raise ValueError(f"{name} requires dimensionless arguments")
            return Dimension()
        if name == "sqrt":
            if len(dimensions) != 1:
                raise ValueError("sqrt requires one argument")
            return dimensions[0] ** 0.5
        if name in {"abs", "min", "max"}:
            if not dimensions or any(item != dimensions[0] for item in dimensions[1:]):
                raise ValueError(f"{name} requires equal argument dimensions")
            return dimensions[0]
    raise ValueError(f"cannot infer formula dimension for {type(node).__name__}")


def _evaluate(node: ast.AST, values: Mapping[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values)
    if isinstance(node, ast.Name):
        return float(values[node.id])
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left, values), _evaluate(node.right, values)
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        elif isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            result = left / right
        elif isinstance(node.op, ast.Mod):
            if right == 0:
                raise ValueError("modulo by zero")
            result = left % right
        elif isinstance(node.op, ast.Pow):
            if abs(right) > 32:
                raise ValueError("formula exponent exceeds bound")
            result = left**right
        else:
            raise ValueError("unsupported operator")
    elif isinstance(node, ast.Call):
        name = node.func.id
        arguments = [_evaluate(argument, values) for argument in node.args]
        result = _ALLOWED_FUNCTIONS[name](*arguments)
    else:
        raise ValueError(f"unsupported evaluation node: {type(node).__name__}")
    if (
        isinstance(result, complex)
        or not math.isfinite(float(result))
        or abs(float(result)) > 1e100
    ):
        raise ValueError("formula result is non-finite or out of bounds")
    return float(result)


class FormulaEngine:
    def __init__(self, formulas: Sequence[FormulaDefinition] = ()) -> None:
        self._formulas: dict[str, FormulaDefinition] = {}
        for formula in formulas:
            self.register(formula)

    def register(self, formula: FormulaDefinition) -> None:
        if formula.formula_id in self._formulas:
            raise ValueError(f"duplicate formula id: {formula.formula_id}")
        if formula.status == "executable":
            if not formula.variables:
                raise ValueError(
                    f"formula {formula.formula_id} has no declared variables"
                )
            if not formula.assumptions:
                raise ValueError(
                    f"formula {formula.formula_id} has no declared assumptions"
                )
            if not formula.authoritative_source or not formula.validation:
                raise ValueError(
                    f"formula {formula.formula_id} lacks source or validation authority"
                )
            if not formula.expected_examples or not formula.property_cases:
                raise ValueError(
                    f"formula {formula.formula_id} lacks example or property evidence"
                )
            tree = ast.parse(formula.expression, mode="eval")
            _validate_ast(tree, set(formula.variables))
            actual = _dimension(tree, formula.variables)
            if actual != formula.output_dimension:
                raise ValueError(
                    f"formula {formula.formula_id} output dimension {actual.render()} != {formula.output_dimension.render()}"
                )
            for index, example in enumerate(formula.expected_examples):
                inputs = example.get("inputs")
                if not isinstance(inputs, Mapping) or set(map(str, inputs)) != set(
                    formula.variables
                ):
                    raise ValueError(
                        f"formula {formula.formula_id} example {index} inputs mismatch"
                    )
                actual_value = _evaluate(
                    tree, {str(name): float(value) for name, value in inputs.items()}
                )
                expected = float(example["expected"])
                tolerance = float(example.get("tolerance", 1e-9))
                if tolerance < 0 or not math.isclose(
                    actual_value, expected, rel_tol=tolerance, abs_tol=tolerance
                ):
                    raise ValueError(
                        f"formula {formula.formula_id} example {index} failed"
                    )
        self._formulas[formula.formula_id] = formula

    def describe(self, formula_id: str) -> dict[str, Any]:
        formula = self._formulas[formula_id]
        return {
            "id": formula.formula_id,
            "expression": formula.expression,
            "variables": {
                name: {
                    "dimension": variable.dimension.render(),
                    "minimum": variable.minimum,
                    "maximum": variable.maximum,
                }
                for name, variable in formula.variables.items()
            },
            "output_dimension": formula.output_dimension.render(),
            "assumptions": list(formula.assumptions),
            "status": formula.status,
            "source": formula.source,
            "authoritative_source": formula.authoritative_source,
            "expected_examples": list(formula.expected_examples),
            "property_cases": list(formula.property_cases),
            "validation": formula.validation,
        }

    def evaluate(
        self,
        formula_id: str,
        values: Mapping[str, float],
        *,
        standard_uncertainties: Mapping[str, float] | None = None,
        covariances: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        formula = self._formulas[formula_id]
        if formula.status != "executable":
            raise ValueError(
                f"formula {formula_id} is {formula.status}, not executable"
            )
        missing = sorted(set(formula.variables) - set(values))
        extra = sorted(set(values) - set(formula.variables))
        if missing or extra:
            raise ValueError(
                f"formula inputs mismatch; missing={missing}, extra={extra}"
            )
        numeric = {name: float(value) for name, value in values.items()}
        for name, variable in formula.variables.items():
            value = numeric[name]
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if variable.minimum is not None and value < variable.minimum:
                raise ValueError(f"{name} is below its domain minimum")
            if variable.maximum is not None and value > variable.maximum:
                raise ValueError(f"{name} is above its domain maximum")
        tree = ast.parse(formula.expression, mode="eval")
        result = _evaluate(tree, numeric)
        sensitivities: dict[str, float] = {}
        uncertainty_values: dict[str, float] = {}
        uncertainties = standard_uncertainties or {}
        unknown_uncertainties = sorted(set(map(str, uncertainties)) - set(numeric))
        if unknown_uncertainties:
            raise ValueError(
                f"uncertainties reference unknown variables: {unknown_uncertainties}"
            )
        for name, value in numeric.items():
            variable = formula.variables[name]
            step = max(abs(value) * 1e-6, 1e-8)
            can_minus = variable.minimum is None or value - step >= variable.minimum
            can_plus = variable.maximum is None or value + step <= variable.maximum
            plus, minus = dict(numeric), dict(numeric)
            plus[name], minus[name] = value + step, value - step
            if can_minus and can_plus:
                derivative = (_evaluate(tree, plus) - _evaluate(tree, minus)) / (
                    2 * step
                )
            elif can_plus:
                derivative = (_evaluate(tree, plus) - result) / step
            elif can_minus:
                derivative = (result - _evaluate(tree, minus)) / step
            else:
                derivative = 0.0
            sensitivities[name] = derivative
            uncertainty = float(uncertainties.get(name, 0.0))
            if uncertainty < 0 or not math.isfinite(uncertainty):
                raise ValueError(
                    "standard uncertainties must be finite and nonnegative"
                )
            uncertainty_values[name] = uncertainty
        variance = sum(
            (sensitivities[name] * uncertainty_values[name]) ** 2 for name in numeric
        )
        covariance_terms: list[dict[str, float | str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for pair, covariance_raw in (covariances or {}).items():
            parts = [
                item.strip()
                for item in str(pair).replace("|", ",").split(",")
                if item.strip()
            ]
            if len(parts) != 2 or any(name not in numeric for name in parts):
                raise ValueError(
                    f"invalid covariance key {pair!r}; use 'variable_a,variable_b'"
                )
            left, right = parts
            if left == right:
                raise ValueError(
                    "self-covariance belongs in standard_uncertainties, not covariances"
                )
            canonical_pair = tuple(sorted((left, right)))
            if canonical_pair in seen_pairs:
                raise ValueError(f"duplicate covariance pair: {left},{right}")
            seen_pairs.add(canonical_pair)
            covariance = float(covariance_raw)
            if not math.isfinite(covariance):
                raise ValueError("covariances must be finite")
            maximum_covariance = uncertainty_values[left] * uncertainty_values[right]
            if abs(covariance) > maximum_covariance + 1e-12:
                raise ValueError(
                    f"covariance {left},{right} violates |cov| <= u_left*u_right"
                )
            term = 2.0 * sensitivities[left] * sensitivities[right] * covariance
            variance += term
            covariance_terms.append(
                {
                    "pair": f"{canonical_pair[0]},{canonical_pair[1]}",
                    "covariance": covariance,
                    "variance_term": term,
                }
            )
        if variance < -1e-12:
            raise ValueError("covariance matrix produces negative propagated variance")
        variance = max(0.0, variance)
        payload = {
            "valid": True,
            "formula_id": formula_id,
            "result": result,
            "output_dimension": formula.output_dimension.render(),
            "sensitivities": sensitivities,
            "combined_standard_uncertainty": math.sqrt(variance),
            "covariance_terms": covariance_terms,
            "assumptions": list(formula.assumptions),
            "warning": "Uncertainty propagation is first-order local linearization around the supplied operating point.",
        }
        return {**payload, "result_sha256": stable_hash(payload)}

    def equivalence_check(
        self,
        left_id: str,
        right_id: str,
        cases: Sequence[Mapping[str, float]],
        *,
        relative_tolerance: float = 1e-9,
        absolute_tolerance: float = 1e-12,
    ) -> dict[str, Any]:
        if relative_tolerance < 0 or absolute_tolerance < 0:
            raise ValueError("equivalence tolerances must be nonnegative")
        left, right = self._formulas[left_id], self._formulas[right_id]
        if (
            set(left.variables) != set(right.variables)
            or left.output_dimension != right.output_dimension
        ):
            return {"equivalent": False, "reason": "signature mismatch", "cases": 0}
        failures = []
        for index, case in enumerate(cases):
            left_value = self.evaluate(left_id, case)["result"]
            right_value = self.evaluate(right_id, case)["result"]
            if not math.isclose(
                left_value,
                right_value,
                rel_tol=relative_tolerance,
                abs_tol=absolute_tolerance,
            ):
                failures.append(
                    {"case": index, "left": left_value, "right": right_value}
                )
        return {
            "equivalent": not failures and bool(cases),
            "cases": len(cases),
            "failures": failures[:20],
            "method": "bounded property comparison, not symbolic proof",
        }


def engine_from_payload(payload: Mapping[str, Any]) -> FormulaEngine:
    return FormulaEngine(
        tuple(
            FormulaDefinition.from_mapping(item) for item in payload.get("formulas", ())
        )
    )


def evaluate_formula(payload: Mapping[str, Any]) -> dict[str, Any]:
    engine = engine_from_payload(payload)
    return engine.evaluate(
        str(payload["formula_id"]),
        payload.get("values", {}),
        standard_uncertainties=payload.get("standard_uncertainties", {}),
        covariances=payload.get("covariances", {}),
    )


def compare_formulas(payload: Mapping[str, Any]) -> dict[str, Any]:
    engine = engine_from_payload(payload)
    return engine.equivalence_check(
        str(payload["left_id"]),
        str(payload["right_id"]),
        payload.get("cases", ()),
        relative_tolerance=float(payload.get("relative_tolerance", 1e-9)),
        absolute_tolerance=float(payload.get("absolute_tolerance", 1e-12)),
    )
