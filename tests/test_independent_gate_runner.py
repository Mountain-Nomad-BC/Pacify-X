from __future__ import annotations

import json
from pathlib import Path

from runtime.gate_runner import GateSpec, finalize_gates, run_gates
import runtime.gate_runner as gates


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
