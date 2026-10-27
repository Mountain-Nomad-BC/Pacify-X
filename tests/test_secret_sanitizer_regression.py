from __future__ import annotations

import unittest

from runtime.memory_intelligence import sanitize_capture


class PXAUD071_SecretSanitizerDetectsCredentials(unittest.TestCase):
    """PX-AUD-071: secret sanitizer rejects Authorization Bearer and AWS credentials."""

    def test_authorization_bearer_detected(self) -> None:
        result = sanitize_capture(
            'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c'
        )
        self.assertIn("authorization_bearer", result.secret_finding_codes)
        self.assertEqual(result.admission, "quarantined")
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", result.sanitized)

    def test_authorization_bearer_case_insensitive(self) -> None:
        result = sanitize_capture(
            "authorization: bearer abcdefghijklmnopqrstuvwxyz1234567890"
        )
        self.assertIn("authorization_bearer", result.secret_finding_codes)
        self.assertEqual(result.admission, "quarantined")

    def test_aws_access_key_id_detected(self) -> None:
        result = sanitize_capture("AKIAIOSFODNN7EXAMPLE")
        self.assertIn("aws_access_key_id", result.secret_finding_codes)
        self.assertEqual(result.admission, "quarantined")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", result.sanitized)

    def test_aws_secret_access_key_detected(self) -> None:
        result = sanitize_capture(
            'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
        )
        self.assertIn("aws_secret_access_key", result.secret_finding_codes)
        self.assertEqual(result.admission, "quarantined")
        self.assertNotIn("wJalrXUtnFEMI", result.sanitized)

    def test_named_secret_still_detected(self) -> None:
        result = sanitize_capture("api_key = sk-1234567890abcdef1234567890abcdef")
        self.assertIn("api_token", result.secret_finding_codes)
        self.assertEqual(result.admission, "quarantined")

    def test_plain_text_no_secrets_accepted(self) -> None:
        result = sanitize_capture("This is just normal text with no secrets at all.")
        self.assertEqual(result.secret_finding_codes, ())
        self.assertEqual(result.admission, "accepted")
        self.assertEqual(result.sanitized, "This is just normal text with no secrets at all.")

    def test_private_key_still_detected(self) -> None:
        result = sanitize_capture(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        )
        self.assertIn("private_key", result.secret_finding_codes)
        self.assertEqual(result.admission, "quarantined")


if __name__ == "__main__":
    unittest.main()
