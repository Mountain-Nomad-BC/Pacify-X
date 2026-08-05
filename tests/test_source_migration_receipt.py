import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class SourceMigrationReceiptTests(unittest.TestCase):
    def test_historical_source_maps_are_external_and_current_owners_exist(self) -> None:
        receipt = json.loads(
            (ROOT / "evidence/source-migration-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(receipt["complete"])
        self.assertFalse(receipt["runtime_loaded"])
        self.assertTrue(
            all(batch.get("unresolved") == 0 for batch in receipt["batches"])
        )
        self.assertTrue(
            all((ROOT / path).exists() for path in receipt["operational_owners"])
        )
        self.assertFalse((ROOT / "planning/migration").exists())
        index = json.loads(
            (ROOT / "evidence/externalized-payload-index.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(index["records"])

    def test_raw_catalog_inventory_behavior_and_domain_trees_are_external(self) -> None:
        for relative in (
            "planning/catalogs",
            "planning/inventory",
            "planning/external_behavior_intake",
            "knowledge/physical_systems",
            "evidence/builds",
        ):
            self.assertFalse((ROOT / relative).exists())
        for receipt in (
            "evidence/corpus-intake-receipt.json",
            "evidence/domain-reference-receipt.json",
        ):
            payload = json.loads((ROOT / receipt).read_text(encoding="utf-8"))
            self.assertFalse(payload["runtime_loaded"])


if __name__ == "__main__":
    unittest.main()
