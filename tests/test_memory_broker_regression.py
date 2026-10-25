from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from runtime.memory_broker import (
    build_memory_query_plan,
    materialize_memory_context,
    validate_memory_query_plan,
)
from runtime.memory_fabric import MemoryRecord
from tests.support.fixtures import NOW, plan as _plan, record as _record


class PXAUD069_NonFiniteBudgetRejected(unittest.TestCase):
    """PX-AUD-069: non-finite memory query limits admit stale records and invalid budgets."""

    def test_nonfinite_max_items_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _plan(max_items=float("inf"))
        self.assertIn("max_items must be a positive integer", str(ctx.exception))

    def test_bool_max_bytes_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _plan(max_bytes=True)
        self.assertIn("max_bytes must be a positive integer", str(ctx.exception))

    def test_trust_floor_bool_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _plan(trust_floor=True)
        self.assertIn("trust_floor must be a finite number between zero and one", str(ctx.exception))

    def test_trust_floor_nan_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _plan(trust_floor=float("nan"))
        self.assertIn("trust_floor must be a finite number between zero and one", str(ctx.exception))


class PXAUD070_InvalidConfidenceQuarantined(unittest.TestCase):
    """PX-AUD-070: broker admits invalid non-finite MemoryRecord confidence."""

    def test_bool_confidence_quarantined(self) -> None:
        result = materialize_memory_context(
            _plan(), [_record("memory:one", confidence=True)], now_utc=NOW
        )
        self.assertFalse(result["eligible"])
        self.assertIn("memory_invalid_confidence:memory:one", result["quarantined"])

    def test_nan_confidence_quarantined(self) -> None:
        result = materialize_memory_context(
            _plan(), [_record("memory:one", confidence=float("nan"))], now_utc=NOW
        )
        self.assertFalse(result["eligible"])
        self.assertIn("memory_invalid_confidence:memory:one", result["quarantined"])

    def test_inf_confidence_quarantined(self) -> None:
        result = materialize_memory_context(
            _plan(), [_record("memory:one", confidence=float("inf"))], now_utc=NOW
        )
        self.assertFalse(result["eligible"])
        self.assertIn("memory_invalid_confidence:memory:one", result["quarantined"])

    def test_confidence_out_of_range_quarantined(self) -> None:
        result = materialize_memory_context(
            _plan(), [_record("memory:one", confidence=1.5)], now_utc=NOW
        )
        self.assertFalse(result["eligible"])
        self.assertIn("memory_invalid_confidence:memory:one", result["quarantined"])


class PXAUD073_SearchLimitBounded(unittest.TestCase):
    """PX-AUD-073: MemoryVault.search negative result limit bypasses intended cap."""

    def test_negative_limit_rejected(self) -> None:
        import tempfile
        from pathlib import Path
        from runtime.memory_vault import MemoryVault

        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(Path(directory), workspace_id="wsp", project_id="prj")
            with self.assertRaises(ValueError) as ctx:
                vault.search("query", actor_id="agent", limit=-1)
            self.assertIn("memory search limit must be an integer", str(ctx.exception))

    def test_limit_above_cap_rejected(self) -> None:
        import tempfile
        from pathlib import Path
        from runtime.memory_vault import MemoryVault

        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(Path(directory), workspace_id="wsp", project_id="prj")
            with self.assertRaises(ValueError) as ctx:
                vault.search("query", actor_id="agent", limit=99999)
            self.assertIn("memory search limit must be an integer", str(ctx.exception))

    def test_bool_limit_rejected(self) -> None:
        import tempfile
        from pathlib import Path
        from runtime.memory_vault import MemoryVault

        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(Path(directory), workspace_id="wsp", project_id="prj")
            with self.assertRaises(ValueError) as ctx:
                vault.search("query", actor_id="agent", limit=True)
            self.assertIn("memory search limit must be an integer", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
