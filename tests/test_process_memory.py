from pathlib import Path
import tempfile
import unittest

from runtime.commissioning import commission
from runtime.process_memory import compile_process_candidate, record_process_candidate


ROOT = Path(__file__).parents[1]


def record(outcome_met: bool = True) -> dict:
    return {
        "schema_version": "1.0",
        "goal": "Audit a bootstrap repository",
        "outcome": "Structural and runtime evidence reconciled",
        "decisions": [
            {
                "decision": "compose validators",
                "reason": "avoid shallow duplicate checks",
                "alternatives": ["fixed file counts"],
            }
        ],
        "tools": [
            {
                "tool": "unittest",
                "reason": "authoritative runtime checks",
                "effects": ["read_local"],
            }
        ],
        "steps": [
            "discover canonical owners",
            "run composed validation",
            "investigate failures",
            "rerun and assemble evidence",
        ],
        "failures": [
            {
                "failure": "stale package manifest",
                "recovery": "package missing audit sources",
                "verified": True,
            }
        ],
        "verification": {
            "outcome_met": outcome_met,
            "checks": ["source suite", "installed wheel"],
        },
        "reusable_pattern": "validate engineering outcomes with live composed checks",
        "evidence": ["test receipt", "wheel receipt"],
    }


class ProcessMemoryTests(unittest.TestCase):
    def test_verified_process_compiles_to_inert_graph_backed_candidate(self) -> None:
        result = compile_process_candidate(ROOT, record())
        self.assertTrue(result["valid"])
        self.assertFalse(result["candidate"]["auto_activate"])
        self.assertEqual(result["activation"], "requires_skill_admission_controller")
        self.assertEqual(len(result["execution_graph"]), 4)
        self.assertIn(result["decision"], {"improve_existing", "create_candidate"})

    def test_unverified_outcome_cannot_compile(self) -> None:
        result = compile_process_candidate(ROOT, record(False))
        self.assertFalse(result["valid"])
        self.assertEqual(result["activation"], "blocked")

    def test_apply_records_process_in_commissioned_project_without_activation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            record_process_candidate(ROOT, project, record(), apply=False)
            self.assertFalse(
                (project / ".engineering-bootstrap/project-management/process").exists()
            )
            applied = record_process_candidate(ROOT, project, record(), apply=True)
            self.assertTrue((project / applied["receipt"]).is_file())
            self.assertFalse(applied["candidate"]["auto_activate"])


if __name__ == "__main__":
    unittest.main()
