from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from runtime.gate_runner import GateSpec, finalize_gates, run_gates
import runtime.gate_runner as gates


@pytest.fixture(autouse=True)
def isolated_authority_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PACIFY_X_GATE_AUTHORITY_ROOT", str(tmp_path / "authority-store"))


def test_passing_gate_receipt_is_reused_until_its_inputs_change(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "product"
    root.mkdir()
    (root / "a.txt").write_text("one", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        gates,
        "GATES",
        {
            "a": GateSpec(
                "a", ("a.txt",), (), lambda _: calls.append("a") or {"valid": True}
            )
        },
    )
    receipts = tmp_path / "receipts"
    first = run_gates(root, receipts)
    second = run_gates(root, receipts)
    assert first["valid"] and second["valid"] and calls == ["a"]
    assert second["results"][0]["state"] == "reused_current_pass"
    (root / "a.txt").write_text("two", encoding="utf-8")
    third = run_gates(root, receipts)
    assert third["results"][0]["state"] == "executed" and calls == ["a", "a"]


def test_gate_input_digest_excludes_derived_custody_but_tracks_source_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "product"
    source = root / ".engineering-bootstrap/project-management/state.json"
    derived = root / ".engineering-bootstrap/operation-bus/event.json"
    source.parent.mkdir(parents=True)
    derived.parent.mkdir(parents=True)
    source.write_text('{"state":"one"}', encoding="utf-8")
    derived.write_text('{"event":"one"}', encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        gates,
        "GATES",
        {
            "structural": GateSpec(
                "structural",
                (".engineering-bootstrap/**/*.json",),
                (),
                lambda _: calls.append("structural") or {"valid": True},
            )
        },
    )
    receipts = tmp_path / "receipts"

    assert run_gates(root, receipts)["results"][0]["state"] == "executed"
    derived.write_text('{"event":"two"}', encoding="utf-8")
    assert run_gates(root, receipts)["results"][0]["state"] == "reused_current_pass"
    source.write_text('{"state":"two"}', encoding="utf-8")
    assert run_gates(root, receipts)["results"][0]["state"] == "executed"
    assert calls == ["structural", "structural"]


def test_failed_gate_reruns_without_reexecuting_unrelated_current_gate(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "product"
    root.mkdir()
    (root / "a").write_text("a")
    (root / "b").write_text("b")
    calls = []
    state = {"b": False}
    monkeypatch.setattr(
        gates,
        "GATES",
        {
            "a": GateSpec(
                "a", ("a",), (), lambda _: calls.append("a") or {"valid": True}
            ),
            "b": GateSpec(
                "b", ("b",), (), lambda _: calls.append("b") or {"valid": state["b"]}
            ),
        },
    )
    receipts = tmp_path / "receipts"
    assert not run_gates(root, receipts)["valid"]
    state["b"] = True
    result = run_gates(root, receipts)
    assert result["valid"] and calls == ["a", "b", "b"]


def test_finalizer_rejects_stale_or_tampered_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "product"
    root.mkdir()
    (root / "a").write_text("a")
    monkeypatch.setattr(
        gates, "GATES", {"a": GateSpec("a", ("a",), (), lambda _: {"valid": True})}
    )
    receipts = tmp_path / "receipts"
    run_gates(root, receipts)
    assert finalize_gates(root, receipts)["valid"]
    value = json.loads((receipts / "a.json").read_text())
    value["passed"] = False
    (receipts / "a.json").write_text(json.dumps(value))
    assert not finalize_gates(root, receipts)["valid"]


def test_gate_identity_includes_transitive_local_import(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "product"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime/__init__.py").write_text("", encoding="utf-8")
    (root / "runtime/owner.py").write_text("from . import helper\n", encoding="utf-8")
    helper = root / "runtime/helper.py"
    helper.write_text("VALUE = 1\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(gates, "GATES", {"a": GateSpec("a", ("runtime/owner.py",), (), lambda _: calls.append(1) or {"valid": True})})
    receipts = tmp_path / "receipts"
    assert run_gates(root, receipts)["valid"]
    helper.write_text("VALUE = 2\n", encoding="utf-8")
    assert run_gates(root, receipts)["results"][0]["state"] == "executed"
    assert calls == [1, 1]


def test_self_sealed_receipt_without_authority_hmac_is_not_reused(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "product"
    root.mkdir()
    (root / "a").write_text("a", encoding="utf-8")
    calls = []
    monkeypatch.setattr(gates, "GATES", {"a": GateSpec("a", ("a",), (), lambda _: calls.append(1) or {"valid": True})})
    receipts = tmp_path / "receipts"
    run_gates(root, receipts)
    value = json.loads((receipts / "a.json").read_text(encoding="utf-8"))
    value.pop("authority_hmac_sha256")
    (receipts / "a.json").write_text(json.dumps(gates._seal(value)), encoding="utf-8")
    result = run_gates(root, receipts)
    assert result["results"][0]["state"] == "executed"
    assert calls == [1, 1]


def test_gate_authority_key_publication_is_complete_under_concurrent_creation(tmp_path: Path) -> None:
    root = tmp_path / "product"
    root.mkdir()
    with ThreadPoolExecutor(max_workers=8) as executor:
        keys = tuple(executor.map(lambda _: gates._authority_key(root, create=True), range(32)))
    assert len(set(keys)) == 1
    assert len(keys[0]) == 32
    authority = gates._authority_path(root)
    protected = authority.read_bytes()
    assert protected != keys[0]
    assert gates._authority_key(root, create=False) == keys[0]
    assert list(authority.parent.glob("*.prepared")) == []
