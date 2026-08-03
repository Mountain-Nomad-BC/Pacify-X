from __future__ import annotations

from pathlib import Path
import unittest

from runtime.system_graph import build_system_graph


ROOT = Path(__file__).parents[1]


class SystemGraphTests(unittest.TestCase):
    def test_graph_spans_every_asset_type_and_has_resolved_deterministic_edges(self) -> None:
        first = build_system_graph(ROOT)
        second = build_system_graph(ROOT)
        self.assertEqual(first, second)
        self.assertEqual({node.asset_type for node in first.nodes}, {"capability", "skill", "builder", "tool", "model", "knowledge", "integration"})
        ids = {node.node_id for node in first.nodes}
        self.assertTrue(all(edge.source in ids and edge.target in ids for edge in first.edges))
        self.assertTrue(any(edge.source == "governed-retrieval-adapter" and edge.target == "corpus-intake-receipt" for edge in first.edges))


if __name__ == "__main__":
    unittest.main()
