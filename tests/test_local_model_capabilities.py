from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


def load_script(skill: str, name: str):
    path = ROOT / ".agents" / "skills" / skill / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"test_{skill}_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class LocalModelCapabilityTests(unittest.TestCase):
    def test_architecture_inspection_normalizes_gqa_and_matches_kv_fixture(
        self,
    ) -> None:
        module = load_script("inspect-llm-architecture", "inspect_llm_architecture.py")
        result = module.inspect(
            {
                "model_type": "llama",
                "hidden_size": 4096,
                "intermediate_size": 11008,
                "num_hidden_layers": 32,
                "num_attention_heads": 32,
                "num_key_value_heads": 32,
                "vocab_size": 32000,
                "max_position_embeddings": 4096,
                "hidden_act": "silu",
            },
            {
                "tokens": 4096,
                "batch": 1,
                "kv_bytes_per_element": 2,
                "bits_per_weight": 16,
            },
        )
        self.assertEqual(result["normalized"]["attention_variant"], "MHA")
        self.assertEqual(result["estimates"]["kv_cache_bytes"], 2 * 1024**3)
        self.assertGreater(
            result["estimates"]["estimated_total_parameters"], 6_000_000_000
        )
        self.assertFalse(result["security"]["remote_code_executed"])

    def test_architecture_inspection_rejects_hostile_or_inconsistent_dimensions(
        self,
    ) -> None:
        module = load_script("inspect-llm-architecture", "inspect_llm_architecture.py")
        with self.assertRaises(ValueError):
            module.inspect({"hidden_size": True})
        with self.assertRaises(ValueError):
            module.inspect({"hidden_size": 4097, "num_attention_heads": 32})

    def test_planner_emits_complete_matrix_and_forbids_private_remote_fallback(
        self,
    ) -> None:
        module = load_script(
            "plan-local-model-deployment", "plan_local_model_deployment.py"
        )
        result = module.plan(
            {
                "hardware": {
                    "available_ram_gib": 64,
                    "available_vram_gib": 24,
                    "free_disk_gib": 120,
                    "sustained_disk_read_mib_s": 3000,
                },
                "model": {
                    "weight_gib": 28,
                    "transformed_weight_gib": 16,
                    "architecture_supported": True,
                    "streaming_supported": True,
                    "quantized_weight_gib": {"4bit": 8},
                },
                "workload": {
                    "kv_cache_gib": 2,
                    "privacy_required": True,
                    "remote_fallback_allowed": True,
                },
            }
        )
        by_id = {item["strategy"]: item for item in result["strategies"]}
        self.assertEqual(by_id["quantized-4bit"]["status"], "conditional")
        self.assertEqual(by_id["remote-fallback"]["status"], "forbidden")
        self.assertTrue(result["artifact_budget"]["disk_preflight_passed"])
        self.assertFalse(result["installed_or_executed"])

    def test_planner_keeps_missing_measurement_visible(self) -> None:
        module = load_script(
            "plan-local-model-deployment", "plan_local_model_deployment.py"
        )
        result = module.plan(
            {
                "hardware": {
                    "available_ram_gib": 32,
                    "available_vram_gib": 8,
                    "free_disk_gib": 60,
                },
                "model": {
                    "weight_gib": 12,
                    "architecture_supported": False,
                    "streaming_supported": False,
                },
                "workload": {
                    "privacy_required": False,
                    "remote_fallback_allowed": False,
                },
            }
        )
        self.assertFalse(result["complete"])
        self.assertEqual(result["blocking_unknowns"], ["sustained_disk_read_mib_s"])


if __name__ == "__main__":
    unittest.main()
