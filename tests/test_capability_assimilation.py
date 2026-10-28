from __future__ import annotations

from pathlib import Path
import unittest

from runtime.capability_assimilation import validate_capability_assimilation


ROOT = Path(__file__).resolve().parents[1]


class CapabilityAssimilationTests(unittest.TestCase):
    def test_scans_dispositions_and_lazy_workflows_reconcile(self) -> None:
        result = validate_capability_assimilation(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["scan_count"], 1)
        self.assertEqual(result["validation_basis"], "current_implementation")
        self.assertFalse(result["historical_scans_verified"])
        self.assertEqual(result["files_accounted"], 3)
        self.assertEqual(len(result["input_sha256"]), 3)
        self.assertGreaterEqual(result["disposition_count"], 30)
        self.assertGreaterEqual(result["workflow_count"], 4)


if __name__ == "__main__":
    unittest.main()


def _current_inputs(tmp_path):
    for name in ["capability_mining_admission.json", "skill_orchestrations.json", "skill_catalog.toml"]:
        target = tmp_path / "registry" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / "registry" / name).read_bytes())
    return tmp_path


def test_fresh_validation_does_not_depend_on_old_receipts(tmp_path):
    import hashlib
    root = _current_inputs(tmp_path)
    assert not (root / "evidence").exists()
    result = validate_capability_assimilation(root)
    assert result["valid"], result["errors"]
    assert result["files_accounted"] == 3
    for name, digest in result["input_sha256"].items():
        assert digest == hashlib.sha256((root / name).read_bytes()).hexdigest()


def test_current_unknown_capability_target_fails_without_historical_gates(tmp_path):
    import json
    root = _current_inputs(tmp_path)
    path = root / "registry/capability_mining_admission.json"
    value = json.loads(path.read_text())
    value["dispositions"][0]["targets"] = ["nonexistent-capability"]
    path.write_text(json.dumps(value))
    result = validate_capability_assimilation(root)
    assert result["valid"] is False
    assert any("unknown skill target" in error for error in result["errors"])


def test_current_empty_workflows_fail_even_with_old_receipt(tmp_path):
    import json
    root = _current_inputs(tmp_path)
    (root / "registry/skill_orchestrations.json").write_text(json.dumps({"workflows": []}))
    (root / "evidence").mkdir()
    (root / "evidence/capability-mining-receipt.json").write_text('{"status":"PASS"}')
    result = validate_capability_assimilation(root)
    assert result["valid"] is False
    assert "current capability admission has no workflows" in result["errors"]
