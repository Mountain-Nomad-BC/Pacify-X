from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from runtime.external_capability_provider import load_external_catalog

ROOT = Path(__file__).resolve().parents[1]


class PersistentMemoryWorkflowTests(unittest.TestCase):
    def test_workflow_is_advisory_read_only(self) -> None:
        workflow = json.loads((ROOT / "orchestration/workflows/persistent-memory-review.yaml").read_text())
        item = workflow["workflows"][0]
        self.assertEqual("persistent-memory-review", item["id"])
        self.assertEqual(["read_local"], item["effects"])
        self.assertFalse(item["bounds"]["canonical_memory_mutation"])
        self.assertFalse(item["bounds"]["external_repo_mutation"])
        self.assertFalse(item["bounds"]["public_projection_mutation"])
        self.assertFalse(item["bounds"]["network"])
        self.assertFalse(item["bounds"]["authority_granted"])
        self.assertEqual(
            ["validate-boundary", "list-memory", "review-preview", "graph-preview", "emit-advisory-evidence"],
            [step["id"] for step in item["steps"]],
        )

    def test_contract_exposes_no_mutation_capability(self) -> None:
        contract = json.loads((ROOT / "contracts/persistent_memory/memory-provider.contract.json").read_text())
        caps = set(contract["properties"]["capability"]["enum"])
        self.assertEqual({"memory.repo.validate","memory.record.list","memory.review.preview","memory.graph.preview"}, caps)
        self.assertEqual(False, contract["properties"]["canonical_memory_authority"]["const"])
        self.assertEqual(False, contract["properties"]["authority_granted"]["const"])
        self.assertIn("noncanonical", contract["description"])

    def test_skill_package_body_hash_and_effects(self) -> None:
        package = json.loads((ROOT / "registry/skill_packages/govern-persistent-memory.json").read_text())
        body = ROOT / package["body"]
        self.assertEqual(hashlib.sha256(body.read_bytes()).hexdigest(), package["body_sha256"])
        self.assertEqual("mapped_deferred", package["status"])
        self.assertEqual(["read_local"], package["effects"])

    def test_external_catalog_bundle_is_deferred_and_reciprocal(self) -> None:
        catalog = load_external_catalog(ROOT)
        bundle = next(row for row in catalog["bundles"] if row["id"] == "govern-persistent-memory")
        self.assertEqual("requires_admission", bundle["activation"])
        self.assertEqual("mapped_deferred", bundle["status"])
        expected = {
            "observe-external-persistent-memory",
            "maintain-external-persistent-memory",
            "prepare-external-memory-contribution",
            "review-external-memory-contribution",
            "publish-external-memory-projection",
        }
        self.assertEqual(expected, set(bundle["candidate_capabilities"]))
        candidate_ids = {row["id"] for row in catalog["candidates"] if row["bundle"] == "govern-persistent-memory"}
        self.assertEqual(expected, candidate_ids)
        source_ids = {row["id"] for row in catalog["licenses"]["sources"]}
        self.assertIn("pacify-x-persistent-memory", source_ids)


if __name__ == "__main__":
    unittest.main()
