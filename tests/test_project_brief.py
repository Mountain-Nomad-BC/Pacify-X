import json
from pathlib import Path
import tempfile
import unittest

from runtime.commissioning import apply_project_brief, commission


ROOT = Path(__file__).resolve().parents[1]


def answers() -> dict:
    return {
        "schema_version": "1.0",
        "mode": "new",
        "answers": {
            key: "confirmed"
            for key in (
                "goal",
                "users",
                "scope",
                "data",
                "accessibility",
                "security",
                "integrations",
                "operations",
                "cost_timeline",
                "acceptance",
            )
        },
        "facts": [],
        "preferences": [],
        "assumptions": [],
        "unknowns": [],
        "contradictions": [],
        "decisions_requiring_approval": [],
        "human_acceptance": {
            key: True
            for key in (
                "scope",
                "architecture",
                "security_governance",
                "accessibility",
                "data_integrations",
                "cost",
                "execution_waves",
                "acceptance_criteria",
            )
        },
    }


class ProjectBriefTests(unittest.TestCase):
    def test_brief_updates_existing_commissioned_state_with_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            questionnaire = Path(directory) / "answers.json"
            questionnaire.write_text(json.dumps(answers()), encoding="utf-8")
            preview = apply_project_brief(project, questionnaire, source_root=ROOT)
            result = apply_project_brief(
                project, questionnaire, source_root=ROOT, apply=True
            )
            state = json.loads(
                (
                    project / ".engineering-bootstrap/project-management/state.json"
                ).read_text(encoding="utf-8")
            )
            history_count = len(
                list(
                    (
                        project / ".engineering-bootstrap/project-management/history"
                    ).glob("state-*")
                )
            )
        self.assertTrue(preview["approval_required"])
        self.assertTrue(result["applied"])
        self.assertEqual(state["work"]["objective"], "confirmed")
        self.assertGreaterEqual(history_count, 1)


if __name__ == "__main__":
    unittest.main()
