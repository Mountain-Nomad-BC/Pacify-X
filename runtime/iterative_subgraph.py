"""Bounded sequential reasoning inside one outer DAG node, never a cyclic DAG.

Limits constrain execution; they are not budget grants. The admitted host must
reserve work through existing owners before entry and supply current epoch and
budget observations. This module creates no registry, reservation, event bus,
process, model route, approval, or mutation authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import time
from typing import Callable, Mapping

from .execution_context import ExecutionContext

MAX_STATE_BYTES = 1_048_576


def _bytes(value: object) -> bytes:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_STATE_BYTES:
        raise ValueError("iterative subgraph state exceeds its bounded JSON contract")
    return data


@dataclass(frozen=True, slots=True)
class IterativeSubgraph:
    subgraph_id: str
    max_hops: int
    max_attempts: int
    time_budget_ms: int
    token_budget: int
    cost_budget_microunits: int
    effect_budget: int
    terminal_escalation: str

    def __post_init__(self) -> None:
        for name in ("subgraph_id", "terminal_escalation"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or len(value.encode()) > 256 or any(ord(c) < 32 for c in value):
                raise ValueError("iterative subgraph requires explicit bounded identity and escalation destination")
        for name, minimum, maximum in (("max_hops", 1, 16), ("max_attempts", 1, 16),
                ("time_budget_ms", 1, 600_000), ("token_budget", 0, 2**31),
                ("cost_budget_microunits", 0, 2**63 - 1), ("effect_budget", 0, 1024)):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"iterative subgraph {name} exceeds its hard bound")


@dataclass(frozen=True, slots=True)
class IterationBudgetSnapshot:
    """Actual monotone usage projected from an existing admitted budget owner."""
    execution_id: str
    epoch: int
    budget_owner: str
    receipt_sha256: str
    tokens: int
    cost_microunits: int
    effects: int

    def __post_init__(self) -> None:
        if any(type(getattr(self, name)) is not int or getattr(self, name) < 0
               for name in ("tokens", "cost_microunits", "effects")):
            raise ValueError("budget observation requires actual nonnegative integer counters")
        if type(self.epoch) is not int or self.epoch < 1:
            raise ValueError("budget observation requires a current positive epoch")
        if type(self.receipt_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.receipt_sha256) is None:
            raise ValueError("budget observation requires actual owner receipt identity")
        for value in (self.execution_id, self.budget_owner):
            if type(value) is not str or not value.strip() or len(value.encode()) > 512:
                raise ValueError("budget observation requires bounded native owner/execution identity")


@dataclass(frozen=True, slots=True)
class IterationResult:
    status: str  # COMPLETE, CONTINUE, RETRY, ESCALATE
    value: Mapping[str, object]
    next_state: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"COMPLETE", "CONTINUE", "RETRY", "ESCALATE"}:
            raise ValueError("iterative step returned an unknown disposition")
        if not isinstance(self.value, Mapping) or self.next_state is not None and not isinstance(self.next_state, Mapping):
            raise ValueError("iterative step state must be bounded JSON objects")
        _bytes(dict(self.value))
        if self.next_state is not None:
            _bytes(dict(self.next_state))


def run_iterative_subgraph(
    specification: IterativeSubgraph, initial_state: Mapping[str, object],
    *, execution_context: ExecutionContext,
    step: Callable[[Mapping[str, object], int, int, ExecutionContext], IterationResult],
    current_epoch: Callable[[], int],
    budget_snapshot: Callable[[ExecutionContext], IterationBudgetSnapshot],
    cancel_requested: Callable[[], bool],
) -> dict[str, object]:
    if type(specification) is not IterativeSubgraph or type(execution_context) is not ExecutionContext:
        raise ValueError("iterative execution requires its explicit contract and canonical execution context")
    if any(not callable(callback) for callback in (step, current_epoch, budget_snapshot, cancel_requested)):
        raise ValueError("iterative execution requires actual epoch, cancellation and existing budget-owner consumers")
    state = json.loads(_bytes(dict(initial_state)))
    started = time.monotonic()
    deadline = datetime.fromisoformat(execution_context.deadline_utc.replace("Z", "+00:00"))
    baseline = budget_snapshot(execution_context)
    if type(baseline) is not IterationBudgetSnapshot:
        raise ValueError("iterative budget owner returned no typed observation")
    if baseline.execution_id != execution_context.execution_id or baseline.epoch != execution_context.epoch:
        raise ValueError("iterative budget observation belongs to a stale or different execution")
    previous = baseline
    history: list[dict[str, object]] = []
    hop = 0
    attempt = 0
    result_value: Mapping[str, object] | None = None
    reason = "UNFINISHED"
    status = "ESCALATE"

    def fence() -> tuple[str | None, IterationBudgetSnapshot]:
        nonlocal previous
        cancellation = cancel_requested()
        if type(cancellation) is not bool:
            return "CANCELLATION_OWNER_INVALID", previous
        if cancellation:
            return "CANCELLED", previous
        epoch = current_epoch()
        if type(epoch) is not int or epoch != execution_context.epoch:
            return "STALE_EPOCH", previous
        if datetime.now(timezone.utc) >= deadline or (time.monotonic() - started) * 1000 >= specification.time_budget_ms:
            return "TIME_BUDGET_EXHAUSTED", previous
        snapshot = budget_snapshot(execution_context)
        if (type(snapshot) is not IterationBudgetSnapshot or snapshot.execution_id != execution_context.execution_id
                or snapshot.epoch != execution_context.epoch or snapshot.budget_owner != baseline.budget_owner):
            return "BUDGET_OWNER_IDENTITY_CHANGED", previous
        values = (snapshot.tokens, snapshot.cost_microunits, snapshot.effects)
        prior = (previous.tokens, previous.cost_microunits, previous.effects)
        if any(current < old for current, old in zip(values, prior)):
            return "BUDGET_COUNTER_REGRESSION", previous
        previous = snapshot
        limits = (specification.token_budget, specification.cost_budget_microunits, specification.effect_budget)
        initial = (baseline.tokens, baseline.cost_microunits, baseline.effects)
        if any(current - old > limit for current, old, limit in zip(values, initial, limits)):
            return "BUDGET_EXCEEDED", snapshot
        return None, snapshot

    while hop < specification.max_hops and attempt < specification.max_attempts:
        failed_fence, snapshot = fence()
        if failed_fence:
            reason = failed_fence
            break
        attempt += 1
        invocation_id = "iterative-" + hashlib.sha256(_bytes({
            "parent_execution_id": execution_context.execution_id,
            "subgraph_id": specification.subgraph_id, "epoch": execution_context.epoch,
            "attempt": attempt,
        })).hexdigest()[:40]
        remaining_seconds = max(0.0, specification.time_budget_ms / 1000 - (time.monotonic() - started))
        child_deadline = min(deadline, datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds))
        child_context = execution_context.child(invocation_id, deadline_utc=child_deadline.isoformat())
        try:
            result = step(json.loads(_bytes(state)), hop, attempt, child_context)
            if type(result) is not IterationResult:
                raise ValueError("iterative step did not return a bounded typed disposition")
        except Exception as error:
            # No implicit retry of potentially effectful failures.
            failure_fence, snapshot = fence()
            reason = failure_fence or "STEP_FAILED"
            history.append({"hop": hop, "attempt": attempt, "status": "FAILED",
                            "execution_id": child_context.execution_id,
                            "failure_type": type(error).__name__, "budget_receipt_sha256": snapshot.receipt_sha256})
            break
        failed_fence, snapshot = fence()
        history.append({"hop": hop, "attempt": attempt, "status": result.status,
                        "execution_id": child_context.execution_id, "execution_context_sha256": child_context.context_sha256,
                        "value_sha256": hashlib.sha256(_bytes(dict(result.value))).hexdigest(),
                        "budget_receipt_sha256": snapshot.receipt_sha256})
        if failed_fence:
            reason = failed_fence
            break
        result_value = json.loads(_bytes(dict(result.value)))
        if result.status == "COMPLETE":
            status, reason = "COMPLETE", "BOUNDED_STEP_COMPLETED"
            break
        if result.status == "ESCALATE":
            reason = "STEP_REQUESTED_ESCALATION"
            break
        if result.next_state is None:
            reason = "NEXT_STATE_MISSING"
            break
        state = json.loads(_bytes(dict(result.next_state)))
        if result.status == "CONTINUE":
            hop += 1
    else:
        reason = "HOP_LIMIT_EXHAUSTED" if hop >= specification.max_hops else "ATTEMPT_LIMIT_EXHAUSTED"
    body = {"schema_version": "px.iterative-subgraph-outcome/1.0",
            "subgraph_id": specification.subgraph_id, "specification": asdict(specification),
            "execution_id": execution_context.execution_id, "epoch": execution_context.epoch,
            "execution_context_sha256": execution_context.context_sha256,
            "status": status, "reason": reason, "attempts": attempt, "hops": hop,
            "terminal_escalation": specification.terminal_escalation if status != "COMPLETE" else None,
            "value": result_value if status == "COMPLETE" else None,
            "history": history, "final_budget_receipt_sha256": previous.receipt_sha256,
            "authority_granted": False, "outer_dag_changed": False}
    return {**body, "outcome_sha256": hashlib.sha256(_bytes(body)).hexdigest()}
