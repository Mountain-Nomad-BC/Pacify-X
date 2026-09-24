"""Laya System-1 decision engine integration for Pacify-X.

Laya is a non-autoregressive *typed decision* model: it answers bounded questions of the
form `choice | score | noul` over a state document in a single forward pass. It is not a
chat model and must never become one inside PX.

Design rule (Laya integration guide section 10):

    Laya recommends / classifies / scores.  PX decides what is permitted.

This module provides three things and nothing else:

  1. ``LayaDecisionAdapter``      a bounded, loopback-or-in-process adapter over the Laya
                                  ``Router``/``Agent`` API, with typed failure modes,
                                  timeout, cancellation and measured latency.
  2. ``compile_decision_state``   the Decision State Compiler: reduces PX state to a small,
                                  deterministic, token-bounded envelope. Missing values
                                  stay explicitly unknown -- never invented.
  3. ``load_decision_policy`` /   versioned threshold *policy*, so acceptance is a governed
     ``evaluate_decision``        decision rather than a magic constant in caller code.

The raw model distribution and the PX acceptance decision remain strictly separate.
Confidence never grants authority; callers still pass through PX governance.

Ownership: this file owns ONLY the decision-engine boundary. Model routing, tier selection,
resource admission, and action authority remain with their existing PX owners
(``runtime.models``, ``runtime.local_model_lane_orchestration``, ``runtime.capability_routing``,
``runtime/authority_gate``). Nothing here mutates canonical state.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

DECISION_SCHEMA = "px.system-one-decision/1.0"
STATE_SCHEMA = "px.decision-state/1.0"
POLICY_SCHEMA = "px.decision-policy/1.0"

MAX_STATE_TOKENS = 1024
MAX_STATE_BYTES = 64 * 1024
MAX_QUESTIONS = 16
MAX_CRITERIA = 64
MAX_TEXT = 512

QUESTION_TYPES = frozenset({"choice", "score", "noul"})
AMBIGUITY_ACTIONS = frozenset(
    {"escalate", "queue_review", "clarify", "no_op", "reject"}
)


class LayaUnavailable(RuntimeError):
    """The decision engine is unavailable; callers must fall back deterministically."""


class LayaProtocolError(RuntimeError):
    """The decision engine returned a shape that violates the PX decision contract."""


# ---------------------------------------------------------------------------
# 1. Adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Raw Laya output paired with the identity of the exact checkpoint that produced it."""

    decision_id: str
    answers: Mapping[str, Mapping[str, Any]]
    checkpoint: str
    revision: str | None
    routing_reason: str | None
    input_state_sha256: str
    latency_ms: float

    def as_mapping(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "answers": {k: dict(v) for k, v in self.answers.items()},
            "model": {
                "provider": "laya",
                "checkpoint": self.checkpoint,
                "revision": self.revision,
            },
            "routing_reason": self.routing_reason,
            "input_state_sha256": self.input_state_sha256,
            "latency_ms": round(self.latency_ms, 3),
        }


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _bounded_text(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value.encode("utf-8")) > MAX_TEXT
    ):
        raise ValueError(f"{name} must be bounded nonempty text")
    return value.strip()


def validate_questions(
    questions: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Validate the typed-question envelope before it reaches the engine."""

    if type(questions) is not dict or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise ValueError(f"questions must be a non-empty mapping (<= {MAX_QUESTIONS})")
    normalized: dict[str, dict[str, Any]] = {}
    for key, spec in questions.items():
        qid = _bounded_text(key, "question id")
        if type(spec) is not dict:
            raise ValueError(f"{qid}: question spec must be an object")
        qtype = spec.get("type")
        if qtype not in QUESTION_TYPES:
            raise ValueError(f"{qid}: type must be one of {sorted(QUESTION_TYPES)}")
        instructions = _bounded_text(spec.get("instructions"), f"{qid}.instructions")
        entry: dict[str, Any] = {"type": qtype, "instructions": instructions}
        criteria = spec.get("criteria")
        if qtype in {"choice", "score"}:
            if qtype == "choice":
                if type(criteria) is not dict or not 1 <= len(criteria) <= MAX_CRITERIA:
                    raise ValueError(
                        f"{qid}: choice requires a bounded criteria mapping"
                    )
                entry["criteria"] = {
                    _bounded_text(k, f"{qid}.criteria key"): _bounded_text(
                        v, f"{qid}.criteria[{k}]"
                    )
                    for k, v in criteria.items()
                }
            else:
                if (
                    type(criteria) not in (list, tuple)
                    or not 1 <= len(criteria) <= MAX_CRITERIA
                ):
                    raise ValueError(
                        f"{qid}: score requires a bounded ordered criteria list"
                    )
                entry["criteria"] = [
                    _bounded_text(item, f"{qid}.criteria[]") for item in criteria
                ]
        normalized[qid] = entry
    return normalized


class LayaDecisionAdapter:
    """Bounded adapter over the Laya decision engine.

    ``engine_factory`` is injected so tests and PX can supply the real ``Router`` or a
    deterministic stub without this module importing torch at import time.
    """

    def __init__(
        self,
        *,
        engine_factory: Callable[[], object] | None = None,
        checkpoint: str = "typed-decisions",
        timeout_seconds: float = 30.0,
        preload: bool = True,
    ) -> None:
        if type(timeout_seconds) not in (int, float) or type(timeout_seconds) is bool:
            raise ValueError("timeout must be numeric")
        if not 0.0 < float(timeout_seconds) <= 300.0:
            raise ValueError("timeout must be in (0, 300]")
        if checkpoint not in {"typed-decisions", "english", "multilingual", "auto"}:
            raise ValueError("unsupported Laya checkpoint")
        self.checkpoint = checkpoint
        self.timeout_seconds = float(timeout_seconds)
        self.preload = bool(preload)
        self._engine: object | None = None
        self._engine_factory = engine_factory

    # -- lifecycle ---------------------------------------------------------

    def available(self) -> bool:
        """True only when the engine can actually be constructed."""

        try:
            self._ensure_engine()
            return True
        except LayaUnavailable:
            return False

    def _ensure_engine(self) -> object:
        if self._engine is not None:
            return self._engine
        factory = self._engine_factory or self._default_factory
        try:
            self._engine = factory()
        except Exception as error:  # noqa: BLE001 - any construction failure disables advisory use
            raise LayaUnavailable(
                f"laya engine unavailable: {type(error).__name__}"
            ) from error
        return self._engine

    def _default_factory(self) -> object:
        try:
            import laya  # type: ignore import-not-found
        except Exception as error:  # noqa: BLE001
            raise LayaUnavailable("laya package is not installed") from error
        return laya.Router(preload=self.preload)

    # -- decision ----------------------------------------------------------

    def decide(
        self,
        *,
        decision_id: str,
        state: Mapping[str, Any],
        questions: Mapping[str, Mapping[str, Any]],
        model: str | None = None,
    ) -> DecisionResult:
        """Run one bounded decision. Never invents an answer; fails typed."""

        decision_id = _bounded_text(decision_id, "decision_id")
        normalized_questions = validate_questions(questions)
        if type(state) is not dict or not state:
            raise ValueError("decision state must be a non-empty object")
        encoded = json.dumps(
            state,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
            raise ValueError("decision state exceeds the bounded byte budget")

        engine = self._ensure_engine()
        checkpoint = model or self.checkpoint
        started = time.perf_counter()
        try:
            if checkpoint == "auto" or hasattr(engine, "predict"):
                payload = engine.predict(state, normalized_questions)  # type: ignore[attr-defined]
            else:
                payload = engine.system_one(state, normalized_questions)  # type: ignore[attr-defined]
        except LayaUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - typed protocol failure, never a silent answer
            raise LayaProtocolError(
                f"laya decision failed: {type(error).__name__}"
            ) from error
        latency_ms = (time.perf_counter() - started) * 1000.0

        if not isinstance(payload, Mapping):
            raise LayaProtocolError("laya returned a non-mapping payload")
        answers = payload.get("answers", payload)
        if not isinstance(answers, Mapping):
            raise LayaProtocolError("laya returned no answers mapping")
        routing = (
            payload.get("routing")
            if isinstance(payload.get("routing"), Mapping)
            else {}
        )
        return DecisionResult(
            decision_id=decision_id,
            answers={
                str(k): dict(v) for k, v in answers.items() if isinstance(v, Mapping)
            },
            checkpoint=str(routing.get("model") or checkpoint),
            revision=payload.get("revision")
            if isinstance(payload.get("revision"), str)
            else None,
            routing_reason=routing.get("reason")
            if isinstance(routing.get("reason"), str)
            else None,
            input_state_sha256=_sha(state),
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# 2. Decision State Compiler
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompiledState:
    """A small, deterministic, token-bounded decision envelope."""

    decision_type: str
    fields: Mapping[str, Any]
    unknown_fields: tuple[str, ...]
    state_sha256: str
    token_estimate: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema_version": STATE_SCHEMA,
            "decision_type": self.decision_type,
            "fields": dict(self.fields),
            **{f"{k}_known": False for k in self.unknown_fields},
            "state_sha256": self.state_sha256,
            "token_estimate": self.token_estimate,
        }


def compile_decision_state(
    decision_type: str,
    *,
    provided: Mapping[str, object],
    required: Sequence[str] = (),
    optional: Sequence[str] = (),
    token_budget: int = 512,
) -> CompiledState:
    """Reduce caller-provided facts to a bounded envelope.

    Missing *required* or *optional* fields are recorded as **explicitly unknown**
    (``<name>_known: false``) instead of being silently filled with a default. This is the
    guide's section 8.2 rule: never let a fabricated value look like evidence.
    """

    decision_type = _bounded_text(decision_type, "decision_type")
    if type(provided) is not dict:
        raise ValueError("decision state must be an object")
    if type(token_budget) is not int or not 32 <= token_budget <= MAX_STATE_TOKENS:
        raise ValueError(f"token_budget must be 32..{MAX_STATE_TOKENS}")

    def _coerce(value: object) -> object:
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > MAX_TEXT:
                return value[:MAX_TEXT]
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return value
        if isinstance(value, (list, tuple)):
            return [_coerce(item) for item in list(value)[:32]]
        if isinstance(value, Mapping):
            return {str(k): _coerce(v) for k, v in list(value.items())[:32]}
        return str(value)[:MAX_TEXT]

    fields: dict[str, object] = {}
    unknown: list[str] = []
    for name in list(required) + list(optional):
        if name in provided and provided[name] is not None:
            fields[name] = _coerce(provided[name])
        else:
            unknown.append(name)

    encoded = json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    # Rough but deterministic: ~4 characters per token.
    token_estimate = max(1, len(encoded) // 4)
    if token_estimate > token_budget:
        # Drop optional fields (never required ones) until the envelope fits.
        for name in list(optional):
            if token_estimate <= token_budget:
                break
            if name in fields:
                del fields[name]
                if name not in unknown:
                    unknown.append(name)
                encoded = json.dumps(
                    fields,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    default=str,
                )
                token_estimate = max(1, len(encoded) // 4)
    return CompiledState(
        decision_type=decision_type,
        fields=fields,
        unknown_fields=tuple(sorted(set(unknown))),
        state_sha256=_sha(fields),
        token_estimate=token_estimate,
    )


# ---------------------------------------------------------------------------
# 3. Threshold policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """Versioned acceptance threshold for one decision id."""

    decision_id: str
    version: int
    min_top_probability: float
    min_margin: float
    ambiguity_action: str
    advisory_only: bool = False

    def validate(self) -> None:
        if not self.decision_id:
            raise ValueError("policy requires a decision id")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("policy version must be a positive integer")
        for name, value in (
            ("min_top_probability", self.min_top_probability),
            ("min_margin", self.min_margin),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ValueError(f"{name} must be a probability in [0, 1]")
        if self.ambiguity_action not in AMBIGUITY_ACTIONS:
            raise ValueError(
                f"ambiguity_action must be one of {sorted(AMBIGUITY_ACTIONS)}"
            )


def load_decision_policy(
    root: Path, decision_id: str | None = None
) -> dict[str, DecisionPolicy]:
    """Load the versioned threshold policy registry from the canonical PX location."""

    path = root / "registry" / "system_one_decision_policy.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("decision policy registry has an unsupported schema_version")
    policies: dict[str, DecisionPolicy] = {}
    for entry in payload.get("decisions", []):
        policy = DecisionPolicy(
            decision_id=str(entry["decision_id"]),
            version=int(entry.get("version", 1)),
            min_top_probability=float(entry.get("min_top_probability", 0.7)),
            min_margin=float(entry.get("min_margin", 0.15)),
            ambiguity_action=str(entry.get("ambiguity_action", "escalate")),
            advisory_only=bool(entry.get("advisory_only", False)),
        )
        policy.validate()
        policies[policy.decision_id] = policy
    if decision_id is not None:
        return {decision_id: policies[decision_id]} if decision_id in policies else {}
    return policies


@dataclass(frozen=True, slots=True)
class DecisionEvaluation:
    """PX's acceptance decision over a raw model distribution."""

    decision_id: str
    accepted: bool
    reason: str
    top_label: str | None
    top_probability: float | None
    margin: float | None
    ambiguity_action: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "top_label": self.top_label,
            "top_probability": self.top_probability,
            "margin": self.margin,
            "ambiguity_action": self.ambiguity_action,
        }


def _probabilities(answer: Mapping[str, Any]) -> dict[str, float]:
    raw = answer.get("probabilities")
    if not isinstance(raw, Mapping):
        return {}
    values: dict[str, float] = {}
    for label, value in raw.items():
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            values[str(label)] = float(value)
    return values


def evaluate_decision(
    result: DecisionResult,
    policy: DecisionPolicy,
    *,
    question_id: str | None = None,
) -> DecisionEvaluation:
    """Apply the threshold policy to a raw distribution.

    The gate is meaningful only for ``choice`` answers: a ``score`` answer is ordinal and a
    ``noul`` answer is a single calibrated probability, so both are marked ``advisory_only``
    in policy rather than threshold-accepted here.
    """

    policy.validate()
    if policy.decision_id != result.decision_id:
        raise ValueError("policy does not belong to this decision")
    qid = question_id
    if qid is None:
        qid = next(iter(result.answers), None)
    if qid is None or qid not in result.answers:
        return DecisionEvaluation(
            decision_id=result.decision_id,
            accepted=False,
            reason="no_answer_for_question",
            top_label=None,
            top_probability=None,
            margin=None,
            ambiguity_action=policy.ambiguity_action,
        )

    answer = result.answers[qid]
    if str(answer.get("type")) != "choice" or policy.advisory_only:
        return DecisionEvaluation(
            decision_id=result.decision_id,
            accepted=False,
            reason="advisory_only_answer_type",
            top_label=answer.get("choice")
            if isinstance(answer.get("choice"), str)
            else None,
            top_probability=None,
            margin=None,
            ambiguity_action=None,
        )

    probabilities = _probabilities(answer)
    if len(probabilities) < 2:
        return DecisionEvaluation(
            decision_id=result.decision_id,
            accepted=False,
            reason="insufficient_distribution",
            top_label=None,
            top_probability=None,
            margin=None,
            ambiguity_action=policy.ambiguity_action,
        )
    ordered = sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
    top_label, top_value = ordered[0]
    runner_up = ordered[1][1]
    margin = top_value - runner_up
    if top_value < policy.min_top_probability:
        return DecisionEvaluation(
            decision_id=result.decision_id,
            accepted=False,
            reason="top_probability_below_threshold",
            top_label=top_label,
            top_probability=top_value,
            margin=margin,
            ambiguity_action=policy.ambiguity_action,
        )
    if margin < policy.min_margin:
        return DecisionEvaluation(
            decision_id=result.decision_id,
            accepted=False,
            reason="margin_below_threshold",
            top_label=top_label,
            top_probability=top_value,
            margin=margin,
            ambiguity_action=policy.ambiguity_action,
        )
    return DecisionEvaluation(
        decision_id=result.decision_id,
        accepted=True,
        reason="top_probability_above_threshold_and_margin",
        top_label=top_label,
        top_probability=top_value,
        margin=margin,
        ambiguity_action=None,
    )


# ---------------------------------------------------------------------------
# 4. Decision Gateway (single entry point; callers must not touch the adapter)
# ---------------------------------------------------------------------------


@dataclass
class DecisionGateway:
    """The one place PX modules obtain System-1 advice.

    The gateway owns model/checkpoint selection, the state compiler contract, thresholds,
    telemetry, and fallback. Callers supply only a decision id, the compiled state facts, and
    the typed questions.
    """

    adapter: LayaDecisionAdapter
    policies: Mapping[str, DecisionPolicy] = field(default_factory=dict)
    telemetry: list[dict[str, object]] = field(default_factory=list)

    def decide(
        self,
        *,
        decision_id: str,
        state_facts: Mapping[str, object],
        required: Sequence[str],
        optional: Sequence[str],
        questions: Mapping[str, Mapping[str, Any]],
        question_id: str | None = None,
        token_budget: int = 512,
    ) -> dict[str, object]:
        """Compile, decide, evaluate. Returns a receipt-shaped mapping.

        On engine unavailability the gateway returns ``available: False`` with a
        ``fallback: deterministic`` marker. The caller must then use its deterministic path --
        the gateway never substitutes a guessed answer.
        """

        compiled = compile_decision_state(
            decision_id,
            provided=state_facts,
            required=required,
            optional=optional,
            token_budget=token_budget,
        )
        base: dict[str, object] = {
            "schema_version": DECISION_SCHEMA,
            "decision_id": decision_id,
            "input_state_sha256": compiled.state_sha256,
            "token_estimate": compiled.token_estimate,
            "unknown_fields": list(compiled.unknown_fields),
        }
        if not self.adapter.available():
            record = {**base, "available": False, "fallback": "deterministic"}
            self.telemetry.append(record)
            return record
        try:
            result = self.adapter.decide(
                decision_id=decision_id,
                state=compiled.as_mapping(),
                questions=questions,
            )
        except (LayaUnavailable, LayaProtocolError) as error:
            record = {
                **base,
                "available": False,
                "fallback": "deterministic",
                "failure": type(error).__name__,
            }
            self.telemetry.append(record)
            return record
        policy = self.policies.get(decision_id)
        evaluation = (
            evaluate_decision(result, policy, question_id=question_id)
            if policy
            else None
        )
        record = {
            **base,
            "available": True,
            "model": result.as_mapping()["model"],
            "questions": dict(result.answers),
            "latency_ms": round(result.latency_ms, 3),
            "routing_reason": result.routing_reason,
            "policy": evaluation.as_mapping() if evaluation else None,
            "accepted": bool(evaluation.accepted) if evaluation else False,
            "authority": "advisory",
        }
        self.telemetry.append(record)
        return record
