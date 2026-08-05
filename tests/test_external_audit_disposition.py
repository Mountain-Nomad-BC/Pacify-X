import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class ExternalAuditDispositionTests(unittest.TestCase):
    def test_all_three_audits_have_zero_open_dispositions_and_live_evidence(
        self,
    ) -> None:
        receipt = json.loads(
            (ROOT / "evidence/external-audit-disposition-20260803.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(receipt["inputs"]), 3)
        self.assertEqual(receipt["finding_count"], 30)
        self.assertEqual(receipt["open_count"], 0)
        self.assertEqual(len(receipt["dispositions"]), 30)
        self.assertEqual(
            {item["id"] for item in receipt["dispositions"]},
            {f"A{number:02d}" for number in range(1, 31)},
        )
        for item in receipt["dispositions"]:
            self.assertNotIn("pending_review", item["status"])
            for relative in item["evidence"]:
                self.assertTrue((ROOT / relative).exists(), f"{item['id']}: {relative}")


if __name__ == "__main__":
    unittest.main()
