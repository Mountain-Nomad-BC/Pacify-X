"""Tests for PX-GAP-0013: evidence-hash custody revalidation.

Written to define the requirement. NOT executed in the implementation-first pass.
"""

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.operational_gap_ledger import (
    REVALIDATION_MATCHING,
    REVALIDATION_MISSING,
    REVALIDATION_STALE,
    revalidate_evidence,
)


def _ledger_with_evidence(root: Path, reference: str, recorded: str) -> Path:
    """Write a minimal ledger whose one card carries an evidence reference.

    Written through the canonical writer (``append_event``) so the compact head
    that the reader requires is produced the same way production produces it,
    rather than hand-writing only the jsonl tail.
    """
    from runtime.operational_gap_ledger import append_event, CHAIN_STAGES

    root.mkdir(parents=True, exist_ok=True)
    append_event(root, "ledger_initialized", {"ledger_id": "revalidation-fixture", "scope": [], "authority": "test fixture"}, actor="test")
    chain = {stage: {"state": "not_applicable", "detail": "fixture stage", "evidence": []} for stage in CHAIN_STAGES}
    append_event(
        root,
        "card_discovered",
        {
            "gap_id": "PX-OS-901",
            "parent_surface": "runtime/operational_gap_ledger.py",
            "feature": "evidence revalidation fixture",
            "control_action": "exercise evidence-hash revalidation",
            "discovery_source": "tests/test_evidence_revalidation.py",
            "discovered_at": "AUTO",
            "discovered_by": "AUTO",
            "source_refs": [{"path": "tests/test_evidence_revalidation.py", "symbols": ["PX-OS-901"]}],
            "expected_behavior": "evidence references are classified against current bytes",
            "observed_behavior": "fixture evidence reference recorded",
            "interaction_chain": chain,
            "classification": "runtime",
            "severity": "low",
            "operational_impact": "fixture only",
            "dependencies": [],
            "blockers": [],
            "assigned_owner": "unassigned",
            "tests_required": ["evidence revalidation classifies matching/stale/missing"],
            "completion_evidence": [],
            "reopen_reason": None,
            "defer_skip": None,
            "next_action": "exercise the canonical revalidation pass",
            "discovery_evidence": [
                {"reference": reference, "claim": "fixture evidence", "artifact_sha256": recorded}
            ],
        },
        actor="test",
    )
    return root / "registry"


class EvidenceRevalidationTest(unittest.TestCase):
    def test_matching_evidence_is_reported_matching(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifact = root / "evidence" / "x.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"payload")
            digest = hashlib.sha256(b"payload").hexdigest()
            _ledger_with_evidence(root, "evidence/x.json", digest)
            report = revalidate_evidence(root)
            self.assertEqual(report["schema_version"], "px.evidence-revalidation/1.0")
            self.assertEqual(report["evidence_reference_count"], 1)
            self.assertEqual(report["stale_count"], 0)
            self.assertEqual(report["rows"][0]["disposition"], REVALIDATION_MATCHING)

    def test_stale_hash_is_detected(self):
        # A recorded digest that does not match the current bytes is STALE.
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifact = root / "evidence" / "x.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"now")
            recorded = hashlib.sha256(b"before").hexdigest()
            _ledger_with_evidence(root, "evidence/x.json", recorded)
            report = revalidate_evidence(root)
            self.assertEqual(report["stale_count"], 1)
            self.assertEqual(report["rows"][0]["disposition"], REVALIDATION_STALE)
            self.assertEqual(report["stale_cards"], ["PX-OS-901"])
            self.assertEqual(REVALIDATION_STALE, "stale")
            self.assertEqual(REVALIDATION_MATCHING, "matching")
            self.assertEqual(REVALIDATION_MISSING, "missing")

    def test_missing_artifact_is_reported_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _ledger_with_evidence(root, "evidence/gone.json", "a" * 64)
            report = revalidate_evidence(root)
            self.assertEqual(report["missing_count"], 1)
            self.assertEqual(report["rows"][0]["disposition"], REVALIDATION_MISSING)

    def test_revalidation_is_read_only(self):
        # The pass must not write to the ledger.
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "evidence").mkdir(parents=True, exist_ok=True)
            (root / "evidence" / "x.json").write_bytes(b"payload")
            registry = _ledger_with_evidence(root, "evidence/x.json", hashlib.sha256(b"payload").hexdigest())
            ledger = registry / "operational_gap_ledger.jsonl"
            before = ledger.read_bytes()
            revalidate_evidence(root)
            self.assertEqual(ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()