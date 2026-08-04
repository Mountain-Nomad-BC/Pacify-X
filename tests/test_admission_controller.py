from __future__ import annotations

import unittest

from runtime.admission_controller import review


class AdmissionControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = {"id": "reader", "version": "1", "owner": "framework", "provides": ["report"], "consumes": ["path"], "effects": ["read_local"], "dependencies": []}
        self.evidence = {"provenance_verified": True, "license_reviewed": True, "tests_passed": True}

    def test_admits_complete_tested_read_only_capability(self) -> None:
        result = review(self.manifest, self.evidence)
        self.assertEqual(result.disposition, "admit")
        self.assertFalse(result.accepted)
        self.assertFalse(result.authoritative)

    def test_quarantines_missing_contract_or_provenance(self) -> None:
        manifest = dict(self.manifest); manifest.pop("owner")
        evidence = dict(self.evidence); evidence["provenance_verified"] = False
        result = review(manifest, evidence)
        self.assertEqual(result.disposition, "quarantine")
        self.assertEqual(len(result.reasons), 3)

    def test_rejects_unsafe_evidence(self) -> None:
        evidence = dict(self.evidence); evidence["malicious_or_unsafe"] = True
        self.assertEqual(review(self.manifest, evidence).disposition, "reject")

    def test_restricts_untested_or_high_risk_capability(self) -> None:
        manifest = dict(self.manifest); manifest["effects"] = ["network"]
        evidence = dict(self.evidence); evidence["tests_passed"] = False
        result = review(manifest, evidence)
        self.assertEqual(result.disposition, "restrict")
        self.assertEqual(len(result.reasons), 3)

    def test_unknown_effect_fails_closed(self) -> None:
        manifest = dict(self.manifest); manifest["effects"] = ["teleport"]
        self.assertEqual(review(manifest, self.evidence).disposition, "quarantine")


if __name__ == "__main__":
    unittest.main()
