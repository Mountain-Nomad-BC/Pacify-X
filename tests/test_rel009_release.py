import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class Rel009ReleaseTests(unittest.TestCase):
    def test_revoked_finalizers_are_not_operational_product_tools(self) -> None:
        self.assertFalse((ROOT / "scripts/finalize_rel008_release.py").exists())
        self.assertFalse((ROOT / "scripts/finalize_rel009_release.py").exists())
        self.assertTrue((ROOT / "runtime/release_certification.py").is_file())

    def test_rel009_certificate_is_historical_and_explicitly_revoked(self) -> None:
        state = json.loads((ROOT / ".engineering-bootstrap/project-management/state.json").read_text(encoding="utf-8"))
        certificate_path = ROOT / "evidence/release-certification-0.6.1.json"
        self.assertTrue(certificate_path.is_file())
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
        self.assertEqual(certificate["release"], "0.6.1")
        self.assertEqual(certificate["status"], "deployment_ready")
        self.assertEqual(certificate["test_evidence"]["source"]["failures"], 0)
        self.assertEqual(certificate["test_evidence"]["installed_wheel"]["failures"], 0)
        self.assertEqual(certificate["gates"]["exact_tools"]["directly_loaded"], certificate["gates"]["exact_tools"]["admitted_tools"])
        self.assertEqual(certificate["gates"]["exact_tools"]["passed_tools"], certificate["gates"]["exact_tools"]["admitted_tools"])
        self.assertTrue(certificate["gates"]["python_surfaces"]["map_current"])
        revocation = json.loads((ROOT / "evidence/release-revocation-0.6.1.json").read_text(encoding="utf-8"))
        self.assertEqual(revocation["status"], "revoked")
        self.assertFalse(revocation["deployment_authoritative"])
        self.assertEqual(hashlib.sha256(certificate_path.read_bytes()).hexdigest(), revocation["certificate_sha256"])
        self.assertEqual(state["lifecycle"]["phase"], "deployment-certified")
        self.assertEqual(
            state["evidence"]["validation_receipt"],
            "evidence/releases/0.6.3/public-release-verification.json",
        )


if __name__ == "__main__":
    unittest.main()
