import json
from pathlib import Path
import tempfile
import unittest

from runtime.contracts import (
    SUPPORTED_DIALECT,
    ContractValidationError,
    build_minimal_instance,
    contract_digest,
    validate_contract_corpus,
    validate_instance,
)


ROOT = Path(__file__).resolve().parents[1]


class ContractRuntimeTests(unittest.TestCase):
    def _write_schema(self, root: Path, name: str, rule: dict) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        payload = {
            "$schema": SUPPORTED_DIALECT,
            "$id": f"urn:test:{name}",
            **rule,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

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

    def test_contract_ref_cannot_escape_contract_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            contract_root = workspace / "contracts"
            self._write_schema(workspace, "outside.json", {"type": "string"})
            schema = self._write_schema(contract_root, "root.json", {"$ref": "../outside.json"})
            with self.assertRaisesRegex(ValueError, "escapes contract root"):
                validate_instance("value", schema, contract_root=contract_root)

    def test_contract_ref_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            target = self._write_schema(contract_root, "target.json", {"type": "string"})
            schema = self._write_schema(contract_root, "root.json", {"$ref": str(target.resolve())})
            with self.assertRaises(ValueError):
                validate_instance("value", schema, contract_root=contract_root)

    def test_contract_ref_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            contract_root = workspace / "contracts"
            outside = self._write_schema(workspace, "outside.json", {"type": "string"})
            contract_root.mkdir(parents=True, exist_ok=True)
            link = contract_root / "linked.json"
            try:
                link.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symlinks are unavailable on this platform: {error}")
            schema = self._write_schema(contract_root, "root.json", {"$ref": "linked.json"})
            with self.assertRaisesRegex(ValueError, "symlinked schema references"):
                validate_instance("value", schema, contract_root=contract_root)

    def test_contract_ref_cycle_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            first = self._write_schema(contract_root, "first.json", {"$ref": "second.json"})
            self._write_schema(contract_root, "second.json", {"$ref": "first.json"})
            with self.assertRaisesRegex(ValueError, "schema reference cycle detected"):
                validate_instance("value", first, contract_root=contract_root)

    def test_contract_digest_includes_referenced_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            child = self._write_schema(contract_root, "child.json", {"type": "string", "minLength": 1})
            root = self._write_schema(contract_root, "root.json", {"$ref": "child.json"})
            before = contract_digest(root, contract_root=contract_root)
            self._write_schema(contract_root, child.name, {"type": "string", "minLength": 2})
            after = contract_digest(root, contract_root=contract_root)
            self.assertNotEqual(before, after)

    def test_contract_ref_sibling_constraints_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            self._write_schema(contract_root, "child.json", {"type": "string"})
            root = self._write_schema(
                contract_root,
                "root.json",
                {"$ref": "child.json", "minLength": 5},
            )
            with self.assertRaises(ContractValidationError):
                validate_instance("abc", root, contract_root=contract_root)
            validate_instance("abcde", root, contract_root=contract_root)

    def test_unsupported_schema_combination_fails_admission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            self._write_schema(contract_root, "child.json", {"type": "object"})
            root = self._write_schema(
                contract_root,
                "root.json",
                {"$ref": "child.json", "minProperties": 1},
            )
            with self.assertRaisesRegex(ValueError, "schema admission failed"):
                validate_instance({}, root, contract_root=contract_root)

    def test_contract_dialect_is_declared_in_schema_metadata(self) -> None:
        for path in sorted((ROOT / "contracts").rglob("*.json")):
            with self.subTest(contract=path.relative_to(ROOT).as_posix()):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema.get("$schema"), SUPPORTED_DIALECT)

    def test_strict_datetime_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            schema = self._write_schema(contract_root, "datetime.json", {"type": "string", "format": "date-time"})
            validate_instance("2026-08-03T12:34:56.123Z", schema, contract_root=contract_root)
            for invalid in ("2026-08-03 12:34:56Z", "2026-08-03T12:34:56", "2026-08-03T12:34:56z"):
                with self.subTest(value=invalid), self.assertRaises(ContractValidationError):
                    validate_instance(invalid, schema, contract_root=contract_root)

    def test_uri_format_rejects_scheme_only_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            schema = self._write_schema(contract_root, "uri.json", {"type": "string", "format": "uri"})
            with self.assertRaises(ContractValidationError):
                validate_instance("https:", schema, contract_root=contract_root)
            validate_instance("https://example.com/path", schema, contract_root=contract_root)
            validate_instance("urn:example:value", schema, contract_root=contract_root)

    def test_multipleof_zero_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            schema = self._write_schema(contract_root, "number.json", {"type": "number", "multipleOf": 0})
            with self.assertRaisesRegex(ValueError, "multipleOf must be greater than zero"):
                validate_instance(1, schema, contract_root=contract_root)

    def test_nan_and_infinity_are_rejected_where_numeric(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            schema = self._write_schema(contract_root, "number.json", {"type": "number"})
            for invalid in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(value=invalid), self.assertRaises(ContractValidationError):
                    validate_instance(invalid, schema, contract_root=contract_root)

    def test_boolean_is_not_accepted_as_integer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract_root = Path(temporary) / "contracts"
            schema = self._write_schema(contract_root, "integer.json", {"type": "integer"})
            with self.assertRaises(ContractValidationError):
                validate_instance(True, schema, contract_root=contract_root)


if __name__ == "__main__":
    unittest.main()
