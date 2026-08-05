from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest

from runtime.memory_fabric import (
    MemoryRecord,
    ProviderIsolationConfig,
    ProviderIsolationEvidence,
    admit_memory,
    assign_shard_address,
    candidate_memories,
    certify_provider_isolation,
    correction_plan,
    decode_hex_alpha,
    encode_hex_alpha,
    normalize_backend_result,
    plan_self_healing,
    memory_record_from_mapping,
)


NOW = datetime.now(timezone.utc)
ROOT = Path(__file__).parents[1]


def record(**updates: object) -> MemoryRecord:
    values = {
        "memory_id": "mem_one",
        "workspace_id": "wsp_main",
        "project_id": "prj_alpha",
        "owner_id": "agt_worker",
        "session_id": "ses_one",
        "lease_id": "lease_one",
        "title": "Bounded memory",
        "memory_type": "decision",
        "summary": "Keep memory project scoped",
        "source_artifact": "decision.md",
        "source_sha256": "a" * 64,
        "evidence_locator": "evd_one",
        "epistemic_status": "observation",
        "confidence": 0.9,
        "confidence_method": "direct_test",
        "classification": "internal",
        "acl": ("prj_alpha",),
        "observed_at": NOW,
        "effective_at": NOW,
        "certification_status": "trusted",
        "retrieval_enabled": True,
    }
    values.update(updates)
    return MemoryRecord(**values)


class MemoryFabricTests(unittest.TestCase):
    def test_memory_template_contains_every_schema_required_field(self) -> None:
        schema = json.loads(
            (ROOT / "contracts/project_stream/memory_note.schema.json").read_text(
                encoding="utf-8"
            )
        )
        template = (ROOT / "templates/project_stream/memory_note.md").read_text(
            encoding="utf-8"
        )
        frontmatter = template.split("---", 2)[1]
        for field in schema["required"]:
            self.assertIn(f"\n{field}:", "\n" + frontmatter, field)
        self.assertIn("bit_width: 8", frontmatter)

    def test_adaptive_address_is_reversible_and_integrity_is_separate(self) -> None:
        address = assign_shard_address("A useful memory", b"canonical content")
        self.assertEqual(
            encode_hex_alpha(decode_hex_alpha(address.short_address)),
            address.short_address,
        )
        self.assertEqual(len(address.integrity_sha256), 64)
        self.assertEqual(address.address_bits, 8)

    def test_collision_expands_only_as_needed(self) -> None:
        base = "collision-base"
        target = assign_shard_address(base, b"a")
        prefix = target.short_address[:2]
        other = None
        for index in range(10000):
            candidate = f"other-{index}"
            if assign_shard_address(candidate, b"b").short_address[:2] == prefix:
                other = candidate
                break
        self.assertIsNotNone(other)
        expanded = assign_shard_address(base, b"a", (other,))
        self.assertTrue(expanded.collision_expanded)
        self.assertGreater(expanded.address_bits, 8)

    def test_memory_requires_attribution_provenance_and_scope(self) -> None:
        self.assertEqual(
            admit_memory(
                record(), active_project_id="prj_alpha", actor_id="agt_worker"
            ).decision,
            "candidate",
        )
        denied = admit_memory(
            record(owner_id="", source_sha256="bad"),
            active_project_id="prj_beta",
            actor_id="agt_worker",
        )
        self.assertEqual(denied.decision, "quarantine")
        self.assertIn("foreign_project_memory", denied.reasons)

    def test_candidates_never_cross_projects(self) -> None:
        local = record(memory_id="mem_local")
        foreign = record(
            memory_id="mem_foreign", project_id="prj_beta", acl=("prj_beta",)
        )
        self.assertEqual(
            candidate_memories(
                "Keep memory project scoped",
                (local, foreign),
                project_id="prj_alpha",
                actor_id="agt_worker",
            ),
            ("mem_local",),
        )

    def test_retrieval_filters_untrusted_expired_and_unauthorized_records(self) -> None:
        untrusted = record(
            memory_id="untrusted",
            certification_status="candidate",
            retrieval_enabled=False,
        )
        expired = record(memory_id="expired", expires_at=NOW - timedelta(seconds=1))
        denied = record(memory_id="denied", acl=("different-actor",))
        self.assertEqual(
            candidate_memories(
                "Keep memory project scoped",
                (untrusted, expired, denied),
                project_id="prj_alpha",
                actor_id="agt_worker",
                now=NOW,
            ),
            (),
        )

    def test_canonical_mapping_builds_the_runtime_record(self) -> None:
        original = record()
        mapping = {
            **{
                name: getattr(original, name)
                for name in (
                    "memory_id",
                    "workspace_id",
                    "project_id",
                    "owner_id",
                    "session_id",
                    "lease_id",
                    "title",
                    "memory_type",
                    "summary",
                    "source_artifact",
                    "source_sha256",
                    "evidence_locator",
                    "epistemic_status",
                    "confidence",
                    "confidence_method",
                    "classification",
                    "acl",
                    "supersedes",
                    "relationships",
                    "revision",
                    "certification_status",
                    "retrieval_enabled",
                )
            },
            "observed_at": original.observed_at.isoformat(),
            "effective_at": original.effective_at.isoformat(),
            "expires_at": None,
        }
        self.assertEqual(memory_record_from_mapping(mapping), original)

    def test_correction_invalidates_every_derived_surface(self) -> None:
        previous = record(revision=1)
        corrected = record(memory_id="mem_two", revision=2, supersedes=("mem_one",))
        result = correction_plan(previous, corrected)
        self.assertEqual(result.decision, "rebuild_required")
        self.assertIn("transfer_exports", result.derived_invalidation)

    def test_external_provider_is_disabled_until_every_isolation_test_passes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ProviderIsolationConfig(
                "prj_alpha",
                root / "memory",
                "db_alpha",
                "idx_alpha",
                "proc_alpha",
                False,
            )
            passing = ProviderIsolationEvidence(
                True, True, True, True, True, True, True
            )
            self.assertEqual(
                certify_provider_isolation(config, passing, project_root=root).decision,
                "disabled",
            )
            self.assertIn(
                "self_attested_provider_evidence_is_not_certifying",
                certify_provider_isolation(config, passing, project_root=root).reasons,
            )
            failing = replace(passing, global_slot_isolated=False)
            self.assertEqual(
                certify_provider_isolation(config, failing, project_root=root).decision,
                "disabled",
            )

    def test_backend_failure_is_not_reported_as_empty_and_repairs_are_dry_run(
        self,
    ) -> None:
        self.assertEqual(
            normalize_backend_result(error=RuntimeError("down")).status, "error"
        )
        self.assertEqual(normalize_backend_result(items=[]).status, "empty")
        plan = plan_self_healing(({"kind": "orphan_index", "target": "gen-2"},))
        self.assertTrue(plan.dry_run)
        self.assertTrue(plan.human_approval_required)
        self.assertFalse(plan.hard_delete_allowed)


if __name__ == "__main__":
    unittest.main()
