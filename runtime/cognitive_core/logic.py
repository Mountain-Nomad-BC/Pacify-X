"""Paraconsistent forward reasoning with explicit support and contradiction state.

This is deliberately small and inspectable. It does not attempt unrestricted theorem
proving. Contradictions remain local instead of making every proposition derivable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .common import stable_hash


class TruthValue(str, Enum):
    TRUE = "true"
    FALSE = "false"
    BOTH = "both"
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class Literal:
    predicate: str
    arguments: tuple[str, ...] = ()
    negated: bool = False
    scope: str = "global"

    @property
    def atom(self) -> tuple[str, tuple[str, ...], str]:
        return self.predicate, self.arguments, self.scope

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Literal":
        predicate = str(value.get("predicate", "")).strip()
        if not predicate:
            raise ValueError("literal predicate is required")
        arguments = tuple(str(item) for item in value.get("arguments", ()))
        return cls(
            predicate,
            arguments,
            bool(value.get("negated", False)),
            str(value.get("scope", "global")),
        )


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    premises: tuple[Literal, ...]
    conclusion: Literal
    exceptions: tuple[Literal, ...] = ()
    priority: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Rule":
        rule_id = str(value.get("id", "")).strip()
        if not rule_id:
            raise ValueError("rule id is required")
        premises = tuple(
            Literal.from_mapping(item) for item in value.get("premises", ())
        )
        if not premises:
            raise ValueError(f"rule {rule_id} requires premises")
        conclusion = Literal.from_mapping(value.get("conclusion", {}))
        exceptions = tuple(
            Literal.from_mapping(item) for item in value.get("exceptions", ())
        )
        return cls(
            rule_id, premises, conclusion, exceptions, int(value.get("priority", 0))
        )


class KnowledgeBase:
    def __init__(self) -> None:
        self._support: dict[tuple[str, tuple[str, ...], str], dict[bool, set[str]]] = {}
        self._derivations: list[dict[str, Any]] = []

    def add(self, literal: Literal, support_id: str) -> bool:
        polarities = self._support.setdefault(literal.atom, {False: set(), True: set()})
        before = len(polarities[literal.negated])
        polarities[literal.negated].add(str(support_id))
        return len(polarities[literal.negated]) != before

    def supports(self, literal: Literal) -> bool:
        return bool(self._support.get(literal.atom, {}).get(literal.negated, set()))

    def truth(self, atom: Literal) -> TruthValue:
        polarities = self._support.get(atom.atom, {False: set(), True: set()})
        positive, negative = bool(polarities[False]), bool(polarities[True])
        if positive and negative:
            return TruthValue.BOTH
        if positive:
            return TruthValue.TRUE
        if negative:
            return TruthValue.FALSE
        return TruthValue.NEITHER

    def infer(self, rules: Iterable[Rule], *, max_rounds: int = 64) -> dict[str, Any]:
        ordered = tuple(sorted(rules, key=lambda item: (-item.priority, item.rule_id)))
        if max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        rounds = 0
        changed = True
        while changed and rounds < max_rounds:
            rounds += 1
            changed = False
            for rule in ordered:
                if not all(self.supports(premise) for premise in rule.premises):
                    continue
                if any(self.supports(exception) for exception in rule.exceptions):
                    continue
                support_id = f"rule:{rule.rule_id}"
                if self.add(rule.conclusion, support_id):
                    changed = True
                    self._derivations.append(
                        {
                            "rule_id": rule.rule_id,
                            "premises": [
                                literal_to_mapping(item) for item in rule.premises
                            ],
                            "conclusion": literal_to_mapping(rule.conclusion),
                        }
                    )
        atoms = []
        contradictions = []
        for (predicate, arguments, scope), polarities in sorted(self._support.items()):
            literal = Literal(predicate, arguments, False, scope)
            truth = self.truth(literal)
            record = {
                "predicate": predicate,
                "arguments": list(arguments),
                "scope": scope,
                "truth": truth.value,
                "positive_support": sorted(polarities[False]),
                "negative_support": sorted(polarities[True]),
            }
            atoms.append(record)
            if truth is TruthValue.BOTH:
                contradictions.append(record)
        payload = {
            "valid": True,
            "rounds": rounds,
            "fixed_point_reached": not changed,
            "atoms": atoms,
            "contradictions": contradictions,
            "derivations": self._derivations,
            "logic": "four-valued paraconsistent forward chaining",
        }
        return {**payload, "result_sha256": stable_hash(payload)}


def literal_to_mapping(value: Literal) -> dict[str, Any]:
    return {
        "predicate": value.predicate,
        "arguments": list(value.arguments),
        "negated": value.negated,
        "scope": value.scope,
    }


def reason(payload: Mapping[str, Any]) -> dict[str, Any]:
    knowledge = KnowledgeBase()
    for index, item in enumerate(payload.get("facts", ())):
        literal = Literal.from_mapping(item)
        knowledge.add(literal, str(item.get("support_id", f"fact:{index}")))
    rules = tuple(Rule.from_mapping(item) for item in payload.get("rules", ()))
    result = knowledge.infer(rules, max_rounds=int(payload.get("max_rounds", 64)))
    queries = []
    for item in payload.get("queries", ()):
        literal = Literal.from_mapping(item)
        queries.append(
            {**literal_to_mapping(literal), "truth": knowledge.truth(literal).value}
        )
    result["queries"] = queries
    return result
