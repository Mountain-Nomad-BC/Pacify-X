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


if __name__ == "__main__":
    unittest.main()
