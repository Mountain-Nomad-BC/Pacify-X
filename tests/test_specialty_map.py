from __future__ import annotations

import json
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).parents[1]


class SpecialtyMapTests(unittest.TestCase):
    def test_every_source_candidate_has_one_explicit_lifecycle_state(self) -> None:
        queue = json.loads((ROOT / "registry/admission_queue.json").read_text(encoding="utf-8"))
        mapped = json.loads((ROOT / "registry/specialty_map.json").read_text(encoding="utf-8"))
        queue_ids = {item["id"] for item in queue["candidates"]}
        entries = [item for category in mapped["categories"] for item in category["specialties"]]
        self.assertEqual({item["id"] for item in entries}, queue_ids)
        self.assertEqual(len(entries), len(queue_ids))
        self.assertTrue(all(item["state"] in {"active", "mapped_deferred"} for item in entries))

    def test_active_candidate_states_match_canonical_skill_catalog(self) -> None:
        catalog = tomllib.loads((ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8"))
        mapped = json.loads((ROOT / "registry/specialty_map.json").read_text(encoding="utf-8"))
        active_ids = {
            item["id"]
            for item in catalog["skills"]
            if item.get("status") in {"active", "admitted"}
        }
        mapped_active = {
            item["id"]
            for category in mapped["categories"]
            for item in category["specialties"]
            if item["state"] == "active"
        }
        candidate_ids = {
            item["id"]
            for category in mapped["categories"]
            for item in category["specialties"]
        }
        self.assertEqual(mapped_active, active_ids & candidate_ids)
        self.assertEqual(set(mapped["framework_only_active"]), active_ids - candidate_ids)
        self.assertEqual(mapped["candidate_count"], len(candidate_ids))
        self.assertEqual(mapped["active_candidate_count"], len(mapped_active))
        self.assertEqual(mapped["deferred_candidate_count"], len(candidate_ids - mapped_active))


if __name__ == "__main__":
    unittest.main()
