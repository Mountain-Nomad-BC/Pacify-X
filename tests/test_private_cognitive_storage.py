from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

EXTERNAL_ROOT = os.environ.get("PX_PERSISTENT_MEMORY_EXTERNAL_ROOT")
if EXTERNAL_ROOT:
    sys.path.insert(0, EXTERNAL_ROOT)
    importlib.invalidate_caches()
PACKAGE_AVAILABLE = importlib.util.find_spec("pacifyx_memory") is not None
if PACKAGE_AVAILABLE:
    from pacifyx_memory.cognitive_storage import CognitivePaths, PrivateKnowledgeStore, PrivateSkillStore
else:
    CognitivePaths = PrivateKnowledgeStore = PrivateSkillStore = None


@unittest.skipUnless(PACKAGE_AVAILABLE, "external cognitive package source not supplied to test environment")
class PrivateCognitiveStorageTests(unittest.TestCase):
    def test_knowledge_candidate_and_px_promotion_record_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "external"
            store = PrivateKnowledgeStore(root)
            candidate = store.add_candidate(
                knowledge_id="knowledge:px/model-fabric",
                project_id="project:px",
                title="Model fabric fact",
                body="Evidence-backed candidate",
                source_refs=["source:1"],
                evidence_refs=["evidence:1"],
                subjects=["subject:pacify-x/model-fabric"],
                relations=["relation:supported-by"],
                proposal_receipt_sha256="1" * 64,
            )
            again = store.add_candidate(
                knowledge_id="knowledge:px/model-fabric",
                project_id="project:px",
                title="Model fabric fact",
                body="Evidence-backed candidate",
                source_refs=["source:1"],
                evidence_refs=["evidence:1"],
                subjects=["subject:pacify-x/model-fabric"],
                relations=["relation:supported-by"],
                proposal_receipt_sha256="1" * 64,
            )
            self.assertEqual(candidate, again)
            head = store.record_promoted_revision(
                knowledge_id="knowledge:px/model-fabric",
                revision=1,
                canonical_payload={"claim": "x", "source_sha256": "2" * 64},
                candidate_sha256=candidate["candidate_sha256"],
                px_promotion_receipt_sha256="3" * 64,
            )
            self.assertFalse(head["authority_granted"])
            self.assertEqual(head, store.record_promoted_revision(
                knowledge_id="knowledge:px/model-fabric",
                revision=1,
                canonical_payload={"claim": "x", "source_sha256": "2" * 64},
                candidate_sha256=candidate["candidate_sha256"],
                px_promotion_receipt_sha256="3" * 64,
            ))
            rows = [json.loads(line) for line in (CognitivePaths(root).knowledge / "Events" / "events.ndjson").read_text().splitlines()]
            self.assertEqual(["candidate_recorded", "px_promoted_revision_recorded"], [row["event"] for row in rows])
            self.assertEqual(1, len(store.heads()))

    def test_knowledge_promotion_cannot_exist_without_candidate_and_px_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "external"
            store = PrivateKnowledgeStore(root)
            with self.assertRaises(ValueError):
                store.record_promoted_revision(
                    knowledge_id="knowledge:x",
                    revision=1,
                    canonical_payload={},
                    candidate_sha256="a" * 64,
                    px_promotion_receipt_sha256="not-a-sha",
                )
            with self.assertRaisesRegex(RuntimeError, "unknown"):
                store.record_promoted_revision(
                    knowledge_id="knowledge:x",
                    revision=1,
                    canonical_payload={},
                    candidate_sha256="a" * 64,
                    px_promotion_receipt_sha256="b" * 64,
                )

    def test_skill_candidate_never_self_grants_execution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "external"
            source = base / "skill"
            source.mkdir()
            (source / "SKILL.md").write_text("# bounded skill\n", encoding="utf-8")
            (source / "tool.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            store = PrivateSkillStore(root)
            staged = store.stage_candidate(
                skill_id="skill:private/test",
                revision="r1",
                source_dir=source,
                proposal_receipt_sha256="4" * 64,
                evidence_refs=["evidence:skill-test"],
            )
            candidate_root = root / staged["path"]
            manifest = json.loads((candidate_root / "candidate.json").read_text())
            self.assertFalse(manifest["authority_granted"])
            self.assertFalse(manifest["executable_authority"])
            self.assertFalse((CognitivePaths(root).skills / "Admitted").joinpath("skill-private-test", "r1").exists())
            admission = store.record_px_admission(
                skill_id="skill:private/test",
                revision="r1",
                package_sha256=staged["package_sha256"],
                px_admission_receipt_sha256="5" * 64,
            )
            self.assertFalse(admission["authority_granted"])
            self.assertFalse(admission["executable_authority"])
            self.assertTrue(admission["runtime_must_verify_px_registry"])
            self.assertEqual(admission, store.record_px_admission(
                skill_id="skill:private/test",
                revision="r1",
                package_sha256=staged["package_sha256"],
                px_admission_receipt_sha256="5" * 64,
            ))
            catalog = store.catalog()
            self.assertFalse(catalog["authority_granted"])
            self.assertTrue(catalog["runtime_must_verify_px_registry"])

    def test_skill_payload_tamper_is_detected_before_admission(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); root = base / "external"; source = base / "skill"; source.mkdir()
            (source / "SKILL.md").write_text("# v1\n", encoding="utf-8")
            store = PrivateSkillStore(root)
            staged = store.stage_candidate(skill_id="skill:test", revision="1", source_dir=source, proposal_receipt_sha256="6" * 64)
            payload = root / staged["path"] / "payload" / "SKILL.md"
            payload.write_text("# tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "changed"):
                store.record_px_admission(skill_id="skill:test", revision="1", package_sha256=staged["package_sha256"], px_admission_receipt_sha256="7" * 64)


if __name__ == "__main__":
    unittest.main()
