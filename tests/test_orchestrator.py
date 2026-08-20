from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from runtime.evidence_assembler import Claim, EvidenceKind, EvidenceLink, EvidenceRecord
from runtime.execution_contract import PolicyDecision
from runtime.lifecycle import FailureRecord, MemoryCheckpointSink, decide_retry
from runtime.orchestrator import CapabilityResult, Orchestrator, TaskRequest


ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)


def successful_result(task_id: str = "task-1") -> CapabilityResult:
    return CapabilityResult(
        claims=(Claim("claim-1", "The requested result is verified"),),
        evidence=(
            EvidenceRecord(
                "evidence-1", task_id, EvidenceKind.TEST, "tests/result.json", NOW
            ),
        ),
        links=(EvidenceLink("claim-1", "evidence-1"),),
        postconditions={"result": True},
        executor_claimed_complete=True,
    )


def request(**changes: object) -> TaskRequest:
    values: dict[str, object] = {
        "task_id": "task-1",
        "goal": "assemble deterministic evidence package",
        "inputs": {
            "task id": "task-1",
            "claims": [],
            "evidence records": [],
            "claim-evidence links": [],
        },
        "preferred_capability_id": "evidence-assembler",
    }
    values.update(changes)
    return TaskRequest(**values)


class OrchestratorTests(unittest.TestCase):
    def test_runs_authorized_handler_and_verifies_result(self) -> None:
        sink = MemoryCheckpointSink()
        orchestrator = Orchestrator(
            ROOT,
            lambda _: lambda context: successful_result(context.request.task_id),
            checkpoint_sink=sink,
            now=lambda: NOW,
        )
        result = orchestrator.run(request(), PolicyDecision(True, ("read_local",)))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.verification.status, "verified")
        self.assertEqual(result.evidence.unsupported_claims, ())
        self.assertTrue(result.unloaded)

    def test_handler_is_not_resolved_before_policy_authorization(self) -> None:
        resolutions: list[str] = []
        orchestrator = Orchestrator(
            ROOT,
            lambda capability_id: resolutions.append(capability_id),
            now=lambda: NOW,
        )
        result = orchestrator.run(request(), PolicyDecision(False, ()))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(resolutions, [])

    def test_nested_px_executor_is_blocked_before_handler_resolution(self) -> None:
        resolutions: list[str] = []
        orchestrator = Orchestrator(
            ROOT,
            lambda capability_id: resolutions.append(capability_id),
            now=lambda: NOW,
        )
        result = orchestrator.run(
            request(
                executor="px-owned-executor",
                explicit_delegation=True,
                active_executors=("codex-host",),
            ),
            PolicyDecision(True, ("read_local",)),
        )
        self.assertEqual(result.status, "blocked")
        self.assertIn("overlapping active executor", " ".join(result.errors))
        self.assertEqual(resolutions, [])

    def test_missing_inputs_blocks_before_activation(self) -> None:
        resolutions: list[str] = []
        orchestrator = Orchestrator(
            ROOT,
            lambda capability_id: resolutions.append(capability_id),
            now=lambda: NOW,
        )
        result = orchestrator.run(
            request(inputs={}), PolicyDecision(True, ("read_local",))
        )
        self.assertEqual(result.status, "blocked")
        self.assertIn("missing inputs", result.errors[0])
        self.assertEqual(resolutions, [])

    def test_unregistered_handler_fails_closed(self) -> None:
        result = Orchestrator(ROOT, lambda _: None, now=lambda: NOW).run(
            request(), PolicyDecision(True, ("read_local",))
        )
        self.assertEqual(result.status, "blocked")
        self.assertIn("no runtime handler", result.errors[0])

    def test_failed_postcondition_is_not_complete(self) -> None:
        bad = successful_result()
        bad = CapabilityResult(
            bad.claims, bad.evidence, bad.links, {"result": False}, True
        )
        result = Orchestrator(ROOT, lambda _: lambda __: bad, now=lambda: NOW).run(
            request(), PolicyDecision(True, ("read_local",))
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.verification.status, "failed")

    def test_handler_exception_becomes_structured_failure_and_unloads(self) -> None:
        def fail(_: object) -> CapabilityResult:
            raise RuntimeError("controlled failure")

        result = Orchestrator(ROOT, lambda _: fail, now=lambda: NOW).run(
            request(), PolicyDecision(True, ("read_local",))
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.failure.fingerprint), 16)
        self.assertTrue(result.unloaded)
        self.assertEqual(result.checkpoints[-1].status, "failed")

    def test_retry_requires_new_evidence_and_respects_budget(self) -> None:
        previous = FailureRecord(
            "task-1", "evidence-assembler", "abc", 1, ("old",), "failure"
        )
        denied = decide_retry(
            previous,
            candidate_attempt=2,
            evidence_ids=("old",),
            max_retries=1,
            require_new_evidence=True,
        )
        allowed = decide_retry(
            previous,
            candidate_attempt=2,
            evidence_ids=("old", "new"),
            max_retries=1,
            require_new_evidence=True,
        )
        exhausted = decide_retry(
            previous,
            candidate_attempt=3,
            evidence_ids=("new",),
            max_retries=1,
            require_new_evidence=True,
        )
        self.assertFalse(denied.allowed)
        self.assertTrue(allowed.allowed)
        self.assertFalse(exhausted.allowed)


if __name__ == "__main__":
    unittest.main()
