from __future__ import annotations

from pathlib import Path
import unittest

from runtime.licensing import AUTHOR, LICENSE_ID, PUBLISHER, validate_licensing


ROOT = Path(__file__).parents[1]


class LicensingTests(unittest.TestCase):
    def test_publication_identity_and_license_are_consistent(self) -> None:
        result = validate_licensing(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["license"], LICENSE_ID)
        self.assertEqual(result["author"], AUTHOR)
        self.assertEqual(result["publisher"], PUBLISHER)

    def test_redistributed_third_party_payloads_are_attributed(self) -> None:
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        required = {
            "LICENSES/everything-claude-code-MIT.txt": "Everything Claude Code",
            "LICENSES/mattpocock-skills-MIT.txt": "mattpocock/skills",
            "providers/agency_agents/LICENSE.txt": "AgentLand contributors",
        }
        for relative, attribution in required.items():
            self.assertTrue((ROOT / relative).is_file(), relative)
            self.assertIn(attribution, notice)


if __name__ == "__main__":
    unittest.main()
