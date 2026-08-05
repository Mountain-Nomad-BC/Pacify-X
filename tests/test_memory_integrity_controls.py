from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from runtime.memory_fabric import MemoryRecord, correction_plan
from runtime.memory_vault import MemoryVault


def _record(memory_id: str = "mem-one") -> MemoryRecord:
    now = datetime.now(timezone.utc)
    return MemoryRecord(
        memory_id,
        "wsp",
        "prj",
        "agent",
        "session",
        "lease",
        "Memory title",
        "decision",
        "Evidence backed memory summary",
        "source.md",
        "a" * 64,
        "E-1",
        "observation",
        0.9,
        "direct",
        "internal",
        ("prj",),
        now,
        now,
    )


def _canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _vault(root: Path) -> MemoryVault:
    vault = MemoryVault(root, workspace_id="wsp", project_id="prj")
    vault.append(_record())
    return vault


def test_rewritten_memory_and_lifecycle_event_are_detected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        vault = _vault(root)
        record_path = next(root.rglob("record-*.json"))
        event_path = next((root / ".memory-control/lifecycle/mem-one").glob("*.json"))
        event = json.loads(event_path.read_text())
        event["evidence"] = ["forged"]
        event["event_sha256"] = _canonical(
            {key: value for key, value in event.items() if key != "event_sha256"}
        )
        event_path.write_text(json.dumps(event), encoding="utf-8")
        stored = json.loads(record_path.read_text())
        stored["summary"] = "forged"
        stored["lifecycle_event_head_sha256"] = event["event_sha256"]
        stored["record_sha256"] = _canonical(
            {key: value for key, value in stored.items() if key != "record_sha256"}
        )
        record_path.write_text(json.dumps(stored), encoding="utf-8")
        with pytest.raises(ValueError, match="protected head mismatch"):
            vault.records()


def test_invalid_lifecycle_state_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        vault = _vault(root)
        event = next((root / ".memory-control/lifecycle/mem-one").glob("*.json"))
        payload = json.loads(event.read_text())
        payload["state"] = "invented"
        event.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid lifecycle state"):
            vault.lifecycle_state("mem-one")


def test_truncated_lifecycle_event_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        vault = _vault(root)
        event = next((root / ".memory-control/lifecycle/mem-one").glob("*.json"))
        event.write_text("{", encoding="utf-8")
        with pytest.raises(ValueError, match="integrity failure"):
            vault.lifecycle_state("mem-one")


def test_memory_transition_must_be_allowed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        vault = _vault(Path(directory))
        with pytest.raises(ValueError, match="invalid memory lifecycle transition"):
            vault.transition("mem-one", "trusted", evidence=("approval",))


def test_correction_of_revoked_memory_is_rejected() -> None:
    prior = replace(_record(), certification_status="revoked")
    correction = replace(_record("mem-two"), supersedes=(prior.memory_id,))
    decision = correction_plan(prior, correction)
    assert (
        decision.decision == "deny" and "correction_target_revoked" in decision.reasons
    )


def test_reinstatement_requires_distinct_approved_event() -> None:
    with tempfile.TemporaryDirectory() as directory:
        vault = _vault(Path(directory))
        vault.transition("mem-one", "revoked", evidence=("revocation",))
        with pytest.raises(ValueError, match="approval evidence"):
            vault.reinstate("mem-one", approval_evidence=())
        decision = vault.reinstate("mem-one", approval_evidence=("review-approval",))
        assert decision.previous == "revoked" and decision.current == "candidate"
        assert len(vault._validate_lifecycle("mem-one")) == 3
