from __future__ import annotations

import hashlib
import math
from pathlib import Path
import tempfile
import unittest

from runtime.knowledge_foundry import (
    CalculationSpec,
    SourceArtifact,
    certify_foundry_bundle,
    compile_calculation,
    compile_foundry_bundle,
    compose_candidate_skills,
    evaluate_calculation,
    evolution_recommendations,
    materialize_candidate_bundle,
)


def source(source_id: str, text: str, **updates: object) -> SourceArtifact:
    values = {
        "source_id": source_id,
        "source_kind": "engineering_note",
        "locator": f"{source_id}.md",
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text": text,
        "license": "internal-reference",
    }
    values.update(updates)
    return SourceArtifact(**values)


class KnowledgeFoundryTests(unittest.TestCase):
    def test_foundry_harvests_normalizes_links_and_emits_multi_artifact_candidates(
        self,
    ) -> None:
        bundle = compile_foundry_bundle(
            (
                source(
                    "one",
                    "# Memory Workflow\n- Retrieve evidence.\n- Validate current revision.\n[[Security]]",
                ),
                source(
                    "two",
                    "# Memory Workflow\n- Retrieve evidence.\nGenerate tests and correct stale memory.",
                ),
            )
        )
        self.assertEqual(bundle.state, "candidate")
        self.assertTrue(bundle.knowledge)
        self.assertIn(("one", "security"), bundle.graph_edges)
        self.assertTrue(bundle.skills)
        self.assertEqual(len(bundle.schemas), len(bundle.skills))
        self.assertEqual(
            certify_foundry_bundle(bundle)["decision"], "certified_candidate"
        )

    def test_research_without_traceable_citation_cannot_certify(self) -> None:
        bundle = compile_foundry_bundle(
            (source("paper", "A paper proposes a validator.", source_kind="paper"),)
        )
        result = certify_foundry_bundle(bundle)
        self.assertEqual(result["decision"], "not_certified")
        self.assertIn("research_citation_missing:paper", result["errors"])

    def test_calculation_emits_executable_python_js_schema_units_and_edges(
        self,
    ) -> None:
        package = compile_calculation(
            CalculationSpec(
                "temperature delta",
                "outdoor - indoor",
                ("outdoor", "indoor"),
                {"outdoor": "degC", "indoor": "degC", "result": "delta_degC"},
            )
        )
        self.assertEqual(
            evaluate_calculation(package, {"outdoor": 30, "indoor": 20}), 10
        )
        self.assertIn("def temperature_delta", package.python_source)
        self.assertIn("export function temperature_delta", package.javascript_source)
        self.assertEqual(
            package.input_schema["properties"]["outdoor"]["x-unit"], "degC"
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            compile_calculation(
                CalculationSpec(
                    "bad", "__import__('os')", ("x",), {"x": "u", "result": "u"}
                )
            )

    def test_calculation_interpreter_supports_only_bounded_finite_arithmetic(
        self,
    ) -> None:
        units = {"x": "u", "y": "u", "result": "u"}
        cases = {
            "x + y": 5.0,
            "x - y": 1.0,
            "x * y": 6.0,
            "x / y": 1.5,
            "x % y": 1.0,
            "x ** y": 9.0,
            "-x + +y": -1.0,
        }
        for equation, expected in cases.items():
            package = compile_calculation(
                CalculationSpec("bounded", equation, ("x", "y"), units)
            )
            self.assertEqual(evaluate_calculation(package, {"x": 3, "y": 2}), expected)
        modulo = compile_calculation(
            CalculationSpec("modulo", "x % y", ("x", "y"), units)
        )
        self.assertIn("pyMod", modulo.javascript_source)
        self.assertEqual(evaluate_calculation(modulo, {"x": -3, "y": 2}), 1.0)

    def test_calculation_interpreter_rejects_pathological_inputs_and_trees(
        self,
    ) -> None:
        units = {"x": "u", "result": "u"}
        package = compile_calculation(
            CalculationSpec("bounded", "x + 1", ("x",), units)
        )
        for value in (True, math.nan, math.inf, -math.inf, 1e101):
            with self.assertRaises(ValueError):
                evaluate_calculation(package, {"x": value})
        with self.assertRaisesRegex(ValueError, "exponent"):
            evaluate_calculation(
                compile_calculation(CalculationSpec("power", "x ** 17", ("x",), units)),
                {"x": 2},
            )
        with self.assertRaisesRegex(ValueError, "depth"):
            compile_calculation(CalculationSpec("deep", "-" * 20 + "x", ("x",), units))
        with self.assertRaisesRegex(ValueError, "node limit"):
            compile_calculation(
                CalculationSpec("wide", "+".join(["x"] * 40), ("x",), units)
            )
        for equation in (
            "x[0]",
            "(x for x in [1])",
            "lambda: x",
            "(y := x)",
            "[x]",
            "'x'",
            "True",
        ):
            with self.assertRaises(ValueError, msg=equation):
                compile_calculation(
                    CalculationSpec("forbidden", equation, ("x",), units)
                )

    def test_materialization_is_candidate_only_append_only_and_complete(self) -> None:
        bundle = compile_foundry_bundle(
            (source("one", "Generate and validate a workflow skill with evidence."),)
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            receipt = materialize_candidate_bundle(bundle, destination)
            root = destination / bundle.bundle_id
            self.assertEqual(receipt["state"], "candidate")
            self.assertTrue((root / "bundle.json").is_file())
            self.assertTrue((root / "benchmarks.json").is_file())
            self.assertTrue(list((root / "skills").glob("*/SKILL.md")))
            with self.assertRaises(FileExistsError):
                materialize_candidate_bundle(bundle, destination)

    def test_composition_and_evolution_never_auto_activate(self) -> None:
        bundle = compile_foundry_bundle(
            (source("one", "Generate, validate, and correct memory workflows."),)
        )
        self.assertGreaterEqual(len(bundle.skills), 2)
        composed = compose_candidate_skills(
            bundle.skills[:2], name="hybrid memory validator"
        )
        self.assertEqual(composed.status, "candidate")
        recommendations = evolution_recommendations(
            (composed,),
            usage={composed.skill_id: 0},
            failure_rates={composed.skill_id: 0.3},
        )
        self.assertTrue(recommendations)
        self.assertTrue(all(item["automatic"] is False for item in recommendations))


if __name__ == "__main__":
    unittest.main()
