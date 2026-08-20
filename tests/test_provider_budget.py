from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from runtime.operational_event_bus import OperationalEventBus
from runtime.provider_budget import (
    BudgetExhaustedError,
    BudgetIntegrityError,
    DuplicateInvocationError,
    ProviderBudgetLedger,
    ProviderUsage,
    load_budget_policy,
)
from runtime.provider_gateway import (
    ProviderInvocationGateway,
    ProviderRequest,
    ProviderResponse,
)


ROOT = Path(__file__).resolve().parents[1]


def _policy_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "budget_id": "budget-1",
        "actor_id": "agent-1",
        "provider_id": "provider-1",
        "currency": "USD",
        "enabled": True,
        "hard_limit_microunits": 500,
        "warning_threshold_microunits": 400,
        "max_requests": 5,
        "max_input_tokens": 500,
        "max_output_tokens": 500,
        "max_charge_per_request_microunits": 100,
        "unknown_billing": "deny",
        "unknown_charge_microunits": 0,
        "fallback_adapter_ids": [],
    }
    row.update(overrides)
    return row


def _engine(tmp_path: Path, policy: dict[str, object]) -> Path:
    root = tmp_path / "engine"
    (root / "contracts/operations").mkdir(parents=True)
    (root / "registry").mkdir()
    for name in (
        "provider-budget-policy.schema.json",
        "provider-adapter-registry.schema.json",
        "operation-event.schema.json",
        "route-observer-registry.schema.json",
    ):
        shutil.copyfile(
            ROOT / "contracts/operations" / name,
            root / "contracts/operations" / name,
        )
    (root / "registry/provider_budget_policy.json").write_text(
        json.dumps(
            {
                "schema_version": "px.provider-budget-policy/1.0",
                "policy": "test deterministic provider limits",
                "budgets": [policy],
            }
        ),
        encoding="utf-8",
    )
    return root


def _ledger(tmp_path: Path, policy: dict[str, object]) -> ProviderBudgetLedger:
    engine = _engine(tmp_path, policy)
    state = tmp_path / "state"
    state.mkdir()
    return ProviderBudgetLedger(engine, state / "provider-budget", state)


def _reserve(
    ledger: ProviderBudgetLedger,
    invocation_id: str = "invocation-1",
    *,
    billing_state: str = "actual",
) -> dict[str, object]:
    return ledger.reserve(
        invocation_id=invocation_id,
        correlation_id="correlation-1",
        budget_id="budget-1",
        actor_id="agent-1",
        provider_id="provider-1",
        adapter_id="primary-adapter",
        billing_state=billing_state,
        max_input_tokens=20,
        max_output_tokens=30,
    )


@pytest.mark.parametrize("billing_state", ["actual", "estimated"])
def test_known_billing_settles_usage_and_releases_reservation(
    tmp_path: Path, billing_state: str
) -> None:
    ledger = _ledger(tmp_path, _policy_row())
    reserved = _reserve(ledger, billing_state=billing_state)
    settled = ledger.settle(
        "invocation-1",
        outcome="success",
        usage=ProviderUsage(billing_state, 10, 12, 35, "remote-request-1"),
    )
    counters = next(iter(ledger.snapshot()["budgets"].values()))
    assert reserved["reserved_charge_microunits"] == 100
    assert settled["settlement_basis"] == billing_state
    assert counters["settled_charge_microunits"] == 35
    assert counters["reserved_charge_microunits"] == 0
    serialized = json.dumps(ledger.snapshot())
    assert "remote-request-1" not in serialized


def test_unknown_billing_is_denied_or_conservatively_burned(tmp_path: Path) -> None:
    denied = _ledger(tmp_path / "denied", _policy_row())
    with pytest.raises(PermissionError, match="unknown provider billing"):
        _reserve(denied, billing_state="unknown")

    allowed = _ledger(
        tmp_path / "allowed",
        _policy_row(
            unknown_billing="allow_conservative_burn",
            unknown_charge_microunits=75,
        ),
    )
    _reserve(allowed, billing_state="unknown")
    receipt = allowed.settle(
        "invocation-1",
        outcome="success",
        usage=ProviderUsage("unknown", 2, 3, None),
    )
    assert receipt["charge_microunits"] == 75
    assert receipt["settlement_basis"] == "unknown_conservative_burn"


def test_warning_and_hard_exhaustion_are_decided_before_execution(
    tmp_path: Path,
) -> None:
    ledger = _ledger(
        tmp_path,
        _policy_row(
            hard_limit_microunits=100,
            warning_threshold_microunits=100,
            max_charge_per_request_microunits=100,
        ),
    )
    receipt = _reserve(ledger)
    assert receipt["warning_threshold_reached"] is True
    with pytest.raises(BudgetExhaustedError, match="hard limit"):
        _reserve(ledger, "invocation-2")


def test_local_non_billable_tracks_tokens_without_spend(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        _policy_row(
            hard_limit_microunits=0,
            warning_threshold_microunits=0,
            max_charge_per_request_microunits=0,
        ),
    )
    _reserve(ledger, billing_state="local_non_billable")
    receipt = ledger.settle(
        "invocation-1",
        outcome="success",
        usage=ProviderUsage("local_non_billable", 4, 5, 0),
    )
    assert receipt["charge_microunits"] == 0
    assert receipt["settlement_basis"] == "local_non_billable"


def test_provider_overrun_is_recorded_at_actual_cost_and_flagged(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, _policy_row())
    _reserve(ledger)
    receipt = ledger.settle(
        "invocation-1",
        outcome="success",
        usage=ProviderUsage("actual", 21, 31, 150),
    )
    counters = next(iter(ledger.snapshot()["budgets"].values()))
    assert receipt["policy_overrun"] is True
    assert receipt["settlement_basis"] == "actual_overrun"
    assert counters["settled_charge_microunits"] == 150


def test_duplicate_restart_and_tamper_are_fail_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, _policy_row())
    _reserve(ledger)
    with pytest.raises(DuplicateInvocationError):
        _reserve(ledger)
    with pytest.raises(BudgetIntegrityError, match="identity differs"):
        ledger.reserve(
            invocation_id="invocation-1",
            correlation_id="different-correlation",
            budget_id="budget-1",
            actor_id="agent-1",
            provider_id="provider-1",
            adapter_id="primary-adapter",
            billing_state="actual",
            max_input_tokens=20,
            max_output_tokens=30,
        )
    restarted = ProviderBudgetLedger(
        ledger.engine_root, ledger.root, ledger.allowed_root
    )
    restarted.settle(
        "invocation-1",
        outcome="success",
        usage=ProviderUsage("actual", 1, 1, 1),
    )
    _reserve(restarted, "invocation-2")
    receipt_path = restarted.root / "receipts/invocation-2.reserved.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["reserved_charge_microunits"] = 1
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(BudgetIntegrityError, match="receipt integrity"):
        restarted.settle(
            "invocation-2",
            outcome="success",
            usage=ProviderUsage("actual", 1, 1, 1),
        )
    state_path = restarted.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["revision"] += 1
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(BudgetIntegrityError, match="integrity mismatch"):
        restarted.snapshot()


class _Adapter:
    def __init__(
        self, adapter_id: str, *, failure: bool = False, billing_state: str = "actual"
    ) -> None:
        self.adapter_id = adapter_id
        self.failure = failure
        self.billing_state = billing_state
        self.calls = 0

    def invoke(self, model_id: str, payload: dict[str, object]) -> ProviderResponse:
        self.calls += 1
        if self.failure:
            raise RuntimeError("provider-secret-error")
        return ProviderResponse(
            {"answer": payload["prompt"]},
            ProviderUsage(self.billing_state, 1, 1, 10, "provider-secret-id"),
        )


def _gateway_case(
    tmp_path: Path,
    policy: dict[str, object],
    *,
    fallback_registered: bool = True,
) -> tuple[ProviderInvocationGateway, ProviderBudgetLedger]:
    root = _engine(tmp_path, policy)
    adapters = [
        {
            "adapter_id": "primary-adapter",
            "provider_id": "provider-1",
            "mode": "remote",
            "implementation": "tests/test_provider_budget.py",
            "admitted": True,
            "status": "ready",
            "billing_state": "actual",
        }
    ]
    if fallback_registered:
        adapters.append(
            {
                "adapter_id": "fallback-adapter",
                "provider_id": "provider-1",
                "mode": "remote",
                "implementation": "tests/test_provider_budget.py",
                "admitted": True,
                "status": "ready",
                "billing_state": "actual",
            }
        )
    (root / "registry/provider_adapters.json").write_text(
        json.dumps(
            {
                "schema_version": "px.provider-adapter-registry/1.0",
                "policy": "test adapters",
                "adapters": adapters,
            }
        ),
        encoding="utf-8",
    )
    routes = json.loads(
        (ROOT / "registry/operation_route_registry.json").read_text(encoding="utf-8")
    )
    (root / "registry/operation_route_registry.json").write_text(
        json.dumps(routes), encoding="utf-8"
    )
    state = tmp_path / "state"
    state.mkdir()
    ledger = ProviderBudgetLedger(root, state / "budget", state)
    gateway = ProviderInvocationGateway(
        root, OperationalEventBus(root, state / "bus", state), ledger
    )
    return gateway, ledger


def _request() -> ProviderRequest:
    return ProviderRequest(
        invocation_id="invocation-1",
        correlation_id="correlation-1",
        project_id="project-1",
        adapter_id="primary-adapter",
        model_id="model-1",
        actor_id="agent-1",
        accountable_owner="owner-1",
        payload={"prompt": "content-secret"},
        budget_id="budget-1",
        max_input_tokens=10,
        max_output_tokens=10,
    )


def test_gateway_fallback_allowed_and_receipts_are_correlated(tmp_path: Path) -> None:
    gateway, ledger = _gateway_case(
        tmp_path,
        _policy_row(fallback_adapter_ids=["fallback-adapter"]),
    )
    primary = _Adapter("primary-adapter", failure=True)
    fallback = _Adapter("fallback-adapter")
    response, receipt = gateway.invoke(
        _request(), primary, fallback_adapter=fallback
    )
    assert response == {"answer": "content-secret"}
    assert primary.calls == fallback.calls == 1
    retained = json.loads(
        (ledger.root / "receipts/invocation-1-fallback.settled.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["budget_receipt_sha256"] == retained["receipt_sha256"]
    assert retained["correlation_id"] == "correlation-1"
    assert "content-secret" not in json.dumps(ledger.snapshot())
    assert "provider-secret" not in json.dumps(ledger.snapshot())


def test_gateway_fallback_denied_or_exhausted_never_calls_fallback(
    tmp_path: Path,
) -> None:
    denied_gateway, _ = _gateway_case(tmp_path / "denied", _policy_row())
    denied_fallback = _Adapter("fallback-adapter")
    with pytest.raises(PermissionError, match="fallback is denied"):
        denied_gateway.invoke(
            _request(), _Adapter("primary-adapter", failure=True),
            fallback_adapter=denied_fallback,
        )
    assert denied_fallback.calls == 0

    exhausted_gateway, _ = _gateway_case(
        tmp_path / "exhausted",
        _policy_row(
            hard_limit_microunits=100,
            warning_threshold_microunits=50,
            max_charge_per_request_microunits=100,
            fallback_adapter_ids=["fallback-adapter"],
        ),
    )
    exhausted_fallback = _Adapter("fallback-adapter")
    with pytest.raises(BudgetExhaustedError):
        exhausted_gateway.invoke(
            _request(), _Adapter("primary-adapter", failure=True),
            fallback_adapter=exhausted_fallback,
        )
    assert exhausted_fallback.calls == 0


def test_gateway_budget_exhaustion_and_duplicate_stop_before_adapter(
    tmp_path: Path,
) -> None:
    exhausted_gateway, _ = _gateway_case(
        tmp_path / "exhausted",
        _policy_row(max_requests=0),
    )
    never_called = _Adapter("primary-adapter")
    with pytest.raises(BudgetExhaustedError):
        exhausted_gateway.invoke(_request(), never_called)
    assert never_called.calls == 0

    gateway, _ = _gateway_case(tmp_path / "duplicate", _policy_row())
    first = _Adapter("primary-adapter")
    gateway.invoke(_request(), first)
    duplicate = _Adapter("primary-adapter")
    with pytest.raises(DuplicateInvocationError):
        gateway.invoke(_request(), duplicate)
    assert duplicate.calls == 0


def test_shipped_policy_and_adapters_are_default_deny() -> None:
    assert load_budget_policy(ROOT)["budgets"] == []
    adapters = json.loads(
        (ROOT / "registry/provider_adapters.json").read_text(encoding="utf-8")
    )["adapters"]
    assert adapters
    assert all(row["admitted"] is False for row in adapters)
    assert all(row["status"] == "unconfigured" for row in adapters)
