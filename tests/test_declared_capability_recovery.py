from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
import unittest

from scripts.reconcile_declared_owner_hashes import reconcile

from runtime.registry import skill_navigation_index
from runtime.skill_navigator import navigate


ROOT = Path(__file__).parents[1]


class DeclaredCapabilityRecoveryTests(unittest.TestCase):
    def test_declared_owner_hash_projection_is_current(self) -> None:
        result = reconcile(ROOT, check=True)
        self.assertTrue(result["valid"], result)

    def test_every_absent_declared_outcome_has_one_hash_bound_canonical_owner(
        self,
    ) -> None:
        payload = json.loads(
            (ROOT / "registry/declared_capability_recovery_map.json").read_text(
                encoding="utf-8"
            )
        )
        catalog = tomllib.loads(
            (ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8")
        )
        statuses = {item["id"]: item["status"] for item in catalog["skills"]}
        records = payload["records"]
        identities = {(item["kind"], item["source_id"]) for item in records}
        self.assertEqual(payload["record_count"], 260)
        self.assertEqual(len(identities), 260)
        for item in records:
            owner = item["canonical_owner"]
            body = ROOT / ".px" / "skills" / owner / "SKILL.md"
            self.assertIn(statuses[owner], {"active", "admitted"})
            self.assertEqual(
                item["owner_body_sha256"], hashlib.sha256(body.read_bytes()).hexdigest()
            )
            if owner in {
                "govern-operating-kernel",
                "analyze-repository-intelligence",
                "engineer-verification-lab",
                "operate-memory-retrieval-observability",
                "secure-agent-supply-chain",
                "govern-runtime-protocol-deployment",
                "manage-revocable-certification",
            }:
                self.assertEqual(
                    item["source_body_state"], "exact_authoritative_recovery"
                )
                self.assertEqual(
                    item["historical_validation_state"], "supplied_and_revalidated"
                )
            contract = json.loads(
                (ROOT / item["owner_package"]).read_text(encoding="utf-8")
            )
            self.assertEqual(contract["status"], "active")
            if "skill_packages" in item["owner_package"]:
                self.assertEqual(contract["id"], owner)
                if contract.get("clean_room") is False:
                    self.assertEqual(
                        contract["provenance"]["type"],
                        "authoritative_contract_and_safe_body_assimilation",
                    )
                else:
                    self.assertTrue(contract["clean_room"])
                self.assertEqual(contract["validation_freshness"], "current")
                for test_path in str(contract["tests"]).split(";"):
                    self.assertTrue((ROOT / test_path.strip()).is_file())
                self.assertTrue((ROOT / contract["evidence"]).is_file())
            else:
                self.assertEqual(contract["validation"]["failed"], 0)
                self.assertEqual(contract["evidence"]["status"], "current")

    def test_every_reconstructed_outcome_routes_to_its_owner_without_body_hydration(
        self,
    ) -> None:
        payload = json.loads(
            (ROOT / "registry/declared_capability_recovery_map.json").read_text(
                encoding="utf-8"
            )
        )
        index = skill_navigation_index(ROOT)
        for item in payload["records"]:
            with self.subTest(source_id=item["source_id"], kind=item["kind"]):
                result = navigate(item["declared_outcome"], index, max_candidates=3)
                returned = [candidate.capability_id for candidate in result.candidates]
                self.assertIn(item["canonical_owner"], returned)
                self.assertGreaterEqual(float(item["routing_score"]), 5.0)


if __name__ == "__main__":
    unittest.main()
