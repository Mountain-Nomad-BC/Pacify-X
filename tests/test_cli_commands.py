from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

from runtime.cli import main


ROOT = Path(__file__).parents[1]


def invoke(*arguments: str) -> tuple[int, dict]:
    output = StringIO()
    with redirect_stdout(output):
        status = main(["--root", str(ROOT), *arguments])
    return status, json.loads(output.getvalue())


class CliCommandTests(unittest.TestCase):
    def test_test_profile_timeout_fails_closed_without_traceback(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["pytest"], 1)):
            status, output = invoke("test-profile", "run", "fast")
        self.assertEqual(status, 1)
        self.assertFalse(output["valid"])
        self.assertTrue(output["timed_out"])

    def test_contract_corpus_is_exposed_as_an_auditable_boundary(self) -> None:
        status, output = invoke("contracts", "status")
        self.assertEqual(status, 0)
        self.assertTrue(output["valid"])
        self.assertEqual(output["contract_count"], output["owned_count"])

    def test_startup_classification_and_working_set_commands_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, startup = invoke("startup", "--project", directory)
        self.assertEqual(status, 0)
        self.assertEqual(startup["hydrated_skill_bodies"], [])
        self.assertLessEqual(startup["capability_metadata_count"], 250)
        status, classification = invoke("classify", "--task", "validate a retrieval workflow")
        self.assertEqual(status, 0)
        self.assertIn("retrieval", classification["domains"])
        status, selected = invoke("working-set", "--goal", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertLessEqual(len(selected["capability_ids"]), 3)

    def test_specialties_exposes_metadata_states_without_skill_bodies(self) -> None:
        status, output = invoke("specialties", "--category", "security")
        self.assertEqual(status, 0)
        self.assertTrue(output["valid"])
        self.assertEqual(output["categories"][0]["id"], "security")
        self.assertTrue(all("purpose" in item and "state" in item for item in output["categories"][0]["specialties"]))

    def test_plan_is_bounded_and_includes_unload_plan(self) -> None:
        status, output = invoke("plan", "--goal", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertLessEqual(len(output["candidate_bundle"]), 3)
        self.assertEqual(output["activation_limit"], 1)
        self.assertIn("release", output["unload_plan"])

    def test_authorize_is_fail_closed_without_policy_allowance(self) -> None:
        denied_status, denied = invoke("authorize", "--capability", "evidence-assembler")
        allowed_status, allowed = invoke("authorize", "--capability", "evidence-assembler", "--policy-allowed")
        self.assertEqual(denied_status, 1)
        self.assertFalse(denied["approved"])
        self.assertEqual(allowed_status, 0)
        self.assertTrue(allowed["approved"])

    def test_verify_and_retry_commands_consume_typed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            verification = location / "verification.json"
            verification.write_text(json.dumps({
                "postconditions": {"tests": True},
                "evidence": [{"id": "E-1", "status": "current", "valid": True}],
                "policy_allowed": True,
                "executor_claimed_complete": True,
            }), encoding="utf-8")
            status, output = invoke("verify-outcome", "--request", str(verification))
            self.assertEqual(status, 0)
            self.assertEqual(output["status"], "verified")

            failure = location / "failure.json"
            failure.write_text(json.dumps({
                "task_id": "task-1", "capability_id": "evidence-assembler",
                "fingerprint": "abc", "attempt": 1, "evidence_ids": ["old"], "message": "failed",
            }), encoding="utf-8")
            denied_status, denied = invoke("retry-decision", "--failure", str(failure), "--attempt", "2", "--evidence-id", "old")
            allowed_status, allowed = invoke("retry-decision", "--failure", str(failure), "--attempt", "2", "--evidence-id", "new")
            self.assertEqual(denied_status, 1)
            self.assertIn("new evidence", denied["reason"])
            self.assertEqual(allowed_status, 0)
            self.assertTrue(allowed["allowed"])


if __name__ == "__main__":
    unittest.main()
