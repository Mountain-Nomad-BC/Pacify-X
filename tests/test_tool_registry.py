from __future__ import annotations

from pathlib import Path
import unittest

from runtime.startup import bounded_startup
from runtime.tooling import probe_tool_family, startup_candidates


ROOT = Path(__file__).resolve().parents[1]


class ToolRegistryTests(unittest.TestCase):
    def test_startup_candidates_remain_bounded_and_metadata_driven(self) -> None:
        self.assertEqual(startup_candidates(ROOT), ("docker", "git", "rg"))
        snapshot = bounded_startup(ROOT, ROOT, tool_resolver=lambda name: f"/{name}")
        self.assertEqual(
            dict(snapshot.tools), {"docker": "/docker", "git": "/git", "rg": "/rg"}
        )

    def test_tool_family_is_probed_only_when_selected(self) -> None:
        probes = probe_tool_family(
            ROOT,
            "security-scanner",
            resolver=lambda name: f"/{name}" if name == "trivy" else None,
        )
        self.assertTrue(
            any(
                item.candidate == "trivy" and item.location == "/trivy"
                for item in probes
            )
        )
        self.assertLessEqual(len(probes), 8)


if __name__ == "__main__":
    unittest.main()
