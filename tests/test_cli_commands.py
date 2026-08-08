from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.admission_controller import AdmissionDecision
from runtime.cli import main


ROOT = Path(__file__).parents[1]


def invoke(*arguments: str) -> tuple[int, dict]:
    output = StringIO()
    with redirect_stdout(output):
        status = main(["--root", str(ROOT), *arguments])
    return status, json.loads(output.getvalue())


class CliCommandTests(unittest.TestCase):
    def test_benchmark_and_assurance_commands_expose_governed_controls(self) -> None:
        profile = {
            "schema_version": "1.0",
            "run_id": "run-cli",
            "lane": "cold",
            "benchmark": {"name": "suite", "version": "1"},
            "agent": {"name": "agent", "version": "1"},
            "model": {"id": "model", "reasoning": "fixed"},
            "pacify_x": {"enabled": True, "version": "0.6.3", "sha": "a" * 40, "capabilities": []},
            "limits": {"seconds": 60},
            "permissions": {"network": False},
            "retry_policy": {"max_retries": 0, "retryable_classes": []},
            "environment": {"container": "fixed", "memory": "disabled", "cache": "empty"},
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            profile_path = base / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            status, frozen = invoke("benchmark", "freeze", "--profile", str(profile_path))
            self.assertEqual(status, 0)
            self.assertTrue(frozen["profile"]["frozen"])
            axes_path = base / "axes.json"
            axes_path.write_text(
                json.dumps(
                    {
                        "behavior": 1,
                        "evaluator_calibration": 1,
                        "evidence_integrity": 1,
                        "coverage": 1,
                        "regression": 1,
                        "operations": 1,
                    }
                ),
                encoding="utf-8",
            )
            status, score = invoke("assurance", "score", "--axes", str(axes_path))
            self.assertEqual(status, 0)
            self.assertTrue(score["admissible"])

    def test_review_candidate_exit_codes_distinguish_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            evidence = Path(directory) / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            cases = {"admit": 0, "restrict": 2, "quarantine": 3, "reject": 4}
            for disposition, expected in cases.items():
                decision = AdmissionDecision(
                    True,
                    True,
                    disposition in {"admit", "restrict"},
                    True,
                    "test",
                    disposition,
                    (),
                    "test",
                    disposition,
                )
                with (
                    self.subTest(disposition=disposition),
                    patch(
                        "runtime.admission_controller.review_authoritative",
                        return_value=decision,
                    ),
                ):
                    status, output = invoke(
                        "review-candidate",
                        "--manifest",
                        str(manifest),
                        "--evidence",
                        str(evidence),
                    )
                    self.assertEqual(status, expected)
                    self.assertEqual(output["disposition"], disposition)

    def test_authoritative_verification_exit_codes_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / "request.json"
            request.write_text("{}", encoding="utf-8")
            cases = {
                "verified": 0,
                "verification_failed": 5,
                "insufficient_trusted_evidence": 6,
                "invalid_request": 7,
                "evidence_integrity_failure": 8,
            }
            for decision, expected in cases.items():
                result = {
                    "verified": decision == "verified",
                    "authoritative": decision == "verified",
                    "decision": decision,
                    "reasons": [],
                }
                with (
                    self.subTest(decision=decision),
                    patch(
                        "runtime.outcome_verifier.verify_authoritative",
                        return_value=result,
                    ),
                ):
                    status, output = invoke("verify-outcome", "--request", str(request))
                    self.assertEqual(status, expected)
                    self.assertEqual(output["decision"], decision)

    def test_test_profile_timeout_fails_closed_without_traceback(self) -> None:
        timed_out = {
            "valid": False,
            "exit_code": 1,
            "timed_out": True,
            "duration_seconds": 1.0,
            "stdout": "",
            "stderr": "",
            "process_tree_terminated": True,
            "termination": {"method": "test-fixture", "errors": []},
            "errors": ["test profile exceeded 300 seconds"],
        }
        with patch("runtime.test_runner.run_test_command", return_value=timed_out):
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
        status, classification = invoke(
            "classify", "--task", "validate a retrieval workflow"
        )
        self.assertEqual(status, 0)
        self.assertIn("retrieval", classification["domains"])
        status, selected = invoke("working-set", "--goal", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertLessEqual(len(selected["capability_ids"]), 3)
        status, routed = invoke("route", "--task", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertTrue(routed["package"]["complete"])
        self.assertEqual(
            set(routed["discovery"]),
            {
                "skill_catalog",
                "semantic_capability_index",
                "cognitive_map_index",
                "agency_agent_registry",
            },
        )

    def test_specialties_exposes_metadata_states_without_skill_bodies(self) -> None:
        status, output = invoke("specialties", "--category", "security")
        self.assertEqual(status, 0)
        self.assertTrue(output["valid"])
        self.assertEqual(output["categories"][0]["id"], "security")
        self.assertTrue(
            all(
                "purpose" in item and "state" in item
                for item in output["categories"][0]["specialties"]
            )
        )

    def test_cognitive_cli_is_read_only_bounded_and_fresh(self) -> None:
        status, health = invoke("cognitive", "status")
        self.assertEqual(status, 0)
        self.assertTrue(health["valid"])
        self.assertEqual(health["index"]["unresolved_external_dependencies"], 0)
        status, result = invoke(
            "cognitive",
            "query",
            "--query",
            "finite domain constraint solver",
            "--limit",
            "2",
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            result["hits"][0]["identifier"], "finite-domain-constraint-solver"
        )
        status, plan = invoke(
            "cognitive",
            "hydrate-plan",
            "--key",
            "capability:finite-domain-constraint-solver",
            "--max-records",
            "4",
        )
        self.assertEqual(status, 0)
        self.assertLessEqual(len(plan["records"]), 4)

    def test_plan_is_bounded_and_includes_unload_plan(self) -> None:
        status, output = invoke("plan", "--goal", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertLessEqual(len(output["candidate_bundle"]), 3)
        self.assertEqual(output["activation_limit"], 1)
        self.assertIn("release", output["unload_plan"])

    def test_caller_asserted_authorization_is_explicitly_simulated(self) -> None:
        denied_status, denied = invoke(
            "simulate-authorization", "--capability", "evidence-assembler"
        )
        allowed_status, allowed = invoke(
            "simulate-authorization",
            "--capability",
            "evidence-assembler",
            "--policy-allowed",
        )
        self.assertEqual(denied_status, 0)
        self.assertFalse(denied["approved"])
        self.assertFalse(denied["authoritative"])
        self.assertEqual(allowed_status, 0)
        self.assertTrue(allowed["approved"])
        self.assertFalse(allowed["authoritative"])

    def test_verify_and_retry_commands_consume_typed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            verification = location / "verification.json"
            verification.write_text(
                json.dumps(
                    {
                        "postconditions": {"tests": True},
                        "evidence": [{"id": "E-1", "status": "current", "valid": True}],
                        "policy_allowed": True,
                        "executor_claimed_complete": True,
                    }
                ),
                encoding="utf-8",
            )
            status, output = invoke(
                "evaluate-outcome-claims", "--request", str(verification)
            )
            self.assertEqual(status, 0)
            self.assertEqual(output["status"], "verified")
            self.assertFalse(output["authoritative"])

            failure = location / "failure.json"
            failure.write_text(
                json.dumps(
                    {
                        "task_id": "task-1",
                        "capability_id": "evidence-assembler",
                        "fingerprint": "abc",
                        "attempt": 1,
                        "evidence_ids": ["old"],
                        "message": "failed",
                    }
                ),
                encoding="utf-8",
            )
            denied_status, denied = invoke(
                "retry-decision",
                "--failure",
                str(failure),
                "--attempt",
                "2",
                "--evidence-id",
                "old",
            )
            allowed_status, allowed = invoke(
                "retry-decision",
                "--failure",
                str(failure),
                "--attempt",
                "2",
                "--evidence-id",
                "new",
            )
            self.assertEqual(denied_status, 1)
            self.assertIn("new evidence", denied["reason"])
            self.assertEqual(allowed_status, 0)
            self.assertTrue(allowed["allowed"])


if __name__ == "__main__":
    unittest.main()
