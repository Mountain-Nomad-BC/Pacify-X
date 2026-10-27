from __future__ import annotations

import unittest

from runtime.context_checkpoint import (
    build_checkpoint, persist_and_publish_checkpoint,
)


class PXAUD079_CheckpointCompactionValidReceipts(unittest.TestCase):
    """PX-AUD-079: context checkpoint permits compaction only after valid receipts."""

    def _make_checkpoint(self) -> dict:
        return build_checkpoint(
            project_id="proj", session_id="sess", task_id="task-1",
            model_route="route", reason="test",
        )

    def test_valid_receipts_permit_compaction(self) -> None:
        checkpoint = self._make_checkpoint()
        def persist(cp): return {"valid": True, "status": "persisted", "generation": 1}
        def publish(cp, sr): return {"valid": True, "status": "published", "generation": 2}
        result = persist_and_publish_checkpoint(checkpoint, persist=persist, publish=publish)
        self.assertTrue(result["compaction_permitted"])
        self.assertTrue(result["bulk_hydration_permitted"])

    def test_invalid_storage_receipt_blocks_compaction(self) -> None:
        checkpoint = self._make_checkpoint()
        def persist(cp): return {"valid": False, "status": "failed", "error": "disk full"}
        def publish(cp, sr): return {"valid": True, "status": "published"}
        with self.assertRaises(RuntimeError) as ctx:
            persist_and_publish_checkpoint(checkpoint, persist=persist, publish=publish)
        self.assertIn("persistence receipt not valid", str(ctx.exception))

    def test_invalid_generation_receipt_blocks_compaction(self) -> None:
        checkpoint = self._make_checkpoint()
        def persist(cp): return {"valid": True, "status": "persisted"}
        def publish(cp, sr): return {"valid": False, "status": "failed", "error": "broker down"}
        with self.assertRaises(RuntimeError) as ctx:
            persist_and_publish_checkpoint(checkpoint, persist=persist, publish=publish)
        self.assertIn("publication receipt not valid", str(ctx.exception))

    def test_missing_valid_field_blocks_compaction(self) -> None:
        checkpoint = self._make_checkpoint()
        def persist(cp): return {"status": "persisted"}  # no "valid" field
        def publish(cp, sr): return {"valid": True, "status": "published"}
        with self.assertRaises(RuntimeError) as ctx:
            persist_and_publish_checkpoint(checkpoint, persist=persist, publish=publish)
        self.assertIn("persistence receipt not valid", str(ctx.exception))

    def test_failed_status_receipt_blocks_compaction(self) -> None:
        checkpoint = self._make_checkpoint()
        def persist(cp): return {"valid": True, "status": "failed", "error": "timeout"}
        def publish(cp, sr): return {"valid": True, "status": "published"}
        with self.assertRaises(RuntimeError) as ctx:
            persist_and_publish_checkpoint(checkpoint, persist=persist, publish=publish)
        self.assertIn("persistence receipt not valid", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
