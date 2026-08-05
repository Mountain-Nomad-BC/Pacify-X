from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from runtime.release_certification import verify_release_certificate


ROOT = Path(__file__).resolve().parents[1]


class Rel011RevocationTests(unittest.TestCase):
    def test_release_062_is_preserved_but_not_deployment_authoritative(self) -> None:
        certificate_path = ROOT / "evidence/release-certification-0.6.2.json"
        revocation = json.loads(
            (ROOT / "evidence/release-revocation-0.6.2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(revocation["status"], "revoked")
        self.assertFalse(revocation["deployment_authoritative"])
        self.assertTrue(revocation["preservation"]["certificate_unchanged"])
        self.assertEqual(
            revocation["certificate_file_sha256"],
            hashlib.sha256(certificate_path.read_bytes()).hexdigest(),
        )

        state = json.loads(
            (ROOT / ".engineering-bootstrap/project-management/state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotEqual(state["lifecycle"]["phase"], "post-release-hardening")
        self.assertEqual(state["lifecycle"]["status"], "integration-complete")
        self.assertEqual(
            state["evidence"]["validation_receipt"],
            "evidence/releases/0.6.3/public-release-verification.json",
        )
        self.assertFalse(verify_release_certificate(ROOT, release="0.6.2")["valid"])

    def test_public_status_does_not_claim_revoked_release_is_ready(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = (ROOT / "START_HERE_FOR_AI.md").read_text(encoding="utf-8")
        self.assertNotIn("**Status:** Certified deployment-ready", readme)
        self.assertIn("**Current release:** [v0.6.3]", readme)
        self.assertIn("Signed self-certified release published", readme)
        self.assertIn("Version 0.6.3 is the current signed release", start)
        self.assertNotIn("0.6.2", readme)
        self.assertNotIn("0.6.2", start)


if __name__ == "__main__":
    unittest.main()
