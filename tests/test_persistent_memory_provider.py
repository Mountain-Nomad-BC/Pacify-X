from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from runtime.external_capability_provider import plan_external_invocation
from runtime.persistent_memory_provider import (
    PersistentMemoryAuthorization,
    execute,
    installed_package_sha256,
    provider_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_ROOT = os.environ.get("PX_PERSISTENT_MEMORY_EXTERNAL_ROOT")


class PersistentMemoryProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if EXTERNAL_ROOT:
            sys.path.insert(0, EXTERNAL_ROOT)
            importlib.invalidate_caches()

    @classmethod
    def tearDownClass(cls) -> None:
        if EXTERNAL_ROOT and EXTERNAL_ROOT in sys.path:
            sys.path.remove(EXTERNAL_ROOT)
            importlib.invalidate_caches()

    def test_optional_import_absence_is_explicit(self) -> None:
        with mock.patch("runtime.persistent_memory_provider.importlib.util.find_spec", return_value=None):
            self.assertFalse(provider_metadata()["available"])
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                installed_package_sha256()

    def test_metadata_exposes_only_read_advisory_surface(self) -> None:
        metadata = provider_metadata()
        self.assertFalse(metadata["runtime_authority"])
        self.assertFalse(metadata["canonical_memory_authority"])
        self.assertFalse(metadata["default_enabled"])
        self.assertEqual([], metadata["mutation_capabilities_exposed"])
        self.assertEqual(
            {
                "memory.repo.validate",
                "memory.record.list",
                "memory.review.preview",
                "memory.graph.preview",
            },
            set(metadata["capabilities"]),
        )

    def test_external_invocation_plan_is_identity_only(self) -> None:
        plan = plan_external_invocation(
            ROOT,
            provider_id="persistent-memory",
            candidate_id="observe-external-persistent-memory",
            capability="memory.record.list",
            required_effects=("read_local",),
            approved_effects=("read_local",),
            payload={"repo": "/external/memory"},
        )
        self.assertFalse(plan.authority_granted)
        self.assertEqual("govern-persistent-memory", plan.bundle_id)
        self.assertEqual(64, len(plan.plan_sha256))
        with self.assertRaises(PermissionError):
            plan_external_invocation(
                ROOT,
                provider_id="persistent-memory",
                candidate_id="observe-external-persistent-memory",
                capability="memory.record.list",
                required_effects=("read_local",),
                approved_effects=(),
                payload={"repo": "/external/memory"},
            )
        with self.assertRaises(ValueError):
            plan_external_invocation(
                ROOT,
                provider_id="persistent-memory",
                candidate_id="observe-external-persistent-memory",
                capability="memory.record.list",
                required_effects=("read_local",),
                approved_effects=(True,),
                payload={"repo": "/external/memory"},
            )

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_exact_revision_bridge_reads_without_mutating_external_repo(self) -> None:
        from pacifyx_memory.adapter import invoke

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            px = base / "px"
            px.mkdir()
            repo = base / "memory"
            invoke(
                "memory.repo.init",
                {"repo": str(repo), "px_root": str(px), "owner": "u"},
                approved_effects=("write_workspace",),
            )
            invoke(
                "memory.record.add",
                {
                    "repo": str(repo),
                    "user_id": "u",
                    "semantic_key": "domain.fact",
                    "kind": "knowledge",
                    "title": "Fact",
                    "body": "Evidence-backed external fact",
                },
                approved_effects=("write_workspace",),
            )
            before = {p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
            auth = PersistentMemoryAuthorization("req-1", installed_package_sha256())
            listed = execute("memory.record.list", {"repo": str(repo)}, px_root=px, authorization=auth)
            review = execute("memory.review.preview", {"repo": str(repo)}, px_root=px, authorization=auth)
            graph = execute("memory.graph.preview", {"repo": str(repo)}, px_root=px, authorization=auth)
            after = {p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual("domain.fact", listed["result"]["records"][0]["semantic_key"])
            self.assertFalse(review["result"]["review"]["authority_granted"])
            self.assertFalse(graph["result"]["graph"]["authority_granted"])
            self.assertFalse(listed["authority_granted"])
            self.assertFalse(listed["canonical_memory_authority"])

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_revision_boundary_and_mutation_requests_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            px = base / "px"; px.mkdir()
            repo = base / "memory"
            auth = PersistentMemoryAuthorization("req-2", "0" * 64)
            with self.assertRaisesRegex(RuntimeError, "revision"):
                execute("memory.repo.validate", {"repo": str(repo)}, px_root=px, authorization=auth)
            auth = PersistentMemoryAuthorization("req-3", installed_package_sha256())
            with self.assertRaises(PermissionError):
                execute("memory.repo.init", {"repo": str(repo)}, px_root=px, authorization=auth)
            with self.assertRaises(PermissionError):
                execute("memory.repo.validate", {"repo": str(px / "inside")}, px_root=px, authorization=auth)
            with self.assertRaises(PermissionError):
                execute(
                    "memory.repo.validate",
                    {"repo": str(repo)},
                    px_root=px,
                    authorization=PersistentMemoryAuthorization(
                        "req-4", installed_package_sha256(), ("read_local", "write_workspace")
                    ),
                )

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_tampered_event_ledger_is_not_silently_treated_as_empty(self) -> None:
        from pacifyx_memory.adapter import invoke

        with tempfile.TemporaryDirectory() as td:
            base = Path(td); px=base/"px"; px.mkdir(); repo=base/"memory"
            invoke("memory.repo.init", {"repo":str(repo),"px_root":str(px),"owner":"u"}, approved_effects=("write_workspace",))
            invoke("memory.record.add", {"repo":str(repo),"user_id":"u","semantic_key":"k","kind":"knowledge","title":"t","body":"b"}, approved_effects=("write_workspace",))
            events=repo/"memory"/"events"/"events.ndjson"
            rows=events.read_text().splitlines(); row=json.loads(rows[0]); row["payload"]["layer"]="archive"; rows[0]=json.dumps(row); events.write_text("\n".join(rows)+"\n")
            auth=PersistentMemoryAuthorization("req-tamper", installed_package_sha256())
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                execute("memory.record.list", {"repo":str(repo)}, px_root=px, authorization=auth)

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_external_package_full_publication_path_preserves_px_nonauthority(self) -> None:
        from pacifyx_memory.adapter import invoke

        def git(repo: Path, *args: str) -> str:
            return subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True).stdout.strip()

        with tempfile.TemporaryDirectory() as td:
            base=Path(td); px=base/"px"; px.mkdir(); private=base/"private"; public=base/"public"
            invoke("memory.repo.init", {"repo":str(private),"px_root":str(px),"owner":"u"}, approved_effects=("write_workspace",))
            added=invoke("memory.record.add", {"repo":str(private),"user_id":"u","semantic_key":"skill.x","kind":"skill","title":"Skill X","body":"Do X"}, approved_effects=("write_workspace",))
            bundle=invoke("memory.contribution.bundle", {"repo":str(private),"record_ids":[added["result"]["record_id"]],"user_id":"u","addition_type":"skill"}, approved_effects=("write_workspace",))
            subprocess.run(["git","init","-b","main",str(public)],check=True,capture_output=True)
            git(public,"config","user.name","Test"); git(public,"config","user.email","test@example.invalid")
            (public/"README.md").write_text("# public\n"); git(public,"add","README.md"); git(public,"commit","-m","init")
            staged=invoke("memory.contribution.stage", {"contribution_dir":bundle["result"]["path"],"public_repo":str(public),"push":False}, approved_effects=("write_workspace",))
            cid=staged["result"]["contribution_id"]
            original=(public/"contributions"/"incoming"/cid/"original.json").read_bytes()
            invoke("memory.contribution.review", {"public_repo":str(public),"contribution_id":cid,"reviewer":"maintainer","assessment":"accepted","promotion_approved":True}, approved_effects=("write_workspace",))
            promoted=invoke("memory.contribution.promote", {"public_repo":str(public),"contribution_id":cid,"promoter":"maintainer"}, approved_effects=("write_workspace",))
            self.assertEqual(original,(public/"contributions"/"incoming"/cid/"original.json").read_bytes())
            self.assertFalse(promoted["result"]["px_authority_granted"])
            projection=json.loads((public/"public-memory"/"projections"/"active.json").read_text())
            self.assertFalse(projection["px_authority_granted"])
            synced=invoke("memory.public.sync", {"repo":str(private),"public_repo":str(public)}, approved_effects=("write_workspace",))
            self.assertEqual(1,synced["result"]["record_count"])

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_symlink_repo_root_is_rejected_by_boundary(self) -> None:
        from pacifyx_memory.adapter import invoke

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            px = base / "px"; px.mkdir()
            actual = base / "actual"; actual.mkdir()
            link = base / "memory-link"
            link.symlink_to(actual, target_is_directory=True)
            result = invoke(
                "memory.repo.validate",
                {"repo": str(link), "px_root": str(px)},
                approved_effects=("read_local",),
            )
            self.assertFalse(result["result"]["ok"])
            self.assertIn("symlink", " ".join(result["result"]["reasons"]))

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_record_replacement_with_recomputed_digest_still_fails_ledger_binding(self) -> None:
        from pacifyx_memory.adapter import invoke
        from pacifyx_memory.utils import sha256_json

        with tempfile.TemporaryDirectory() as td:
            base = Path(td); px = base / "px"; px.mkdir(); repo = base / "memory"
            invoke("memory.repo.init", {"repo": str(repo), "px_root": str(px), "owner": "u"}, approved_effects=("write_workspace",))
            added = invoke(
                "memory.record.add",
                {"repo": str(repo), "user_id": "u", "semantic_key": "k", "kind": "knowledge", "title": "original", "body": "b"},
                approved_effects=("write_workspace",),
            )
            record_path = repo / "memory" / "records" / f"{added['result']['record_id']}.json"
            record = json.loads(record_path.read_text())
            record["title"] = "replaced"
            record["content_sha256"] = sha256_json({k: v for k, v in record.items() if k != "content_sha256"})
            record_path.write_text(json.dumps(record, indent=2) + "\n")
            auth = PersistentMemoryAuthorization("req-replaced", installed_package_sha256())
            with self.assertRaisesRegex(RuntimeError, "does not bind immutable record content"):
                execute("memory.record.list", {"repo": str(repo)}, px_root=px, authorization=auth)

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_external_mutation_requires_write_effect(self) -> None:
        from pacifyx_memory.adapter import invoke

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "memory"
            with self.assertRaises(PermissionError):
                invoke(
                    "memory.repo.init",
                    {"repo": str(repo), "owner": "u"},
                    approved_effects=("read_local",),
                )

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_rejected_review_cannot_be_promoted(self) -> None:
        from pacifyx_memory.adapter import invoke

        def git(repo: Path, *args: str) -> str:
            return subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True).stdout.strip()

        with tempfile.TemporaryDirectory() as td:
            base = Path(td); px = base / "px"; px.mkdir(); private = base / "private"; public = base / "public"
            invoke("memory.repo.init", {"repo": str(private), "px_root": str(px), "owner": "u"}, approved_effects=("write_workspace",))
            added = invoke("memory.record.add", {"repo": str(private), "user_id": "u", "semantic_key": "k", "kind": "knowledge", "title": "t", "body": "b"}, approved_effects=("write_workspace",))
            bundle = invoke("memory.contribution.bundle", {"repo": str(private), "record_ids": [added["result"]["record_id"]], "user_id": "u"}, approved_effects=("write_workspace",))
            subprocess.run(["git", "init", "-b", "main", str(public)], check=True, capture_output=True)
            git(public, "config", "user.name", "Test"); git(public, "config", "user.email", "test@example.invalid")
            (public / "README.md").write_text("# public\n"); git(public, "add", "README.md"); git(public, "commit", "-m", "init")
            staged = invoke("memory.contribution.stage", {"contribution_dir": bundle["result"]["path"], "public_repo": str(public), "push": False}, approved_effects=("write_workspace",))
            cid = staged["result"]["contribution_id"]
            invoke("memory.contribution.review", {"public_repo": str(public), "contribution_id": cid, "reviewer": "maintainer", "assessment": "rejected"}, approved_effects=("write_workspace",))
            with self.assertRaisesRegex(RuntimeError, "explicit review approval"):
                invoke("memory.contribution.promote", {"public_repo": str(public), "contribution_id": cid, "promoter": "maintainer"}, approved_effects=("write_workspace",))

    @unittest.skipUnless(EXTERNAL_ROOT, "external package source not supplied to test environment")
    def test_contribution_source_and_public_repo_must_be_disjoint(self) -> None:
        from pacifyx_memory.contributions import stage_to_public_repo

        with tempfile.TemporaryDirectory() as td:
            public = Path(td) / "public"
            subprocess.run(["git", "init", "-b", "main", str(public)], check=True, capture_output=True)
            nested = public / "contribution"
            nested.mkdir()
            # The overlap check occurs before bundle verification because copying a
            # source out of/into the same repository is itself invalid custody.
            with self.assertRaisesRegex(ValueError, "disjoint"):
                stage_to_public_repo(nested, public)


if __name__ == "__main__":
    unittest.main()
