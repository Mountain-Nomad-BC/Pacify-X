"""Durable deterministic provider reservations, burn accounting, and receipts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from .contracts import ContractValidationError, validate_instance
from .file_lock import FileLock
from .wal_transaction import JsonArtifact, JsonWal


POLICY_PATH = Path("registry/provider_budget_policy.json")
POLICY_SCHEMA = Path("contracts/operations/provider-budget-policy.schema.json")
STATE_SCHEMA_VERSION = "px.provider-budget-ledger/1.0"
RECEIPT_SCHEMA_VERSION = "px.provider-budget-receipt/1.0"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


class BudgetError(RuntimeError):
    """Base class for fail-closed budget decisions."""


class BudgetExhaustedError(BudgetError):
    """Raised before execution when a deterministic hard limit is exhausted."""


class DuplicateInvocationError(BudgetError):
    """Raised when an invocation identity has already been reserved."""


class BudgetIntegrityError(BudgetError):
    """Raised when durable budget state or a duplicate identity is inconsistent."""


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Metadata-only usage returned by every provider adapter."""

    billing_state: str
    input_tokens: int
    output_tokens: int
    charge_microunits: int | None
    provider_request_id: str | None = None


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sealed(value: Mapping[str, object], field: str) -> dict[str, object]:
    result = dict(value)
    result.pop(field, None)
    result[field] = _sha(result)
    return result


def load_budget_policy(root: Path) -> dict[str, object]:
    """Load and semantically validate the versioned deterministic policy."""
    try:
        value = json.loads((root / POLICY_PATH).read_text(encoding="utf-8"))
        validate_instance(value, root / POLICY_SCHEMA)
    except (OSError, UnicodeError, json.JSONDecodeError, ContractValidationError) as error:
        raise ValueError("provider budget policy is invalid") from error
    identities: set[tuple[str, str, str]] = set()
    for raw in value["budgets"]:
        row = dict(raw)
        if len(row["actor_id"]) > 256 or len(row["provider_id"]) > 256:
            raise ValueError("provider budget identity exceeds its byte bound")
        if any(len(adapter_id) > 96 for adapter_id in row["fallback_adapter_ids"]):
            raise ValueError("provider fallback adapter identity exceeds its bound")
        identity = (row["budget_id"], row["actor_id"], row["provider_id"])
        if identity in identities:
            raise ValueError("duplicate provider budget identity")
        identities.add(identity)
        if row["warning_threshold_microunits"] > row["hard_limit_microunits"]:
            raise ValueError("provider budget warning threshold exceeds hard limit")
        if (
            row["max_charge_per_request_microunits"]
            > row["hard_limit_microunits"]
        ):
            raise ValueError("per-request provider reservation exceeds hard limit")
        if (
            row["unknown_billing"] == "allow_conservative_burn"
            and row["unknown_charge_microunits"] <= 0
        ):
            raise ValueError("unknown billing allowance requires a positive burn")
    return value


class ProviderBudgetLedger:
    """WAL-coordinated budget authority; it never retains provider content."""

    def __init__(self, engine_root: Path, root: Path, allowed_root: Path) -> None:
        self.engine_root = engine_root.resolve(strict=True)
        self.allowed_root = allowed_root.resolve(strict=True)
        self.root = root.resolve()
        try:
            self.root.relative_to(self.allowed_root)
        except ValueError as error:
            raise ValueError("provider budget root must be within allowed root") from error
        self.wal = JsonWal(self.root / "wal", self.allowed_root)

    @property
    def state_path(self) -> Path:
        return self.root / "ledger.json"

    def _empty_state(self) -> dict[str, object]:
        return _sealed(
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "revision": 0,
                "budgets": {},
                "invocations": {},
            },
            "state_sha256",
        )

    def _state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BudgetIntegrityError("provider budget ledger is unreadable") from error
        if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
            raise BudgetIntegrityError("provider budget ledger schema is invalid")
        if set(value) != {
            "schema_version", "revision", "budgets", "invocations", "state_sha256"
        } or _sealed(value, "state_sha256") != value:
            raise BudgetIntegrityError("provider budget ledger integrity mismatch")
        if not isinstance(value["budgets"], dict) or not isinstance(
            value["invocations"], dict
        ):
            raise BudgetIntegrityError("provider budget ledger structure is invalid")
        return value

    def _receipt(self, invocation_id: str, phase: str) -> dict[str, object]:
        path = self.root / "receipts" / f"{invocation_id}.{phase}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BudgetIntegrityError("provider budget receipt is unreadable") from error
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != RECEIPT_SCHEMA_VERSION
            or value.get("invocation_id") != invocation_id
            or _sealed(value, "receipt_sha256") != value
        ):
            raise BudgetIntegrityError("provider budget receipt integrity mismatch")
        return value

    def _policy(
        self, budget_id: str, actor_id: str, provider_id: str
    ) -> dict[str, object]:
        matches = [
            dict(row)
            for row in load_budget_policy(self.engine_root)["budgets"]
            if row["budget_id"] == budget_id
            and row["actor_id"] == actor_id
            and row["provider_id"] == provider_id
        ]
        if not matches or matches[0]["enabled"] is not True:
            raise PermissionError("provider budget identity is not enabled")
        return matches[0]

    @staticmethod
    def _usage_values(usage: ProviderUsage) -> tuple[int, int, int | None]:
        if usage.billing_state not in {
            "actual", "estimated", "unknown", "local_non_billable"
        }:
            raise ValueError("provider usage billing state is invalid")
        if usage.provider_request_id is not None and (
            not isinstance(usage.provider_request_id, str)
            or len(usage.provider_request_id.encode("utf-8")) > 512
        ):
            raise ValueError("provider request metadata identity exceeds its bound")
        if (
            not isinstance(usage.input_tokens, int)
            or isinstance(usage.input_tokens, bool)
            or usage.input_tokens < 0
            or not isinstance(usage.output_tokens, int)
            or isinstance(usage.output_tokens, bool)
            or usage.output_tokens < 0
            or (
                usage.charge_microunits is not None
                and (
                    not isinstance(usage.charge_microunits, int)
                    or isinstance(usage.charge_microunits, bool)
                    or usage.charge_microunits < 0
                )
            )
        ):
            raise ValueError("provider usage values are invalid")
        if usage.billing_state in {"actual", "estimated"} and usage.charge_microunits is None:
            raise ValueError("known provider usage requires an explicit charge")
        if usage.billing_state == "unknown" and usage.charge_microunits is not None:
            raise ValueError("unknown provider usage cannot assert a charge")
        if usage.billing_state == "local_non_billable" and usage.charge_microunits != 0:
            raise ValueError("local non-billable usage must have zero charge")
        return usage.input_tokens, usage.output_tokens, usage.charge_microunits

    def reserve(
        self,
        **request: object,
    ) -> dict[str, object]:
        """Reserve under the ledger lock so the read/decision/commit is serial."""
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(self.root / ".budget.lock"):
            return self._reserve_locked(**request)

    def _reserve_locked(
        self,
        *,
        invocation_id: str,
        correlation_id: str,
        budget_id: str,
        actor_id: str,
        provider_id: str,
        adapter_id: str,
        billing_state: str,
        max_input_tokens: int,
        max_output_tokens: int,
        fallback_from: str | None = None,
    ) -> dict[str, object]:
        """Reserve deterministic capacity before any provider side effect."""
        for identifier in (invocation_id, budget_id):
            if not _IDENTIFIER.fullmatch(identifier):
                raise ValueError("provider budget identities must be bounded")
        if (
            not correlation_id
            or len(correlation_id.encode("utf-8")) > 256
            or not actor_id
            or len(actor_id.encode("utf-8")) > 256
            or not provider_id
            or len(provider_id.encode("utf-8")) > 256
            or not _IDENTIFIER.fullmatch(adapter_id)
            or (fallback_from is not None and not _IDENTIFIER.fullmatch(fallback_from))
        ):
            raise ValueError("provider reservation metadata identity is invalid")
        if (
            not isinstance(max_input_tokens, int)
            or isinstance(max_input_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or isinstance(max_output_tokens, bool)
            or max_input_tokens < 0
            or max_output_tokens < 0
        ):
            raise ValueError("provider token reservations must be non-negative integers")
        policy = self._policy(budget_id, actor_id, provider_id)
        if billing_state == "unknown" and policy["unknown_billing"] == "deny":
            raise PermissionError("unknown provider billing is denied by policy")
        if billing_state == "local_non_billable":
            reserved_charge = 0
        elif billing_state == "unknown":
            reserved_charge = int(policy["unknown_charge_microunits"])
        else:
            reserved_charge = int(policy["max_charge_per_request_microunits"])
        identity = {
            "invocation_id": invocation_id,
            "correlation_id": correlation_id,
            "budget_id": budget_id,
            "actor_id": actor_id,
            "provider_id": provider_id,
            "currency": policy["currency"],
            "adapter_id": adapter_id,
            "billing_state": billing_state,
            "max_input_tokens": max_input_tokens,
            "max_output_tokens": max_output_tokens,
            "reserved_charge_microunits": reserved_charge,
            "fallback_from": fallback_from,
        }
        identity_sha256 = _sha(identity)
        state = self._state()
        invocations = dict(state["invocations"])
        if invocation_id in invocations:
            existing = invocations[invocation_id]
            if not isinstance(existing, dict) or existing.get("identity_sha256") != identity_sha256:
                raise BudgetIntegrityError("duplicate provider invocation identity differs")
            raise DuplicateInvocationError("provider invocation was already reserved")
        budget_key = f"{budget_id}\u241f{actor_id}\u241f{provider_id}"
        budgets = dict(state["budgets"])
        counters = dict(
            budgets.get(
                budget_key,
                {
                    "settled_charge_microunits": 0,
                    "reserved_charge_microunits": 0,
                    "settled_input_tokens": 0,
                    "reserved_input_tokens": 0,
                    "settled_output_tokens": 0,
                    "reserved_output_tokens": 0,
                    "request_count": 0,
                },
            )
        )
        projected_charge = (
            int(counters["settled_charge_microunits"])
            + int(counters["reserved_charge_microunits"])
            + reserved_charge
        )
        projected_input = (
            int(counters["settled_input_tokens"])
            + int(counters["reserved_input_tokens"])
            + max_input_tokens
        )
        projected_output = (
            int(counters["settled_output_tokens"])
            + int(counters["reserved_output_tokens"])
            + max_output_tokens
        )
        if (
            projected_charge > int(policy["hard_limit_microunits"])
            or projected_input > int(policy["max_input_tokens"])
            or projected_output > int(policy["max_output_tokens"])
            or int(counters["request_count"]) + 1 > int(policy["max_requests"])
        ):
            raise BudgetExhaustedError("provider budget hard limit is exhausted")
        counters["reserved_charge_microunits"] = (
            int(counters["reserved_charge_microunits"]) + reserved_charge
        )
        counters["reserved_input_tokens"] = (
            int(counters["reserved_input_tokens"]) + max_input_tokens
        )
        counters["reserved_output_tokens"] = (
            int(counters["reserved_output_tokens"]) + max_output_tokens
        )
        counters["request_count"] = int(counters["request_count"]) + 1
        budgets[budget_key] = counters
        warning = projected_charge >= int(policy["warning_threshold_microunits"])
        record = {
            **identity,
            "identity_sha256": identity_sha256,
            "state": "reserved",
            "warning_threshold_reached": warning,
            "settlement": None,
        }
        invocations[invocation_id] = record
        updated = _sealed(
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "revision": int(state["revision"]) + 1,
                "budgets": budgets,
                "invocations": invocations,
            },
            "state_sha256",
        )
        receipt = _sealed(
            {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "phase": "reserved",
                "invocation_id": invocation_id,
                "correlation_id": correlation_id,
                "budget_id": budget_id,
                "actor_id": actor_id,
                "provider_id": provider_id,
                "currency": policy["currency"],
                "adapter_id": adapter_id,
                "identity_sha256": identity_sha256,
                "reserved_charge_microunits": reserved_charge,
                "reserved_input_tokens": max_input_tokens,
                "reserved_output_tokens": max_output_tokens,
                "warning_threshold_reached": warning,
                "payload_retained": False,
            },
            "receipt_sha256",
        )
        receipt_path = self.root / "receipts" / f"{invocation_id}.reserved.json"
        result = self.wal.commit(
            (
                JsonArtifact("state", self.state_path, updated),
                JsonArtifact("receipt", receipt_path, receipt),
            ),
            transaction_id=f"provider-reserve-{invocation_id}",
        )
        return {**receipt, "wal_transaction_id": result["transaction_id"]}

    def settle(
        self,
        invocation_id: str,
        *,
        outcome: str,
        usage: ProviderUsage | None,
    ) -> dict[str, object]:
        """Settle under the same lock as reservations and other settlements."""
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(self.root / ".budget.lock"):
            return self._settle_locked(invocation_id, outcome=outcome, usage=usage)

    def _settle_locked(
        self,
        invocation_id: str,
        *,
        outcome: str,
        usage: ProviderUsage | None,
    ) -> dict[str, object]:
        """Settle once; failures and unknown billing burn the full reservation."""
        if outcome not in {"success", "failure"}:
            raise ValueError("provider settlement outcome is invalid")
        state = self._state()
        invocations = dict(state["invocations"])
        raw = invocations.get(invocation_id)
        if not isinstance(raw, dict):
            raise BudgetIntegrityError("provider reservation does not exist")
        record = dict(raw)
        if record.get("state") != "reserved":
            raise DuplicateInvocationError("provider invocation is already settled")
        retained_receipt = self._receipt(invocation_id, "reserved")
        if (
            retained_receipt.get("phase") != "reserved"
            or retained_receipt.get("identity_sha256")
            != record.get("identity_sha256")
        ):
            raise BudgetIntegrityError("provider reservation receipt differs from state")
        reserved_charge = int(record["reserved_charge_microunits"])
        reserved_input = int(record["max_input_tokens"])
        reserved_output = int(record["max_output_tokens"])
        basis = "reservation_burn"
        policy_overrun = False
        if outcome == "success":
            if usage is None:
                raise ValueError("successful provider settlement requires usage")
            input_tokens, output_tokens, charge = self._usage_values(usage)
            if usage.billing_state != record["billing_state"]:
                raise BudgetIntegrityError(
                    "provider usage billing state differs from its reservation"
                )
            policy_overrun = (
                input_tokens > reserved_input or output_tokens > reserved_output
            )
            if usage.billing_state == "local_non_billable":
                settled_charge = 0
                basis = "local_non_billable"
            elif usage.billing_state in {"actual", "estimated"}:
                assert charge is not None
                settled_charge = charge
                basis = usage.billing_state
                policy_overrun = policy_overrun or charge > reserved_charge
            else:
                settled_charge = reserved_charge
                basis = "unknown_conservative_burn"
            settled_input = input_tokens
            settled_output = output_tokens
            if policy_overrun:
                basis = f"{basis}_overrun"
        else:
            settled_charge = reserved_charge
            settled_input = reserved_input
            settled_output = reserved_output
        budget_key = (
            f"{record['budget_id']}\u241f{record['actor_id']}\u241f{record['provider_id']}"
        )
        budgets = dict(state["budgets"])
        counters = dict(budgets[budget_key])
        counters["reserved_charge_microunits"] = (
            int(counters["reserved_charge_microunits"]) - reserved_charge
        )
        counters["reserved_input_tokens"] = (
            int(counters["reserved_input_tokens"]) - reserved_input
        )
        counters["reserved_output_tokens"] = (
            int(counters["reserved_output_tokens"]) - reserved_output
        )
        counters["settled_charge_microunits"] = (
            int(counters["settled_charge_microunits"]) + settled_charge
        )
        counters["settled_input_tokens"] = (
            int(counters["settled_input_tokens"]) + settled_input
        )
        counters["settled_output_tokens"] = (
            int(counters["settled_output_tokens"]) + settled_output
        )
        budgets[budget_key] = counters
        settlement = {
            "outcome": outcome,
            "basis": basis,
            "charge_microunits": settled_charge,
            "input_tokens": settled_input,
            "output_tokens": settled_output,
            "provider_request_id_sha256": hashlib.sha256(
                usage.provider_request_id.encode("utf-8")
            ).hexdigest()
            if usage is not None and usage.provider_request_id
            else None,
            "policy_overrun": policy_overrun,
        }
        record["state"] = "settled"
        record["settlement"] = settlement
        invocations[invocation_id] = record
        updated = _sealed(
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "revision": int(state["revision"]) + 1,
                "budgets": budgets,
                "invocations": invocations,
            },
            "state_sha256",
        )
        receipt = _sealed(
            {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "phase": "settled",
                "invocation_id": invocation_id,
                "correlation_id": record["correlation_id"],
                "budget_id": record["budget_id"],
                "actor_id": record["actor_id"],
                "provider_id": record["provider_id"],
                "currency": record["currency"],
                "adapter_id": record["adapter_id"],
                "identity_sha256": record["identity_sha256"],
                "outcome": outcome,
                "settlement_basis": basis,
                "charge_microunits": settled_charge,
                "input_tokens": settled_input,
                "output_tokens": settled_output,
                "warning_threshold_reached": record["warning_threshold_reached"],
                "provider_request_id_sha256": settlement[
                    "provider_request_id_sha256"
                ],
                "policy_overrun": policy_overrun,
                "payload_retained": False,
            },
            "receipt_sha256",
        )
        receipt_path = self.root / "receipts" / f"{invocation_id}.settled.json"
        result = self.wal.commit(
            (
                JsonArtifact("state", self.state_path, updated),
                JsonArtifact("receipt", receipt_path, receipt),
            ),
            transaction_id=f"provider-settle-{invocation_id}",
        )
        return {**receipt, "wal_transaction_id": result["transaction_id"]}

    def assert_fallback_allowed(
        self,
        *,
        budget_id: str,
        actor_id: str,
        provider_id: str,
        fallback_adapter_id: str,
    ) -> None:
        policy = self._policy(budget_id, actor_id, provider_id)
        if fallback_adapter_id not in policy["fallback_adapter_ids"]:
            raise PermissionError("provider fallback is denied by budget policy")

    def snapshot(self) -> dict[str, object]:
        """Return verified metadata-only ledger state for operators and tests."""
        return self._state()
