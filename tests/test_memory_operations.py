from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest

from runtime.memory_fabric import MemoryRecord
from runtime.memory_operations import (
    GraphNode, SessionEvent, SessionSummaryLedger, StateKVGuard, build_graph_clusters,
    guarded_search, normalize_action_attribution, persist_with_graph_isolation,
)
from runtime.memory_vault import MemoryVault


NOW = datetime.now(timezone.utc)


def record() -> MemoryRecord:
    return MemoryRecord(
        "mem", "wsp", "prj", "agent", "session", "lease", "Title", "fact", "Summary",
        "source", "a" * 64, "E-1", "observation", 0.9, "direct", "internal", ("prj",), NOW, NOW,
    )


class MemoryOperationTests(unittest.TestCase):
    def test_session_summaries_process_only_deltas_and_distinguish_stop_from_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = SessionSummaryLedger(Path(directory))
            first = ledger.summarize("session", (
                SessionEvent(1, "message", "First fact.", NOW),
                SessionEvent(2, "Stop", "", NOW),
            ))
            self.assertEqual(first.lifecycle, "checkpoint")
            second = ledger.summarize("session", (
                SessionEvent(1, "message", "First fact.", NOW),
                SessionEvent(2, "Stop", "", NOW),
                SessionEvent(3, "message", "Second fact.", NOW),
                SessionEvent(4, "SessionEnd", "", NOW),
            ))
            self.assertEqual(second.lifecycle, "final")
            self.assertEqual(second.processed_event_count, 2)
            self.assertIsNone(ledger.summarize("session", (SessionEvent(4, "SessionEnd", "", NOW),)))

    def test_graph_clustering_is_bounded_keeps_provenance_and_continues_after_missing_edges(self) -> None:
        nodes = (
            GraphNode("a", "alpha common", ("E-a",)),
            GraphNode("b", "beta common", ("E-b",)),
            GraphNode("c", "standalone", ("E-c",)),
        )
        result = build_graph_clusters(nodes, (("missing", "a"), ("a", "b")), max_cluster_size=2)
        self.assertEqual(result.missing_edge_endpoints, ("missing",))
        self.assertEqual(result.clusters[0].member_ids, ("a", "b"))
        self.assertEqual(result.clusters[0].provenance, ("E-a", "E-b"))
        self.assertEqual(result.clusters[1].member_ids, ("c",))
        self.assertTrue(result.clusters[1].fallback_used)

    def test_backend_timeout_and_search_failure_are_not_reported_as_empty(self) -> None:
        guard = StateKVGuard(failure_threshold=1, cooldown_seconds=1)
        result = guarded_search(lambda: (_ for _ in ()).throw(RuntimeError("down")), guard, timeout_seconds=0.1)
        self.assertEqual(result.status, "error")
        self.assertEqual(guard.execute("slow", lambda: time.sleep(0.05), timeout_seconds=0.001).error_code, "TimeoutError")
        self.assertEqual(guard.execute("slow", lambda: (), timeout_seconds=0.1).status, "circuit_open")

    def test_attribution_propagates_through_bulk_actions_and_rejects_spoofing(self) -> None:
        payload = normalize_action_attribution({"records": [{"value": 1}, {"value": 2}]}, authenticated_agent_id="agent")
        self.assertTrue(all(item["createdBy"] == item["agentId"] == "agent" for item in payload["records"]))
        with self.assertRaisesRegex(ValueError, "does not match"):
            normalize_action_attribution({"agentId": "other"}, authenticated_agent_id="agent")

    def test_graph_failure_does_not_rollback_canonical_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(Path(directory), workspace_id="wsp", project_id="prj")
            result = persist_with_graph_isolation(
                vault, record(), lambda _: (_ for _ in ()).throw(RuntimeError("graph down")),
                StateKVGuard(), timeout_seconds=0.1,
            )
            self.assertTrue(result["canonical_persisted"])
            self.assertEqual(result["graph_status"], "error")
            self.assertEqual(len(vault.records()), 1)


if __name__ == "__main__":
    unittest.main()
