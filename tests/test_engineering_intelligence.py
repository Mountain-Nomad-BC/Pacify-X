from __future__ import annotations

import hashlib
import unittest

from runtime.engineering_intelligence import (
    architecture_drift,
    code_genome,
    dependency_shockwave,
    engineering_health,
    future_debt,
    framework_dna,
    knowledge_collisions,
    opportunity_backlog,
    pattern_candidates,
    project_fitness,
    regression_hypotheses,
    refactoring_plan,
    repository_digital_twin,
    benchmark_lab,
    semantic_drift,
)
from runtime.research_assimilation import ResearchMechanism, admission_experiment, canonicalize_research


class EngineeringIntelligenceTests(unittest.TestCase):
    def test_drift_shockwave_and_refactoring_are_deterministic_and_proposal_only(self) -> None:
        drift = architecture_drift({"api": ["db"]}, {"api": ["db", "cache"], "worker": ["db"]})
        self.assertGreater(drift["drift_score"], 0)
        shockwave = dependency_shockwave({"api": ["db"], "ui": ["api"], "report": ["ui"]}, ["db"], max_depth=2)
        self.assertEqual([item["component"] for item in shockwave["affected"]], ["api", "ui"])
        plan = refactoring_plan({"findings": ({"kind": "contract"},)}, drift)
        self.assertFalse(plan["auto_apply"])
        self.assertTrue(plan["actions"])

    def test_semantics_collisions_debt_health_and_fitness_keep_unknowns_visible(self) -> None:
        semantics = semantic_drift(
            {"auth": {"inputs": ["identity"], "effects": []}},
            {"auth": {"inputs": ["role"], "effects": ["write"]}},
        )
        self.assertTrue(semantics["drift"])
        collisions = knowledge_collisions([
            {"subject": "retention", "position": "keep", "evidence": ["a"]},
            {"subject": "retention", "position": "delete", "evidence": ["b"]},
        ])
        self.assertEqual(len(collisions["collisions"]), 1)
        debt = future_debt([{"change_id": "x", "coupling": 1.0}])
        self.assertGreater(debt["findings"][0]["risk"], 0)
        health = engineering_health({"architecture": 1})
        self.assertFalse(health["certifying"])
        self.assertFalse(project_fitness(["a", "b"], ["a"])["complete"])

    def test_code_genome_parses_without_executing_source(self) -> None:
        genome = code_genome({"module.py": "import os\n\ndef run(value):\n    return value\n"})
        self.assertFalse(genome["executes_source"])
        self.assertEqual(genome["parse_errors"], ())
        self.assertIn("FunctionDef:run:1", genome["files"][0]["symbols"])

    def test_regression_engine_ranks_hypotheses_without_claiming_causality(self) -> None:
        result = regression_hypotheses(
            [{"change_id": "c1", "component": "db", "evidence": ["commit"], "temporal_precedence": True}],
            [{"component": "api"}], {"api": ["db"]},
        )
        self.assertEqual(result["hypotheses"][0]["change_id"], "c1")
        self.assertFalse(result["causality_proven"])

    def test_evolution_and_resilience_candidates_are_bounded_and_non_activating(self) -> None:
        dna = framework_dna({"api": ["db"]}, [{"decision": "typed contracts"}], [{"id": "p1", "validated": True, "principle": "fail closed"}], exclusions=["secrets"])
        self.assertFalse(dna["auto_activate"])
        opportunities = opportunity_backlog([{"activity": "review", "repetitions": 10, "minutes_each": 5, "error_rate": 0.1, "automation_risk": 0.2}])
        self.assertTrue(opportunities["opportunities"])
        patterns = pattern_candidates([{"signature": "verify", "example": "a"}, {"signature": "verify", "example": "b"}])
        self.assertFalse(patterns["patterns"][0]["validated"])
        benchmark = benchmark_lab([
            {"candidate_id": "x", "version": "1", "fixture_version": "f1", "quality": 0.9, "latency": 1, "cost": 2, "resource": 3},
            {"candidate_id": "x", "version": "1", "fixture_version": "f1", "quality": 0.8, "latency": 2, "cost": 2, "resource": 4},
        ])
        self.assertEqual(benchmark["regression_gate"], "evaluable")
        twin = repository_digital_twin(["api", "db"], {"api": ["db"]}, [("api", "db")], [])
        self.assertFalse(twin["source_of_truth"])

    def test_research_requires_citations_and_never_becomes_production_proof(self) -> None:
        text = "source"
        digest = hashlib.sha256(text.encode()).hexdigest()
        first = ResearchMechanism(
            "paper-a", digest, "doi:10.1/a", "memory-trust", "Evidence improves trust.",
            "Gate memory through evidence and revision checks.", ("current evidence",), "benchmark-a",
            ("small sample",), ("local benchmark",),
        )
        second = ResearchMechanism(
            "paper-b", digest, "doi:10.1/b", "memory-trust", "Revision checks reduce stale use.",
            "Gate retrieved memory through evidence and revision status.", ("revision metadata",), "benchmark-b",
            ("domain limited",), ("negative stale-memory test",),
        )
        bundle = canonicalize_research([first, second])
        self.assertEqual(bundle["state"], "candidate")
        candidate = bundle["candidates"][0]
        self.assertEqual(candidate["convergence"], "multi_source")
        self.assertFalse(candidate["production_proof"])
        experiment = admission_experiment(candidate, local_tests=["reproduce"], negative_tests=["stale rejected"])
        self.assertEqual(experiment["decision"], "ready_for_local_experiment")
        missing = canonicalize_research([ResearchMechanism(
            "paper-c", digest, "", "memory-trust", "claim", "mechanism", ("a",), "eval", ("limit",), ("test",),
        )])
        self.assertEqual(missing["state"], "blocked")


if __name__ == "__main__":
    unittest.main()
