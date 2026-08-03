from __future__ import annotations

import unittest
from pathlib import Path

from runtime.models import ModelCapability, discover_local_runtimes, load_model_routing_policy, rank_models
from runtime.retrieval import RetrievalSource, retrieve
from runtime.integration_registry import validate_integrations


class RetrievalAndModelTests(unittest.TestCase):
    def test_integration_registry_contract_import_and_smoke(self) -> None:
        root = Path(__file__).parents[1]
        result = validate_integrations(root, smoke=True)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["active_count"], 3)
        self.assertTrue(result["smoke_tested"])

    def test_model_routing_policy_is_lazy_loadable_and_fail_closed(self) -> None:
        root = Path(__file__).parents[1]
        policy = load_model_routing_policy(root)
        self.assertEqual(policy.trait_weight, 10.0)
        self.assertEqual(policy.sensitive_privacy, ("local", "isolated"))
        self.assertTrue(policy.unavailable_is_ineligible)
        model = ModelCapability("local", "runtime", True, 16000, ("coding",), False, "local", "free", "low", 1, 1, ())
        self.assertEqual(rank_models(("coding",), (model,), policy=policy)[0].model_id, "local")

    def test_retrieval_uses_identity_scope_filters_sources_and_emits_lineage(self) -> None:
        sources = (
            RetrievalSource("public", "Capability registry", "workflow capability manifest", ("public",), "inventory:1", "registry"),
            RetrievalSource("restricted", "Secret graph", "workflow relationship", ("admin",), "inventory:2", "document", ("public",)),
        )
        result = retrieve("workflow capability registry", sources, identity_scope=("reader",), client_claimed_role="admin")
        self.assertEqual(result.strategy, "manifest")
        self.assertEqual(result.filtered_source_ids, ("restricted",))
        self.assertEqual(result.hits[0].citation, "source:public")
        self.assertEqual(result.hits[0].lineage, "inventory:1")
        self.assertIn("client_role_authoritative=false", result.trace)

    def test_retrieval_obeys_context_budget_and_degrades_explicitly(self) -> None:
        source = RetrievalSource("one", "test", "test " * 1000, ("public",), "lineage")
        result = retrieve("test", (source,), identity_scope=(), max_context_bytes=10)
        self.assertEqual(result.mode, "degraded_no_match")
        self.assertEqual(result.context_bytes, 0)

    def test_local_runtime_discovery_is_bounded_and_does_not_load_models(self) -> None:
        calls = []
        found = discover_local_runtimes(("z", "a", "b", "c"), resolver=lambda name: calls.append(name) or (f"/{name}" if name == "a" else None), max_runtimes=2)
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(found, (("a", "/a"),))

    def test_model_routing_is_capability_based_sensitive_and_explicit_on_fallback(self) -> None:
        models = (
            ModelCapability("local", "runtime", True, 16000, ("coding", "reasoning"), False, "local", "free", "low", 1, 1, ()),
            ModelCapability("remote", "provider", True, 64000, ("coding", "reasoning", "vision"), True, "policy_gated", "medium", "medium", 0, 0, ()),
        )
        route = rank_models(("coding", "reasoning"), models, sensitive=True)
        self.assertEqual(route[0].model_id, "local")
        fallback = rank_models(("vision",), models, sensitive=True)
        self.assertTrue(fallback[0].fallback_required)
        self.assertIsNone(fallback[0].model_id)


if __name__ == "__main__":
    unittest.main()
