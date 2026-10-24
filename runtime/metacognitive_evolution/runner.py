"""Governed metacognitive-evolution runner (punch cards EVO-001..005, W8).

The facade exposes operations; it does not *evolve* anything by itself. This
runner is the normal execution entrypoint that drives them through the full
governed lifecycle:

    propose -> bounded experiment -> held-out evaluation -> evidence-backed
    promotion OR rollback

It invents no results. A promotion is granted only when the held-out evaluation
meets the declared threshold AND the experiment is inside its declared bound. A
failed or inconclusive experiment rolls back to the recorded baseline rather than
being silently promoted. Nothing here grants runtime authority: a promotion
produces a candidate change plus its evidence, which a human/admitted owner then
applies.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping

from .facade import run_operation

SCHEMA_VERSION = "px.metacognitive-evolution-run/1.0"
MAX_EXPERIMENTS = 16


class EvolutionError(ValueError):
    """Raised when an evolution run is invalid."""


@dataclass(frozen=True, slots=True)
class Experiment:
    experiment_id: str
    operation: str
    payload: Mapping[str, Any]
    held_out: tuple[Mapping[str, Any], ...]
    threshold: float
    baseline: Mapping[str, Any] | None


def _validate_experiment(experiment: Experiment) -> None:
    if type(experiment) is not Experiment:
        raise EvolutionError("evolution requires typed experiments")
    if (type(experiment.experiment_id) is not str or not experiment.experiment_id.strip()
            or len(experiment.experiment_id) > 256):
        raise EvolutionError("experiment requires a bounded identity")
    if (type(experiment.operation) is not str
            or experiment.operation not in {"induce-theory", "evaluate-optimization",
                                            "plan-capability-mutation", "lint-semantic-contract"}):
        raise EvolutionError("experiment operation is not an admitted evolution operation")
    if (not isinstance(experiment.payload, Mapping) or type(experiment.held_out) is not tuple
            or not experiment.held_out):
        raise EvolutionError("experiment requires a bounded payload and non-empty typed held-out set")
    if len(experiment.held_out) > 256:
        raise EvolutionError("held-out evaluation set exceeds its bound")
    if any(not isinstance(row, Mapping) for row in experiment.held_out):
        raise EvolutionError("held-out evaluation cases must be objects")
    if experiment.baseline is not None and not isinstance(experiment.baseline, Mapping):
        raise EvolutionError("experiment baseline must be an object or None")
    if type(experiment.threshold) not in (int, float):
        raise EvolutionError("experiment threshold must be within 0..1")
    threshold = float(experiment.threshold)
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise EvolutionError("experiment threshold must be within 0..1")
def _run_single_experiment(experiment: Experiment, *, validate: Callable[[Mapping[str, Any], tuple], Mapping[str, Any]] | None = None,
                           proposed: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run one bounded experiment and evaluate it on held-out cases.

    ``validate`` is the held-out evaluator. When absent, the facade's own
    ``validate-theory`` operation is used, which is the canonical held-out
    evaluator for induced theories. A promotion is granted only when the held-out
    result reports success at or above the threshold.
    """
    _validate_experiment(experiment)
    proposed = run_operation(experiment.operation, dict(experiment.payload)) if proposed is None else dict(proposed)
    if not isinstance(proposed, dict):
        raise EvolutionError("evolution operation did not return an object")
    if proposed.get("valid") is not True:
        raise EvolutionError("evolution proposal was rejected by its canonical operation")
    if validate is not None:
        evaluation = validate(proposed, experiment.held_out)
    else:
        if experiment.operation != "induce-theory":
            raise EvolutionError("non-theory experiments require their own held-out evaluator")
        wrapped_evaluation = run_operation("validate-theory", {
            "proposal": proposed,
            "held_out_cases": list(experiment.held_out),
        })
        if wrapped_evaluation.get("valid") is not True:
            raise EvolutionError("canonical held-out theory evaluation failed")
        result = wrapped_evaluation.get("result")
        if not isinstance(result, dict):
            raise EvolutionError("canonical held-out theory evaluation returned no result")
        evaluation = {"valid": True, **result}
    if not isinstance(evaluation, dict):
        raise EvolutionError("held-out evaluation did not return an object")
    score = _score(evaluation)
    if evaluation.get("valid") is not True:
        raise EvolutionError("held-out evaluation did not return an explicit valid=true result")
    promoted = (score >= float(experiment.threshold)
                and evaluation.get("admit") is not False)
    body = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment.experiment_id,
        "operation": experiment.operation,
        "proposal_sha256": _digest(proposed),
        "held_out_count": len(experiment.held_out),
        "score": score,
        "threshold": float(experiment.threshold),
        "decision": "PROMOTE" if promoted else "ROLLBACK",
        "promoted_candidate": proposed if promoted else None,
        "rolled_back_to_baseline": None if promoted else experiment.baseline,
        "evaluation": evaluation,
        "authority_granted": False,
        "requires_human_application": True,
    }
    return {**body, "run_sha256": _digest(body)}


def run_experiment(experiment: Experiment, *, validate=None, iterative_subgraph=None,
                   repair=None, execution_context=None, current_epoch=None,
                   budget_snapshot=None, cancel_requested=None) -> dict[str, Any]:
    """Normal experiment owner with explicitly admitted bounded refinement.

    Existing one-shot callers retain their behavior. Iterative callers must bind
    actual context, cancellation, epoch and budget owners. The repair callback
    receives proposal data only: held-out cases and held-out scores are never
    supplied to it. Held-out evaluation runs exactly once, on the final proposal,
    inside the same budget/fence envelope. No recursive workflow edge is added.
    """
    _validate_experiment(experiment)
    if iterative_subgraph is None:
        if any(value is not None for value in (repair, execution_context, current_epoch, budget_snapshot, cancel_requested)):
            raise EvolutionError("iterative controls require an explicit iterative subgraph contract")
        return _run_single_experiment(experiment, validate=validate)
    from ..iterative_subgraph import IterationResult, run_iterative_subgraph
    if not callable(repair):
        raise EvolutionError("iterative evolution requires its admitted bounded proposal-repair consumer")

    def step(state, hop, attempt, context):
        proposal = run_operation(experiment.operation, dict(state))
        if not isinstance(proposal, dict) or proposal.get("valid") is not True:
            return IterationResult("ESCALATE", {"proposal_rejected": True})
        import json
        # The callback cannot mutate the final proposal by retaining a reference.
        isolated = json.loads(json.dumps(proposal, allow_nan=False))
        next_payload = repair(isolated, hop, attempt, context)
        if next_payload is not None:
            if not isinstance(next_payload, Mapping):
                raise EvolutionError("repair must return bounded proposal inputs or None")
            return IterationResult("CONTINUE", {"proposal_sha256": _digest(proposal)}, dict(next_payload))
        final = Experiment(experiment.experiment_id, experiment.operation, dict(state),
                           experiment.held_out, experiment.threshold, experiment.baseline)
        return IterationResult("COMPLETE", _run_single_experiment(final, validate=validate, proposed=proposal))

    outcome = run_iterative_subgraph(
        iterative_subgraph, dict(experiment.payload), execution_context=execution_context,
        step=step, current_epoch=current_epoch, budget_snapshot=budget_snapshot,
        cancel_requested=cancel_requested,
    )
    if outcome["status"] == "COMPLETE":
        body = {**outcome["value"], "iterative_subgraph": outcome}
        body.pop("run_sha256", None)
    else:
        body = {"schema_version": SCHEMA_VERSION, "experiment_id": experiment.experiment_id,
                "operation": experiment.operation, "decision": "ESCALATE",
                "promoted_candidate": None, "rolled_back_to_baseline": experiment.baseline,
                "iterative_subgraph": outcome, "authority_granted": False,
                "requires_human_application": True}
    return {**body, "run_sha256": _digest(body)}


def _score(evaluation: Mapping[str, Any]) -> float:
    for key in ("score", "accuracy", "pass_rate", "validated_ratio", "held_out_pass_rate"):
        value = evaluation.get(key)
        if type(value) in (int, float):
            score = float(value)
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise EvolutionError("held-out score must be finite and within 0..1")
            return score
    # A boolean-only evaluator scores 1.0/0.0 rather than a fabricated fraction.
    return 1.0 if evaluation.get("valid") is True else 0.0


def run_bounded_experiments(experiments, *, validate=None, iterative_controls_for=None) -> dict[str, Any]:
    """Run a bounded set of experiments and report each decision.

    The bound is enforced: an over-large set is refused rather than truncated, so
    a runaway experiment loop cannot be mistaken for a     governed run.
    """
    from itertools import islice
    try:
        rows = tuple(islice(iter(experiments), MAX_EXPERIMENTS + 1))
    except TypeError as error:
        raise EvolutionError("bounded experiments must be an iterable") from error
    if not 1 <= len(rows) <= MAX_EXPERIMENTS:
        raise EvolutionError(f"bounded experiment set must be 1..{MAX_EXPERIMENTS}")
    for experiment in rows:
        _validate_experiment(experiment)
    if iterative_controls_for is not None and not callable(iterative_controls_for):
        raise EvolutionError("iterative batch controls must resolve exact per-experiment ownership")
    results = []
    for experiment in rows:
        controls = iterative_controls_for(experiment.experiment_id) if iterative_controls_for else {}
        allowed = {"iterative_subgraph", "repair", "execution_context", "current_epoch", "budget_snapshot", "cancel_requested"}
        if type(controls) is not dict or set(controls) - allowed:
            raise EvolutionError("iterative batch controls contain unknown or unavailable owners")
        results.append(run_experiment(experiment, validate=validate, **controls))
    body = {
        "schema_version": SCHEMA_VERSION,
        "experiment_count": len(results),
        "promoted": [row["experiment_id"] for row in results if row["decision"] == "PROMOTE"],
        "rolled_back": [row["experiment_id"] for row in results if row["decision"] == "ROLLBACK"],
        "escalated": [row["experiment_id"] for row in results if row["decision"] == "ESCALATE"],
        "results": results,
        "authority_granted": False,
    }
    return {**body, "batch_sha256": _digest(body)}


def _digest(value: object) -> str:
    import hashlib
    import json
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
