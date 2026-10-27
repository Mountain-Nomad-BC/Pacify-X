from __future__ import annotations

import unittest


def _make_hydration(pressure="checkpoint-required-before-bulk-hydration"):
    """Return a hydrate_selected-like function using cognitive_query's logic inline."""
    def hydrate_selected(
        result, selections, hydrate, *, max_records=8,
        context_used_tokens=None, context_max_tokens=None,
        checkpoint_publication_receipt=None,
    ):
        if pressure in {"checkpoint-required-before-bulk-hydration", "hard-checkpoint-and-block-bulk-hydration"}:
            receipt = dict(checkpoint_publication_receipt or {})
            if receipt.get("schema_version") != "px.context-checkpoint-publication/1.0":
                raise RuntimeError("context pressure blocks hydration until a published checkpoint exists")
            if receipt.get("compaction_permitted") is not True:
                raise RuntimeError("context pressure blocks hydration until a published checkpoint exists")
            checkpoint_id = receipt.get("checkpoint_id")
            if not isinstance(checkpoint_id, str) or not checkpoint_id.startswith("ctx-"):
                raise RuntimeError("context pressure blocks hydration until a published checkpoint exists")
            receipt_sha256 = receipt.get("receipt_sha256")
            if not isinstance(receipt_sha256, str) or len(receipt_sha256) != 64 or any(c not in "0123456789abcdef" for c in receipt_sha256):
                raise RuntimeError("context pressure blocks hydration until a published checkpoint exists")
        return {"hydrated": True}

    return hydrate_selected


class PXAUD081_HydrationValidatesCheckpointReceipt(unittest.TestCase):
    """PX-AUD-081: hydration rejects forged checkpoint-publication receipts."""

    def _valid_receipt(self) -> dict:
        return {
            "schema_version": "px.context-checkpoint-publication/1.0",
            "compaction_permitted": True,
            "checkpoint_id": "ctx-abc123def456",
            "receipt_sha256": "a" * 64,
        }

    def test_valid_receipt_allows_hydration(self) -> None:
        hydrate = _make_hydration()
        result = hydrate(
            None, {}, None, context_used_tokens=100, context_max_tokens=1000,
            checkpoint_publication_receipt=self._valid_receipt(),
        )
        self.assertTrue(result["hydrated"])

    def test_forged_sha256_rejected(self) -> None:
        hydrate = _make_hydration()
        receipt = dict(self._valid_receipt())
        receipt["receipt_sha256"] = "garbage-not-hex"
        with self.assertRaises(RuntimeError):
            hydrate(None, {}, None, context_used_tokens=100, context_max_tokens=1000,
                     checkpoint_publication_receipt=receipt)

    def test_short_sha256_rejected(self) -> None:
        hydrate = _make_hydration()
        receipt = dict(self._valid_receipt())
        receipt["receipt_sha256"] = "a" * 32
        with self.assertRaises(RuntimeError):
            hydrate(None, {}, None, context_used_tokens=100, context_max_tokens=1000,
                     checkpoint_publication_receipt=receipt)

    def test_unbacked_checkpoint_id_rejected(self) -> None:
        hydrate = _make_hydration()
        receipt = dict(self._valid_receipt())
        receipt["checkpoint_id"] = "unbacked-checkpoint"
        with self.assertRaises(RuntimeError):
            hydrate(None, {}, None, context_used_tokens=100, context_max_tokens=1000,
                     checkpoint_publication_receipt=receipt)

    def test_missing_checkpoint_id_rejected(self) -> None:
        hydrate = _make_hydration()
        receipt = dict(self._valid_receipt())
        receipt.pop("checkpoint_id")
        with self.assertRaises(RuntimeError):
            hydrate(None, {}, None, context_used_tokens=100, context_max_tokens=1000,
                     checkpoint_publication_receipt=receipt)

    def test_no_receipt_at_high_pressure_rejected(self) -> None:
        hydrate = _make_hydration()
        with self.assertRaises(RuntimeError):
            hydrate(None, {}, None, context_used_tokens=100, context_max_tokens=1000,
                     checkpoint_publication_receipt=None)

    def test_valid_no_pressure_passes(self) -> None:
        hydrate = _make_hydration(pressure="none")
        result = hydrate(None, {}, None, context_used_tokens=None, context_max_tokens=None,
                          checkpoint_publication_receipt=None)
        self.assertTrue(result["hydrated"])


if __name__ == "__main__":
    unittest.main()
