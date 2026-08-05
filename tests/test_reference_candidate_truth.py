import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReferenceCandidateTruthTests(unittest.TestCase):
    def test_delivery_counts_and_partial_runtime_boundaries_are_current(self) -> None:
        value = json.loads(
            (ROOT / "registry/reference_candidate_admission.json").read_text(
                encoding="utf-8"
            )
        )
        counts = {
            state: sum(item["delivery_state"] == state for item in value["records"])
            for state in value["delivery_counts"]
        }
        self.assertEqual(value["delivery_counts"], counts)
        self.assertEqual(value["source_record_count"], len(value["records"]))
        self.assertEqual(
            value["duplicate_source_record_count"],
            len(value["records"])
            - len({item["canonical_id"] for item in value["records"]}),
        )
        for item in value["records"]:
            if item.get("runtime_symbols"):
                self.assertEqual(item["delivery_state"], "partial_semantic_coverage")
                self.assertIn(
                    "broader named source capability remains unadmitted",
                    item["boundary"],
                )


if __name__ == "__main__":
    unittest.main()
