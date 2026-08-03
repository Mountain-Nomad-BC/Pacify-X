from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from runtime.evidence_assembler import (
    Claim,
    EvidenceKind,
    EvidenceLink,
    EvidenceRecord,
    EvidenceRelation,
    EvidenceStatus,
    Sensitivity,
    assemble_evidence,
)


NOW = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)


def record(
    evidence_id: str,
    *,
    task_id: str = "task-1",
    age: timedelta = timedelta(hours=1),
    status: EvidenceStatus = EvidenceStatus.CURRENT,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        task_id=task_id,
        kind=EvidenceKind.TEST,
        source=f"tests/{evidence_id}.json",
        created_at=NOW - age,
        sensitivity=Sensitivity.INTERNAL,
        status=status,
    )


class EvidenceAssemblerTests(unittest.TestCase):
    def test_assembles_supported_claim_from_local_typed_evidence(self) -> None:
        package = assemble_evidence(
            "task-1",
            [Claim("claim-1", "The focused tests passed")],
            [record("test-result")],
            [EvidenceLink("claim-1", "test-result")],
            as_of=NOW,
            max_age=timedelta(days=1),
        )

        self.assertTrue(package.claims[0].supported)
        self.assertEqual(package.claims[0].attachments[0].record.kind, EvidenceKind.TEST)
        self.assertEqual(package.unsupported_claims, ())
        self.assertEqual(package.warnings, ())

    def test_marks_claim_without_resolved_support_as_unsupported(self) -> None:
        package = assemble_evidence(
            "task-1",
            [Claim("claim-1", "A claim")],
            [],
            [EvidenceLink("claim-1", "missing")],
            as_of=NOW,
        )

        self.assertEqual(package.unsupported_claims, ("claim-1",))
        self.assertEqual(
            [warning.code for warning in package.claims[0].warnings],
            ["unsupported_claim", "unresolved_evidence"],
        )

    def test_stale_and_invalid_statuses_warn_and_do_not_support(self) -> None:
        package = assemble_evidence(
            "task-1",
            [Claim("claim-1", "A claim")],
            [
                record("age-stale", age=timedelta(days=10)),
                record("status-invalid", status=EvidenceStatus.INVALID),
                record("status-stale", status=EvidenceStatus.STALE),
            ],
            [
                EvidenceLink("claim-1", "status-stale"),
                EvidenceLink("claim-1", "age-stale"),
                EvidenceLink("claim-1", "status-invalid"),
            ],
            as_of=NOW,
            max_age=timedelta(days=1),
        )

        codes = {warning.code for warning in package.warnings}
        self.assertEqual(
            codes,
            {"freshness_expired", "status_invalid", "status_stale", "unsupported_claim"},
        )
        self.assertFalse(any(item.usable_for_support for item in package.claims[0].attachments))

    def test_wrong_task_and_future_evidence_are_visible_but_ineligible(self) -> None:
        package = assemble_evidence(
            "task-1",
            [Claim("claim-1", "A claim")],
            [
                record("future", age=timedelta(hours=-1)),
                record("other-task", task_id="task-2"),
            ],
            [
                EvidenceLink("claim-1", "future"),
                EvidenceLink("claim-1", "other-task"),
            ],
            as_of=NOW,
        )

        codes = {warning.code for warning in package.warnings}
        self.assertTrue({"future_dated", "task_scope_mismatch", "unsupported_claim"} <= codes)
        self.assertEqual(len(package.claims[0].attachments), 1)
        self.assertEqual(package.claims[0].attachments[0].record.evidence_id, "future")

    def test_foreign_task_metadata_is_retained_only_when_explicitly_requested(self) -> None:
        package = assemble_evidence(
            "task-1",
            [Claim("claim-1", "A claim")],
            [record("other-task", task_id="task-2")],
            [EvidenceLink("claim-1", "other-task")],
            as_of=NOW,
            strict_task_ownership=False,
        )
        self.assertEqual(len(package.claims[0].attachments), 1)
        self.assertFalse(package.claims[0].attachments[0].usable_for_support)

    def test_current_contradiction_is_surfaced_without_erasing_support(self) -> None:
        package = assemble_evidence(
            "task-1",
            [Claim("claim-1", "A claim")],
            [record("a-support"), record("z-contradiction")],
            [
                EvidenceLink("claim-1", "a-support"),
                EvidenceLink("claim-1", "z-contradiction", EvidenceRelation.CONTRADICTS),
            ],
            as_of=NOW,
        )

        self.assertTrue(package.claims[0].supported)
        self.assertIn("contradictory_evidence", [warning.code for warning in package.warnings])

    def test_result_is_deterministic_across_input_order_and_duplicate_links(self) -> None:
        claims = [Claim("z", "Last"), Claim("a", "First")]
        records = [record("z-record"), record("a-record")]
        links = [
            EvidenceLink("z", "z-record"),
            EvidenceLink("a", "a-record"),
            EvidenceLink("a", "a-record"),
        ]

        first = assemble_evidence("task-1", claims, records, links, as_of=NOW)
        second = assemble_evidence(
            "task-1", reversed(claims), reversed(records), reversed(links), as_of=NOW
        )

        self.assertEqual(first, second)
        self.assertEqual([item.claim.claim_id for item in first.claims], ["a", "z"])

    def test_rejects_ambiguous_or_nondeterministic_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate claim_id"):
            assemble_evidence(
                "task-1",
                [Claim("same", "One"), Claim("same", "Two")],
                [],
                [],
                as_of=NOW,
            )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            assemble_evidence("task-1", [], [], [], as_of=datetime(2026, 8, 1))
        with self.assertRaisesRegex(ValueError, "max_age"):
            assemble_evidence("task-1", [], [], [], as_of=NOW, max_age=timedelta(seconds=-1))


if __name__ == "__main__":
    unittest.main()
