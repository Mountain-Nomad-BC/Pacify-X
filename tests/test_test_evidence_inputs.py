"""Receipt diagnostic privacy and bounds; synthetic values and owned receipts."""

import hashlib
import json

import pytest

import runtime.test_profiles as profiles


def _execution(stdout="", stderr="", **extra):
    return {
        "valid": False,
        "exit_code": 1,
        "timed_out": False,
        "duration_seconds": 0.1,
        "stdout": stdout,
        "stderr": stderr,
        **extra,
    }


def _receipt(execution, group=False):
    if group:
        return profiles.group_receipt(
            {"group": "synthetic", "input_sha256": "a" * 64, "member_count": 1},
            execution,
        )
    return profiles.section_chunk_receipt(
        {"section": "synthetic"},
        {
            "chunk_id": "chunk-01",
            "input_sha256": "a" * 64,
            "member_count": 1,
            "members": ["tests/test_fixture.py"],
        },
        execution,
    )


@pytest.mark.parametrize("group", [False, True], ids=["section", "group"])
@pytest.mark.parametrize(
    "payload",
    [
        "synthetic-password-value",
        "token=synthetic-token-value",
        "sk-synthetic01234567890123456789",
        "user@example.invalid",
        "C:\\Users\\Fixture\\private.txt",
        "/home/fixture/private.txt",
        "nested[value] - synthetic assertion",
    ],
    ids=["plain", "named", "token", "email", "windows", "posix", "nested"],
)
def test_parameters_are_removed_before_receipt_retention(tmp_path, group, payload):
    raw = (
        "FAILED tests/test_fixture.py::FixtureTests::test_case["
        + payload
        + "] - synthetic error\n"
    )
    receipt = _receipt(_execution(raw), group)
    assert receipt["output_evidence"]["failure_nodes"] == [
        "tests/test_fixture.py::FixtureTests::test_case[parameters-redacted]"
    ]
    writer = (
        profiles.write_group_receipt if group else profiles.write_section_chunk_receipt
    )
    path = writer(tmp_path, receipt)
    assert payload not in path.read_text(encoding="utf-8")
    assert receipt["passed"] is False
    assert (
        receipt["output_evidence"]["stdout_sha256"]
        == hashlib.sha256(raw.encode()).hexdigest()
    )
    assert profiles._valid_bounded_output_evidence(receipt["output_evidence"])


@pytest.mark.parametrize(
    "prefix,expected",
    [
        ("\u2716 ", "node:details-redacted"),
        ("not ok 7 - ", "tap:details-redacted"),
        ("FAILED ", "pytest:details-redacted"),
    ],
)
def test_free_form_titles_never_reach_retained_attribution(prefix, expected):
    payload = "password=synthetic-password-value user@example.invalid (1.2ms)"
    result = _receipt(_execution(prefix + payload + "\n"))
    assert result["output_evidence"]["failure_nodes"] == [expected]
    assert payload not in json.dumps(result)


def test_redaction_precedes_deduplication():
    text = "\n".join(
        "FAILED tests/test_fixture.py::test_case[synthetic-" + str(i) + "]"
        for i in range(200)
    )
    result = profiles._bounded_output_evidence(_execution(text))
    assert result["failure_nodes"] == [
        "tests/test_fixture.py::test_case[parameters-redacted]"
    ]


@pytest.mark.parametrize("value", [True, 0, [], {}, b"output"])
def test_output_types_are_not_coerced(value):
    with pytest.raises(ValueError):
        _receipt(_execution(stdout=value))


def test_oversized_stream_refuses_before_utf8_encoding(monkeypatch):
    monkeypatch.setattr(profiles, "_PUBLIC_OUTPUT_CHAR_LIMIT", 8, raising=False)
    with pytest.raises(ValueError):
        _receipt(_execution("x" * 9))


@pytest.mark.parametrize("value", [True, 1.0, "1", 2**32, -(2**31) - 1])
def test_exit_status_requires_actual_bounded_integer(value):
    with pytest.raises(ValueError):
        _receipt(_execution(exit_code=value))


def test_unknown_supervision_status_is_not_retained():
    result = _receipt(
        _execution(supervision_status="password=synthetic-password-value")
    )
    assert result["output_evidence"]["failure_nodes"] == ["unattributed-process-exit:1"]
    assert "synthetic-password-value" not in json.dumps(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("stdout_bytes", True),
        ("stdout_bytes", 2**40),
        ("failure_nodes", ["raw secret"]),
        ("failure_nodes", ["tests/test_fixture.py::test_case[synthetic-secret]"]),
    ],
)
def test_receipt_reader_rejects_unsafe_existing_attribution(tmp_path, field, value):
    receipt = _receipt(_execution())
    path = profiles.write_section_chunk_receipt(tmp_path, receipt)
    predecessor = path.read_bytes()
    receipt["output_evidence"][field] = value
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError):
        profiles.write_section_chunk_receipt(tmp_path, receipt)
    assert path.read_bytes() == predecessor
    # Deliberately corrupt an owned fixture image to exercise the reader too.
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert profiles.read_section_chunk_receipt(tmp_path, "synthetic", "chunk-01") == {}


def test_retained_name_count_is_bounded_before_materializing_all_names(monkeypatch):
    monkeypatch.setattr(profiles, "_PUBLIC_FAILURE_LIMIT", 4, raising=False)
    raw = "\n".join(
        "FAILED tests/test_fixture.py::test_case_" + str(i) for i in range(20)
    )
    result = profiles._bounded_output_evidence(_execution(raw))
    assert len(result["failure_nodes"]) == 4
    assert result["failure_nodes"][-1] == "diagnostics:attribution-truncated"
    assert profiles._valid_bounded_output_evidence(result)


def test_line_budget_reports_incomplete_attribution_and_keeps_exact_digest(monkeypatch):
    monkeypatch.setattr(profiles, "_PUBLIC_OUTPUT_LINE_LIMIT", 3, raising=False)
    raw = "ordinary\n" * 4 + "FAILED tests/test_fixture.py::test_case\n"
    result = profiles._bounded_output_evidence(_execution(raw))
    assert result["failure_nodes"] == ["diagnostics:attribution-truncated"]
    assert result["stdout_sha256"] == hashlib.sha256(raw.encode()).hexdigest()


def test_long_line_never_retains_a_sensitive_prefix(monkeypatch):
    monkeypatch.setattr(profiles, "_PUBLIC_OUTPUT_LINE_CHARS", 16, raising=False)
    result = profiles._bounded_output_evidence(
        _execution("FAILED synthetic-password-value")
    )
    assert result["failure_nodes"] == ["diagnostics:attribution-truncated"]


def test_multibyte_chunk_boundary_preserves_exact_text_digest():
    raw = (
        "\u00e9" * 65535 + "\U0001f680" + "\nFAILED tests/test_fixture.py::test_case\n"
    )
    result = profiles._bounded_output_evidence(_execution(raw))
    assert result["stdout_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert result["stdout_bytes"] == len(raw.encode())


def test_structural_test_location_and_exit_failure_are_preserved(tmp_path):
    receipt = _receipt(
        _execution(
            "FAILED tests/test_fixture.py::FixtureTests::test_case - assertion\n"
        )
    )
    assert receipt["output_evidence"]["failure_nodes"] == [
        "tests/test_fixture.py::FixtureTests::test_case"
    ]
    path = profiles.write_section_chunk_receipt(tmp_path, receipt)
    assert path.is_file()
    assert (
        profiles.read_section_chunk_receipt(tmp_path, "synthetic", "chunk-01")
        == receipt
    )
    assert receipt["passed"] is False


def test_no_output_success_remains_no_output_success():
    result = profiles._bounded_output_evidence(_execution(exit_code=0, valid=True))
    assert result["failure_nodes"] == []
    assert profiles._valid_bounded_output_evidence(result)


@pytest.mark.parametrize(
    "status,code", [("spawn_failed", None), ("cancelled", 0), ("owner_lost", None)]
)
def test_known_supervision_failure_is_attributed_even_without_nonzero_exit(
    status, code
):
    result = profiles._bounded_output_evidence(
        _execution(exit_code=code, supervision_status=status)
    )
    assert result["failure_nodes"] == ["supervision:" + status]
    assert profiles._valid_bounded_output_evidence(result)
