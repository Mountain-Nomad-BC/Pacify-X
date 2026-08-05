from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtime.config import load_startup_config
from runtime.registry import validate_registry


ROOT = Path(__file__).parents[1]


class ConfigAndRegistryTests(unittest.TestCase):
    def test_loads_fail_closed_bounded_startup(self) -> None:
        config = load_startup_config(ROOT / "bootstrap" / "startup.toml")
        self.assertTrue(config.fail_closed)
        self.assertTrue(config.model_agnostic)
        self.assertTrue(config.lifecycle.unload_after_step)
        self.assertGreater(config.budget.max_context_bytes, 0)

    def test_rejects_fail_open_startup(self) -> None:
        original = (ROOT / "bootstrap" / "startup.toml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "startup.toml"
            path.write_text(
                original.replace("fail_closed = true", "fail_closed = false"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "fail_closed"):
                load_startup_config(path)

    def test_registry_is_canonical_and_cross_checked(self) -> None:
        result = validate_registry(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["active_count"], 6)

    def test_registry_rejects_missing_active_ledger_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for relative in (
                "bootstrap/startup.toml",
                "registry/capability_map.json",
                "registry/admission_ledger.json",
            ):
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            data = json.loads(
                (target / "registry/admission_ledger.json").read_text(encoding="utf-8")
            )
            data["records"] = [
                record
                for record in data["records"]
                if record["id"] != "skill-navigator"
            ]
            (target / "registry/admission_ledger.json").write_text(
                json.dumps(data), encoding="utf-8"
            )
            result = validate_registry(target)
            self.assertFalse(result["valid"])
            self.assertTrue(any("ledger" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
