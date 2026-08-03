import json
from pathlib import Path
import tempfile
import unittest

from runtime.contracts import ContractValidationError, build_minimal_instance, validate_contract_corpus, validate_instance


ROOT = Path(__file__).resolve().parents[1]


class ContractRuntimeTests(unittest.TestCase):
    def test_every_shipped_contract_is_valid_owned_and_resolvable(self) -> None:
        result = validate_contract_corpus(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["contract_count"], result["owned_count"])
        self.assertGreater(result["contract_count"], 0)

    def test_validation_rejects_invalid_commissioning_record(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_instance({"schema_version": "1.0", "mode": "new"}, ROOT / "contracts/commissioning-questionnaire.schema.json")

    def test_local_file_reference_is_enforced(self) -> None:
        valid = {
            "schema_version": "1.0", "status": "active", "workspace_id": "wsp_demo",
            "project_id": "prj_demo", "project_root": "projects/demo",
            "memory_namespace": "project/prj_demo", "memory_root": "projects_tracking/projects/prj_demo/memory",
            "scope": {
                "workspace_id": "wsp_demo", "project_id": "prj_demo", "agent_id": "agent_operator",
                "session_id": "session_operator", "workstream_id": "work_1", "lease_id": "lease_1",
                "intent_id": "intent_1", "correlation_id": "corr_1",
            },
            "writable_roots": ["projects/demo"], "created_utc": "2026-08-02T00:00:00Z",
            "expires_utc": "2026-08-02T01:00:00Z", "cross_project_access": "deny",
        }
        validate_instance(valid, ROOT / "contracts/project_stream/active-session.schema.json")

    def test_unsupported_standard_keyword_is_rejected(self) -> None:
        from runtime.contracts import _schema_structure_errors

        self.assertIn("$: unsupported schema keyword minProperties", _schema_structure_errors({"type": "object", "minProperties": 1}))

    def test_every_contract_accepts_generated_positive_and_rejects_empty_negative(self) -> None:
        for path in sorted((ROOT / "contracts").rglob("*.json")):
            with self.subTest(contract=path.relative_to(ROOT).as_posix()):
                validate_instance(build_minimal_instance(path), path)
                schema = json.loads(path.read_text(encoding="utf-8"))
                if schema.get("required"):
                    with self.assertRaises(ContractValidationError):
                        validate_instance({}, path)

    def test_property_named_type_is_not_misread_as_a_schema_keyword(self) -> None:
        from runtime.contracts import _schema_structure_errors

        self.assertEqual(_schema_structure_errors({"type": "object", "properties": {"type": {"type": "string"}}}), [])


if __name__ == "__main__":
    unittest.main()
