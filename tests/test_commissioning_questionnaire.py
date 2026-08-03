import json
from pathlib import Path
import tempfile
import unittest

from runtime.commissioning import commission


ROOT = Path(__file__).resolve().parents[1]


def questionnaire() -> dict:
    return {
        "schema_version": "1.0", "mode": "new",
        "answers": {key: "confirmed" for key in ("goal", "users", "scope", "data", "accessibility", "security", "integrations", "operations", "cost_timeline", "acceptance")},
        "facts": [{"id": "f1", "statement": "confirmed fact", "evidence": ["user"]}],
        "preferences": [], "assumptions": [], "unknowns": [], "contradictions": [], "decisions_requiring_approval": [],
        "human_acceptance": {key: True for key in ("scope", "architecture", "security_governance", "accessibility", "data_integrations", "cost", "execution_waves", "acceptance_criteria")},
    }


class CommissioningQuestionnaireTests(unittest.TestCase):
    def test_valid_questionnaire_populates_governed_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            answer = root / "answers.json"
            answer.write_text(json.dumps(questionnaire()), encoding="utf-8")
            project = root / "project"
            result = commission(project, "new", apply=True, source_root=ROOT, questionnaire=answer)
            state = json.loads((project / ".engineering-bootstrap/project-management/state.json").read_text(encoding="utf-8"))
        self.assertTrue(result["applied"])
        self.assertEqual(state["work"]["objective"], "confirmed")
        self.assertEqual(state["lifecycle"]["status"], "brief_accepted_awaiting_plan")

    def test_mode_mismatch_fails_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = questionnaire(); data["mode"] = "existing"
            answer = root / "answers.json"; answer.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                commission(root / "project", "new", apply=True, source_root=ROOT, questionnaire=answer)
            self.assertFalse((root / "project").exists())


if __name__ == "__main__":
    unittest.main()
