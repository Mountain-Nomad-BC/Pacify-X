from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from runtime import operational_observers as owner
from tests import test_operational_observers as legacy


class Opaque:
    def __bool__(self):
        raise AssertionError("opaque truthiness executed")

    def __str__(self):
        raise AssertionError("opaque string conversion executed")

    def __iter__(self):
        raise AssertionError("opaque iteration executed")

    def __eq__(self, other):
        raise AssertionError("opaque equality executed")


class FakeConsent:
    def validate(self, **kwargs):
        raise AssertionError("untyped consent hook executed")


def plan():
    return owner.build_windows_etw_plan(
        session_name="PacifyX-test", scope_refs=legacy.SCOPES, executable="fake-logman"
    )


@pytest.mark.parametrize(
    "grant",
    ["false", "true", 1, 0, None, [], Opaque()],
    ids=["false-text", "true-text", "one", "zero", "null", "array", "opaque"],
)
def test_consent_requires_actual_boolean(grant):
    with pytest.raises(ValueError):
        legacy._consent(granted=grant).validate()


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("max_events", owner.MAX_CAPTURE_EVENTS),
        ("max_bytes", owner.MAX_CAPTURE_BYTES),
        ("max_duration_seconds", owner.MAX_CAPTURE_SECONDS),
    ],
)
@pytest.mark.parametrize(
    "kind", ["bool", "fraction", "text", "nan", "inf", "null", "zero", "over", "opaque"]
)
def test_consent_budgets_are_exact_before_comparison(field, maximum, kind):
    values = {
        "bool": True,
        "fraction": 1.5,
        "text": "1",
        "nan": float("nan"),
        "inf": float("inf"),
        "null": None,
        "zero": 0,
        "over": maximum + 1,
        "opaque": Opaque(),
    }
    with pytest.raises(ValueError):
        legacy._consent(**{field: values[kind]}).validate()


@pytest.mark.parametrize(
    "field",
    ["consent_id", "observer_id", "project_id", "accountable_owner", "classification"],
)
@pytest.mark.parametrize("kind", ["opaque", "control", "bytes", "multibyte"])
def test_consent_identity_text_has_no_conversion_hooks(field, kind):
    value = {
        "opaque": Opaque(),
        "control": "owner\n",
        "bytes": b"owner",
        "multibyte": "\u754c" * 81,
    }[kind]
    with pytest.raises(ValueError):
        legacy._consent(**{field: value}).validate()


@pytest.mark.parametrize(
    "kind", ["string", "list", "set", "duplicates", "unsupported", "too-many", "opaque"]
)
def test_effects_have_one_bounded_immutable_representation(kind):
    values = {
        "string": "read",
        "list": ["read"],
        "set": {"read"},
        "duplicates": ("read", "read"),
        "unsupported": ("service",),
        "too-many": ("read",) * 5,
        "opaque": Opaque(),
    }
    with pytest.raises(ValueError):
        legacy._consent(allowed_effects=values[kind]).validate()


BAD_SCOPES = [
    "process-id:",
    "process-id:0",
    "process-id:01",
    "process-id:-1",
    "process-id:4294967296",
    "process-id:\u0664\u0662",
    "project:",
    "project:../secret",
    "project:C:/secret",
    "project:two words",
    "path-sha256:" + "a" * 63,
    "executable-sha256:" + "A" * 64,
    "endpoint-sha256:raw-host",
    "unknown:x",
]


@pytest.mark.parametrize(
    "scope",
    BAD_SCOPES,
    ids=[
        "pid-empty",
        "pid-zero",
        "pid-leading-zero",
        "pid-negative",
        "pid-over",
        "pid-unicode",
        "project-empty",
        "project-traversal",
        "project-path",
        "project-space",
        "hash-short",
        "hash-upper",
        "endpoint-raw",
        "unknown",
    ],
)
def test_scope_grammar_is_shared_by_consent_and_both_plan_producers(scope, monkeypatch):
    with pytest.raises(ValueError):
        legacy._consent(scope_refs=(scope,)).validate()

    def forbidden(*args, **kwargs):
        raise AssertionError("discovery or path access happened before scope refusal")

    monkeypatch.setattr(owner.shutil, "which", forbidden)
    with pytest.raises(ValueError):
        owner.build_windows_etw_plan(session_name="PacifyX-test", scope_refs=(scope,))
    with pytest.raises(ValueError):
        owner.build_linux_audit_plan(
            rule_key="pacifyx_test", watched_directory=Opaque(), scope_refs=(scope,)
        )


@pytest.mark.parametrize("kind", ["duplicate", "too-many", "list", "string", "opaque"])
def test_scope_container_and_uniqueness_precede_materialization(kind):
    values = {
        "duplicate": ("project:px", "project:px"),
        "too-many": tuple("project:p" + str(i) for i in range(17)),
        "list": ["project:px"],
        "string": "project:px",
        "opaque": Opaque(),
    }
    with pytest.raises(ValueError):
        legacy._consent(scope_refs=values[kind]).validate()
    with pytest.raises(ValueError):
        owner.build_windows_etw_plan(
            session_name="PacifyX-test",
            scope_refs=values[kind],
            executable="fake-logman",
        )


@pytest.mark.parametrize(
    "scope",
    [
        "process-id:1",
        "process-id:4294967295",
        "project:px",
        "project:P_1.2-3",
        "path-sha256:" + "a" * 64,
        "endpoint-sha256:" + "b" * 64,
        "executable-sha256:" + "c" * 64,
    ],
)
def test_all_supported_scope_kinds_keep_direct_and_record_parity(scope):
    consent = legacy._consent(scope_refs=(scope,))
    consent.validate()
    record = legacy._record("record-1") | {"scope_refs": [scope]}
    before = json.loads(json.dumps(record))
    result = owner._validate_observation(record, consent)
    assert result == record == before
    result["scope_refs"].clear()
    assert record["scope_refs"] == [scope]


@pytest.mark.parametrize(
    "kind",
    [
        "opaque",
        "pairs",
        "extra-field",
        "duplicate-scope",
        "scope-tuple",
        "scope-over",
        "operation-control",
        "identity-multibyte",
        "time-opaque",
    ],
)
def test_observation_shape_and_scope_are_bounded_before_copy(kind):
    record = legacy._record("record-1")
    if kind == "opaque":
        record = Opaque()
    elif kind == "pairs":
        record = list(record.items())
    elif kind == "extra-field":
        record["payload"] = "forbidden"
    elif kind == "duplicate-scope":
        record["scope_refs"] *= 2
    elif kind == "scope-tuple":
        record["scope_refs"] = tuple(record["scope_refs"])
    elif kind == "scope-over":
        record["scope_refs"] *= 9
    elif kind == "operation-control":
        record["operation"] = "start\n"
    elif kind == "identity-multibyte":
        record["observation_id"] = "\u754c" * 81
    elif kind == "time-opaque":
        record["observed_at"] = Opaque()
    with pytest.raises(ValueError):
        owner._validate_observation(record, legacy._consent())


def test_observation_still_refuses_outside_effect_and_scope():
    with pytest.raises(PermissionError):
        owner._validate_observation(
            legacy._record("record-1", effect="network"), legacy._consent()
        )
    with pytest.raises(ValueError):
        owner._validate_observation(
            legacy._record("record-1") | {"scope_refs": ["project:other"]},
            legacy._consent(),
        )


@pytest.mark.parametrize(
    "kind",
    [
        "mapping-opaque",
        "missing",
        "extra",
        "args-list",
        "args-string",
        "args-opaque",
        "too-many",
        "arg-bytes",
        "arg-over",
        "aggregate-over",
    ],
)
def test_plan_inputs_are_bounded_before_hash_or_constructor(kind):
    commands = {name: ("fake",) for name in ("start", "stop", "uninstall")}
    if kind == "mapping-opaque":
        commands = Opaque()
    elif kind == "missing":
        commands.pop("stop")
    elif kind == "extra":
        commands["extra"] = ("fake",)
    elif kind == "args-list":
        commands["start"] = ["fake"]
    elif kind == "args-string":
        commands["start"] = "fake"
    elif kind == "args-opaque":
        commands["start"] = Opaque()
    elif kind == "too-many":
        commands["start"] = ("fake",) * 33
    elif kind == "arg-bytes":
        commands["start"] = (b"fake",)
    elif kind == "arg-over":
        commands["start"] = ("a" * 4097,)
    elif kind == "aggregate-over":
        commands["start"] = ("a" * 4096,) * 5
    with pytest.raises(ValueError):
        owner._plan_digest("windows-etw", legacy.SCOPES, commands)
    with pytest.raises(ValueError):
        owner.ObserverCommandPlan(
            "windows-etw", "win32", legacy.SCOPES, commands, "a" * 64
        )


def test_valid_plan_keeps_canonical_hash_and_exact_fixed_commands():
    result = plan()
    payload = {
        "schema_version": "px.os-observer-command-plan/1.0",
        "observer_id": result.observer_id,
        "scope_refs": list(result.scope_refs),
        "commands": {
            key: list(value) for key, value in sorted(result.commands.items())
        },
    }
    expected = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    assert result.configuration_sha256 == expected
    assert result.commands["start"] == (
        "fake-logman",
        "create",
        "trace",
        "PacifyX-test",
        "-p",
        owner.WINDOWS_KERNEL_PROCESS_PROVIDER,
        "0xffffffffffffffff",
        "5",
        "-ets",
    )
    assert result.commands["stop"] == ("fake-logman", "stop", "PacifyX-test", "-ets")


@pytest.mark.parametrize("field", ["observer_id", "platform", "configuration_sha256"])
def test_plan_scalar_hooks_are_rejected(field):
    kwargs = dict(
        observer_id="windows-etw",
        platform="win32",
        scope_refs=legacy.SCOPES,
        commands={name: ("fake",) for name in ("start", "stop", "uninstall")},
        configuration_sha256="a" * 64,
    )
    kwargs[field] = Opaque()
    with pytest.raises(ValueError):
        owner.ObserverCommandPlan(**kwargs)


@pytest.mark.parametrize("method", ["enable", "capture", "start"])
def test_untyped_consent_cannot_run_custom_validator(method):
    if method == "start":
        obj = owner.ManagedCommandObserverBackend.__new__(
            owner.ManagedCommandObserverBackend
        )
    else:
        obj = owner.OperationalObserverController.__new__(
            owner.OperationalObserverController
        )
    with pytest.raises(ValueError):
        getattr(obj, method)(FakeConsent())


@pytest.mark.parametrize(
    "limit",
    [True, 1.5, "1", None, Opaque()],
    ids=["bool", "fraction", "text", "null", "opaque"],
)
def test_capture_limit_refuses_before_lookup_lock_or_state_access(limit):
    obj = owner.OperationalObserverController.__new__(
        owner.OperationalObserverController
    )
    with pytest.raises(ValueError):
        obj.capture(legacy._consent(), limit=limit)


def test_invalid_grant_refuses_before_backend_lookup_or_state_access():
    obj = owner.OperationalObserverController.__new__(
        owner.OperationalObserverController
    )
    with pytest.raises(ValueError):
        obj.enable(legacy._consent(granted="false"))


@pytest.mark.parametrize(
    "kind", ["fresh-text", "fresh-int", "now-naive", "now-opaque", "expiry-subclass"]
)
def test_time_validation_controls_are_typed(kind):
    consent = legacy._consent()
    options = {}
    if kind == "fresh-text":
        options["require_fresh"] = "false"
    elif kind == "fresh-int":
        options["require_fresh"] = 1
    elif kind == "now-naive":
        options["now"] = datetime(2026, 9, 9)
    elif kind == "now-opaque":
        options["now"] = Opaque()
    else:

        class Text(str):
            pass

        consent = replace(consent, expires_at=Text(consent.expires_at))
    with pytest.raises(ValueError):
        consent.validate(**options)


def test_exact_budget_edges_expiry_and_withheld_consent_are_preserved():
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    for maximum in [False, True]:
        consent = legacy._consent(
            max_events=owner.MAX_CAPTURE_EVENTS if maximum else 1,
            max_bytes=owner.MAX_CAPTURE_BYTES if maximum else 1,
            max_duration_seconds=owner.MAX_CAPTURE_SECONDS if maximum else 1,
            expires_at=(now + timedelta(seconds=1)).isoformat(),
        )
        consent.validate(now=now)
    with pytest.raises(PermissionError):
        replace(consent, granted=False).validate(now=now)
    with pytest.raises(PermissionError):
        replace(consent, expires_at=now.isoformat()).validate(now=now)
    replace(consent, expires_at=now.isoformat()).validate(now=now, require_fresh=False)
