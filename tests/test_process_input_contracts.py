"""Future finite process budget and exact UTF-8 replacement contracts."""

from dataclasses import asdict
import random

import pytest

import runtime.process_supervisor as processes


def _budget(**changes):
    value = {
        "startup_timeout_seconds": 2.0,
        "idle_timeout_seconds": 1.0,
        "total_timeout_seconds": 3.0,
        "graceful_shutdown_seconds": 0.2,
        "force_shutdown_seconds": 2.0,
        "stdout_limit_bytes": 128,
        "stderr_limit_bytes": 128,
    }
    value.update(changes)
    return value


TIME_FIELDS = [
    "startup_timeout_seconds",
    "idle_timeout_seconds",
    "total_timeout_seconds",
    "graceful_shutdown_seconds",
    "force_shutdown_seconds",
    "poll_interval_seconds",
]
BYTE_FIELDS = [
    "stdout_limit_bytes",
    "stderr_limit_bytes",
    "disk_consumption_limit_bytes",
]


@pytest.mark.parametrize("field", TIME_FIELDS)
@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), True, "1", 0, -1]
)
def test_mapping_time_budgets_require_positive_actual_finite_numbers(field, value):
    with pytest.raises(ValueError):
        processes.ProcessBudgets.from_mapping(_budget(**{field: value}))


@pytest.mark.parametrize("field", BYTE_FIELDS)
@pytest.mark.parametrize("value", [True, 1.5, "128", 0, -1])
def test_mapping_byte_budgets_require_actual_bounded_integers(field, value):
    with pytest.raises(ValueError):
        processes.ProcessBudgets.from_mapping(_budget(**{field: value}))


@pytest.mark.parametrize("field", TIME_FIELDS)
def test_direct_budget_construction_enforces_the_same_finite_contract(field):
    with pytest.raises(ValueError):
        processes.ProcessBudgets(**_budget(**{field: float("nan")}))


@pytest.mark.parametrize("field", BYTE_FIELDS)
def test_direct_budget_construction_rejects_boolean_byte_limits(field):
    with pytest.raises(ValueError):
        processes.ProcessBudgets(**_budget(**{field: True}))


@pytest.mark.parametrize("value", [[], [("stdout_limit_bytes", 128)], True, "budget"])
def test_budget_mapping_shape_is_checked_before_materialization(value):
    with pytest.raises(ValueError):
        processes.ProcessBudgets.from_mapping(value)


def test_unknown_budget_fields_are_not_silently_discarded():
    with pytest.raises(ValueError):
        processes.ProcessBudgets.from_mapping(_budget(unbounded_future_limit=1))


def test_optional_budget_defaults_and_round_trip_are_compatible():
    result = processes.ProcessBudgets.from_mapping(_budget())
    assert (
        result.disk_consumption_limit_bytes
        == processes.DEFAULT_DISK_CONSUMPTION_LIMIT_BYTES
    )
    assert result.poll_interval_seconds == 0.02
    assert processes.ProcessBudgets.from_mapping(asdict(result)) == result


@pytest.mark.parametrize("location", ["budget", "limits"])
def test_process_budget_validation_precedes_generic_assurance(
    tmp_path, monkeypatch, location
):
    def forbidden(_action):
        raise AssertionError(
            "generic assurance must not coerce invalid process budgets"
        )

    monkeypatch.setattr(processes, "supervise_action", forbidden)
    action = {
        "action_id": "synthetic-preflight",
        "budget": _budget(),
        "limits": _budget(),
    }
    action[location]["startup_timeout_seconds"] = float("nan")
    with pytest.raises(ValueError):
        processes.ProcessSupervisor(object())._authorize(action, tmp_path)


def _reference_decode(raw):
    # Prior owner algorithm retained as an independent exact behavior oracle.
    parts = []
    remaining = raw
    errors = 0
    while remaining:
        try:
            parts.append(remaining.decode("utf-8", errors="strict"))
            break
        except UnicodeDecodeError as error:
            parts.append(remaining[: error.start].decode("utf-8", errors="strict"))
            parts.append("\ufffd")
            errors += 1
            remaining = remaining[error.end :]
    return "".join(parts), errors


def test_decoder_matches_every_one_and_two_byte_sequence():
    for first in range(256):
        value = bytes([first])
        assert processes._decode_utf8_lossy(value) == _reference_decode(value)
        for second in range(256):
            value = bytes([first, second])
            assert processes._decode_utf8_lossy(value) == _reference_decode(value)


def test_decoder_preserves_valid_replacements_adjacent_to_malformed_utf8():
    marker = b"\xef\xbf\xbd"
    cases = [
        b"",
        marker,
        marker * 3,
        b"\xed\xa0\x80",
        b"\xf0\x90\x80",
        b"\xe0\x80",
        b"\xff\xfe",
        "\U0001f680".encode(),
    ]
    for value in cases:
        for payload in [marker + value, value + marker, value + marker + value]:
            assert processes._decode_utf8_lossy(payload) == _reference_decode(payload)
    random_source = random.Random(32)
    for _ in range(256):
        value = random_source.randbytes(64) + marker + random_source.randbytes(64)
        assert processes._decode_utf8_lossy(value) == _reference_decode(value)


def test_bounded_capture_retains_exact_counters_for_malformed_flood():
    capture = processes._BoundedCapture(8192, lambda: None)
    capture.feed(b"\xff" * 16384)
    result = capture.result()
    assert result.text == "\ufffd" * 8192
    assert (
        result.decode_error_count
        == result.retained_bytes
        == result.dropped_bytes
        == 8192
    )
    assert result.total_bytes == 16384 and result.truncated
