from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Rel008AssimilationTests(unittest.TestCase):
    def test_every_source_file_has_closed_disposition(self) -> None:
        receipt = load(ROOT / "evidence/rel008-assimilation.json")
        self.assertEqual(receipt["source_files_at_expanded_intake"], 2195)
        self.assertEqual(receipt["source_files_at_close"], 2192)
        self.assertEqual(receipt["source_generated_cache_files_quarantined"], 3)
        self.assertEqual(receipt["open_file_dispositions"], 0)
        self.assertEqual(receipt["status"], "verified_complete")
        self.assertFalse(receipt["intake_quarantine"]["hard_delete"])

    def test_all_authoritative_declared_contracts_are_assimilated(self) -> None:
        owners = ["govern-operating-kernel", "analyze-repository-intelligence", "engineer-verification-lab", "operate-memory-retrieval-observability", "secure-agent-supply-chain", "govern-runtime-protocol-deployment", "manage-revocable-certification"]
        total = 0
        for owner in owners:
            base = ROOT / ".agents" / "skills" / owner / "references"
            for name in ("capability-contracts.json", "script-contracts.json"):
                contracts = load(base / name)["contracts"]
                total += len(contracts)
                for contract in contracts:
                    self.assertTrue("authoritative_sha256" in contract or "authoritative_source_sha256" in contract, contract["id"])
                    self.assertNotIn("historical_non_claim", contract)
        workflows = load(ROOT / "orchestration" / "workflows" / "declared-suite.yaml")["workflows"]
        total += len(workflows)
        self.assertEqual(total, 257)
        self.assertTrue(all("authoritative_sha256" in workflow for workflow in workflows))

    def test_unsafe_upstream_bodies_are_not_admitted(self) -> None:
        tools = load(ROOT / "registry" / "declared_suite_authoritative_tools.json")
        rejected = {item["id"] for item in tools["rejected"]}
        self.assertEqual(rejected, {"archive-hygiene", "benchmark-harness", "scenario-runner"})
        admitted_paths = {item["target"] for item in tools["admitted"]}
        self.assertFalse(any("archive_hygiene" in path or "benchmark_harness" in path or "scenario_runner" in path for path in admitted_paths))

    def test_contracts_are_split_for_single_outcome_lazy_loading(self) -> None:
        owners = ["govern-operating-kernel", "analyze-repository-intelligence", "engineer-verification-lab", "operate-memory-retrieval-observability", "secure-agent-supply-chain", "govern-runtime-protocol-deployment", "manage-revocable-certification"]
        split_total = 0
        for owner in owners:
            references = ROOT / ".agents" / "skills" / owner / "references"
            for name in ("capabilities-index.json", "scripts-index.json"):
                index = load(references / name)
                split_total += index["count"]
                for record in index["records"]:
                    self.assertTrue((ROOT / record["path"]).is_file())
        self.assertEqual(split_total, 195)
        meta = load(ROOT / ".agents" / "skills" / "govern-metacognitive-evolution" / "references" / "capability-index.json")
        self.assertEqual(meta["count"], 50)
        self.assertTrue(all((ROOT / record["path"]).is_file() for record in meta["records"]))

    def test_exact_recovery_report_covers_all_previously_missing_bodies(self) -> None:
        recovery = load(ROOT / "registry/declared_capability_recovery_map.json")
        exact = [record for record in recovery["records"] if record["source_body_state"] == "exact_authoritative_recovery"]
        self.assertEqual(len(exact), 257)
        self.assertTrue(all(record["historical_validation_state"] == "supplied_and_revalidated" for record in exact))
        self.assertEqual(load(ROOT / "evidence/rel008-assimilation.json")["declared_suite"]["authoritative_body_matches"], 1233)

    def test_skill_package_body_hash_is_current(self) -> None:
        package = load(ROOT / "registry" / "skill_packages" / "govern-metacognitive-evolution.json")
        body = ROOT / package["body"]
        self.assertEqual(package["body_sha256"], hashlib.sha256(body.read_bytes()).hexdigest())
        self.assertEqual(package["provenance"]["type"], "sanitized_authoritative_assimilation")


if __name__ == "__main__":
    unittest.main()
