from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from runtime.memory_fabric import MemoryRecord
from runtime.memory_vault import MemoryVault


NOW = datetime.now(timezone.utc)


def record(memory_id: str = "mem-one", **updates: object) -> MemoryRecord:
    values = {
        "memory_id": memory_id,
        "workspace_id": "wsp",
        "project_id": "prj",
        "owner_id": "agent",
        "session_id": "session",
        "lease_id": "lease",
        "title": "Preserve project memory",
        "memory_type": "decision",
        "summary": "Store concise evidence backed decisions",
        "source_artifact": "decision.md",
        "source_sha256": "a" * 64,
        "evidence_locator": "E-1",
        "epistemic_status": "observation",
        "confidence": 0.9,
        "confidence_method": "direct",
        "classification": "internal",
        "acl": ("prj",),
        "observed_at": NOW,
        "effective_at": NOW,
    }
    values.update(updates)
    return MemoryRecord(**values)


class MemoryVaultTests(unittest.TestCase):
    def test_append_writes_human_note_and_never_overwrites_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = MemoryVault(root, workspace_id="wsp", project_id="prj")
            written = vault.append(record())
            self.assertIn("Knowledge/Decisions/", written.markdown_path)
            note = (root / written.markdown_path).read_text(encoding="utf-8")
            related = vault.append(
                record("related", relationships=("Preserve project memory",))
            )
            related_note = (root / related.markdown_path).read_text(encoding="utf-8")
            self.assertIn("[[Preserve project memory]]", related_note)
            self.assertIn("Preserve project memory", note)
            with self.assertRaisesRegex(ValueError, "revision must be append-only"):
                vault.append(record())

    def test_lifecycle_controls_retrieval_and_correction_supersedes_old_memory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(Path(directory), workspace_id="wsp", project_id="prj")
            vault.append(record())
            self.assertEqual(
                vault.search("evidence backed decisions", actor_id="agent"), ()
            )
            vault.transition("mem-one", "validated", evidence=("test-1",))
            vault.transition("mem-one", "certified", evidence=("test-2",))
            self.assertEqual(
                [
                    item.memory_id
                    for item in vault.search(
                        "evidence backed decisions", actor_id="agent"
                    )
                ],
                ["mem-one"],
            )
            corrected = record(
                "mem-two",
                summary="Store only current corrected decisions",
                supersedes=("mem-one",),
            )
            vault.append(corrected)
            self.assertEqual(
                [item.memory_id for item in vault.retrieval_records(actor_id="agent")],
                ["mem-one"],
            )
            vault.transition("mem-two", "validated", evidence=("test-3",))
            self.assertEqual(
                [item.memory_id for item in vault.retrieval_records(actor_id="agent")],
                ["mem-one"],
            )
            vault.transition("mem-two", "certified", evidence=("test-4",))
            self.assertEqual(
                [item.memory_id for item in vault.retrieval_records(actor_id="agent")],
                ["mem-two"],
            )

    def test_index_publication_is_append_only_and_orphans_are_not_authoritative(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = MemoryVault(root, workspace_id="wsp", project_id="prj")
            vault.append(record())
            first = vault.build_index()
            second = vault.build_index()
            self.assertEqual((first.generation, second.generation), (1, 2))
            self.assertTrue((root / first.manifest_path).is_file())
            orphan = root / ".memory-control/index/generations/000003"
            orphan.mkdir(parents=True)
            (orphan / "entries.json").write_text("[]\n", encoding="utf-8")
            status = vault.reconcile_indexes()
            self.assertEqual(status["authoritative_generation"], "000002")
            self.assertEqual(status["orphan_generations"], ("000003",))
            self.assertFalse(status["hard_delete"])

    def test_concurrent_index_requests_publish_distinct_complete_generations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = MemoryVault(root, workspace_id="wsp", project_id="prj")
            vault.append(record())
            with ThreadPoolExecutor(max_workers=4) as pool:
                generations = tuple(pool.map(lambda _: vault.build_index(), range(4)))
            self.assertEqual(
                sorted(item.generation for item in generations), [1, 2, 3, 4]
            )
            self.assertTrue(
                all((root / item.manifest_path).is_file() for item in generations)
            )

    def test_project_scope_revision_and_bucket_capacity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = MemoryVault(
                root, workspace_id="wsp", project_id="prj", max_records_per_bucket=1
            )
            with self.assertRaisesRegex(ValueError, "outside the vault namespace"):
                vault.append(record(project_id="other", acl=("other",)))
            first = vault.append(record())
            second = vault.append(record("mem-two", title="Different memory"))
            self.assertTrue(first.short_address)
            self.assertTrue(second.short_address)

    def test_memory_shard_same_title_different_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(Path(directory), workspace_id="wsp", project_id="prj")
            first = vault.append(record("one", title="same"))
            second = vault.append(record("two", title="same"))
            self.assertNotEqual(first.short_address, second.short_address)

    def test_memory_shard_full_bucket_expands_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(
                Path(directory),
                workspace_id="wsp",
                project_id="prj",
                max_records_per_bucket=1,
            )
            first = vault.append(record("one", title="same"))
            second = vault.append(record("two", title="same"))
            self.assertGreaterEqual(second.address_bits, first.address_bits)

    def test_memory_shard_corrupt_entry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = MemoryVault(root, workspace_id="wsp", project_id="prj")
            vault.append(record("one"))
            next(root.rglob("record-*.json")).write_text("{bad", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity failure"):
                vault.append(record("two"))

    def test_memory_shard_assignment_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = MemoryVault(Path(directory), workspace_id="wsp", project_id="prj")
            item = record("one")
            self.assertEqual(
                vault._address(item, b"stable"), vault._address(item, b"stable")
            )

    def test_parallel_appends_and_index_publication_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = MemoryVault(root, workspace_id="wsp", project_id="prj")
            with ThreadPoolExecutor(max_workers=4) as pool:
                writes = list(
                    pool.map(
                        lambda index: vault.append(
                            record(f"mem-{index}", title=f"Memory {index}")
                        ),
                        range(8),
                    )
                )
            self.assertEqual(len({item.memory_id for item in writes}), 8)
            self.assertEqual(len(vault.latest_records()), 8)
            with ThreadPoolExecutor(max_workers=2) as pool:
                generations = list(pool.map(lambda _: vault.build_index(), range(2)))
            self.assertEqual(sorted(item.generation for item in generations), [1, 2])
            self.assertEqual(
                vault.reconcile_indexes()["complete_generations"], ("000001", "000002")
            )


if __name__ == "__main__":
    unittest.main()
