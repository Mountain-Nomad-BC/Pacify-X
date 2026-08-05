from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import yaml

from runtime.knowledge_foundry import SourceArtifact
from runtime.memory_vault import MemoryVault
from runtime.project_stream_controls import (
    ScopeEnvelope,
    SwitchEvidence,
    TransferPackage,
)
from runtime.project_stream_orchestrator import (
    ProjectStreamContext,
    execute_project_stream,
)


ROOT = Path(__file__).parents[1]
PREFLIGHT = {
    name: True
    for name in (
        "constitution_resolved",
        "lease_valid",
        "scope_resolved",
        "side_effect_budget_set",
    )
}


def _load_json(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _assert_schema_subset(
    test: unittest.TestCase,
    value: object,
    schema: dict[str, object],
    path: str = "root",
) -> None:
    declared = schema.get("type")
    allowed = (declared,) if isinstance(declared, str) else tuple(declared or ())
    if allowed:
        matches = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }
        test.assertTrue(
            any(matches.get(kind, False) for kind in allowed),
            f"{path}: expected {allowed}, got {type(value).__name__}",
        )
    if "const" in schema:
        test.assertEqual(value, schema["const"], path)
    if "enum" in schema:
        test.assertIn(value, schema["enum"], path)
    if isinstance(value, str) and schema.get("pattern"):
        test.assertIsNotNone(re.search(str(schema["pattern"]), value), path)
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and "minimum" in schema
    ):
        test.assertGreaterEqual(value, schema["minimum"], path)
    if isinstance(value, dict):
        required = set(map(str, schema.get("required", ())))
        test.assertFalse(
            required - set(value), f"{path}: missing {sorted(required - set(value))}"
        )
        properties = dict(schema.get("properties", {}))
        if schema.get("additionalProperties") is False:
            test.assertFalse(
                set(value) - set(properties),
                f"{path}: unexpected {sorted(set(value) - set(properties))}",
            )
        for key, child in value.items():
            if key in properties:
                _assert_schema_subset(test, child, properties[key], f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            _assert_schema_subset(test, child, schema["items"], f"{path}[{index}]")


def _source() -> SourceArtifact:
    text = "# Memory rule\n- Preserve evidence and validate the current revision."
    return SourceArtifact(
        "source",
        "engineering_note",
        "source.md",
        hashlib.sha256(text.encode()).hexdigest(),
        text,
        "internal-reference",
    )


class TempTwoCompletenessTests(unittest.TestCase):
    def test_closed_snapshot_is_compact_and_raw_ledger_is_externalized(self) -> None:
        history = _load_json("evidence/source-intake-receipt.json")
        self.assertEqual(history["file_count"], 318)
        self.assertTrue(history["final_intake_complete"])
        self.assertFalse((ROOT / "planning").exists())
        index = _load_json("evidence/externalized-payload-index.json")
        self.assertTrue(index["records"])

    def test_structured_templates_conform_to_their_contracts(self) -> None:
        template_root = ROOT / "templates/project_stream"
        contract_root = ROOT / "contracts/project_stream"
        pairs = {
            "agent.yaml": "agent_record.schema.json",
            "project.yaml": "project_record.schema.json",
            "workspace.toml": "workspace_config.schema.json",
            "workstream.yaml": "workstream.schema.json",
            "workflow_request.json": "workflow-request.schema.json",
        }
        for template_name, contract_name in pairs.items():
            with self.subTest(template=template_name):
                raw = (template_root / template_name).read_text(encoding="utf-8")
                value = (
                    tomllib.loads(raw)
                    if template_name.endswith(".toml")
                    else (
                        json.loads(raw)
                        if template_name.endswith(".json")
                        else yaml.safe_load(raw)
                    )
                )
                schema = json.loads(
                    (contract_root / contract_name).read_text(encoding="utf-8")
                )
                _assert_schema_subset(self, value, schema)

    def test_markdown_templates_expose_their_contract_fields(self) -> None:
        checks = {
            "decision_record.md": (
                "Decision ID",
                "Project",
                "Status",
                "## Decision",
                "## Evidence",
            ),
            "memory_note.md": (
                "memory_id:",
                "project_id:",
                "source_sha256:",
                "certification_status:",
                "retrieval_enabled:",
            ),
            "quarantine_review.md": (
                "Quarantine ID",
                "Project ID",
                "Original path",
                "Quarantine path",
                "Pre-move SHA-256",
            ),
            "transfer_package.md": (
                "Transfer ID",
                "Source project",
                "Destination project",
                "Purpose",
                "Provenance and license",
            ),
        }
        for name, markers in checks.items():
            body = (ROOT / "templates/project_stream" / name).read_text(
                encoding="utf-8"
            )
            with self.subTest(template=name):
                for marker in markers:
                    self.assertIn(marker, body)

    def test_every_registered_project_stream_workflow_executes_with_synthetic_inputs(
        self,
    ) -> None:
        handlers = _load_json("registry/project_stream_handlers.json")["workflows"]
        effects = {
            item["orchestration_id"]: tuple(item["effects"]) for item in handlers
        }
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            vault = MemoryVault(
                temp / "memory-vault", workspace_id="workspace", project_id="project"
            )

            transfer_root = temp / "transfer"
            transfer_root.mkdir()
            transfer_source = transfer_root / "source.txt"
            transfer_source.write_text("bounded capability", encoding="utf-8")

            active_change = temp / "change" / "active"
            active_change.mkdir(parents=True)
            staged_change = temp / "change" / "staged.py"
            staged_change.write_text("value = 2\n", encoding="utf-8")

            active_recovery = temp / "recovery" / "active"
            active_recovery.mkdir(parents=True)
            recovery_candidate = temp / "recovery" / "candidate.py"
            recovery_candidate.write_text("value = 1\n", encoding="utf-8")

            onboard = temp / "onboard"
            onboard.mkdir()
            (onboard / "pyproject.toml").write_text(
                "[project]\nname='fixture'\n", encoding="utf-8"
            )

            cleanup_active = temp / "cleanup" / "active"
            cleanup_active.mkdir(parents=True)
            cleanup_candidate = cleanup_active / "cache.bin"
            cleanup_candidate.write_bytes(b"recoverable")

            promotion_candidate = temp / "promotion" / "candidate.json"
            promotion_candidate.parent.mkdir()
            promotion_candidate.write_text("{}\n", encoding="utf-8")

            payloads: dict[str, dict[str, object]] = {
                "agent_create_validate": {
                    "ledger": temp / "agent-ledger",
                    "specification": {
                        "agent_id": "agent",
                        "template_id": "template",
                        "project_id": "project",
                        "permissions": ["read"],
                        "tests": {"identity": True, "sandbox": True},
                        "sandbox_validated": True,
                        "evidence": ["synthetic-test"],
                    },
                },
                "chaos_resilience_cycle": {
                    "experiments": [
                        {
                            "experiment_id": "dependency-down",
                            "fault": "dependency_failure",
                            "digital_twin": True,
                            "approved": True,
                            "baseline_evidence": "baseline",
                            "observed_evidence": "trace",
                            "rollback_verified": True,
                            "outcome_met": True,
                        }
                    ]
                },
                "continuous_improvement": {"sources": (_source(),)},
                "cross_project_transfer": {
                    "workspace_root": transfer_root,
                    "source": transfer_source,
                    "destination": transfer_root / "destination" / "source.txt",
                    "ledger": temp / "transfer-ledger",
                    "package": TransferPackage(
                        "transfer-one",
                        "project-old",
                        "project-new",
                        "sanitized_capability",
                        ("synthetic-evidence",),
                        "internal-reference",
                        (),
                        ("synthetic-test",),
                        True,
                        True,
                        True,
                    ),
                },
                "guarded_change": {
                    "active_root": active_change,
                    "staged_file": staged_change,
                    "staging_root": staged_change.parent,
                    "expected_source_sha256": hashlib.sha256(
                        staged_change.read_bytes()
                    ).hexdigest(),
                    "destination": active_change / "app.py",
                    "quarantine_root": temp / "change" / "quarantine",
                    "ledger": temp / "change-ledger",
                    "evidence": {
                        "intent": "bounded change",
                        "tests": ["synthetic"],
                        "outcome_contract": "value present",
                        "rollback": "quarantine",
                        "approval_id": "approval",
                        "idempotency_key": "change-one",
                        "tests_passed": True,
                        "outcome_passed": True,
                    },
                },
                "incident_diagnose_recover": {
                    "active_root": active_recovery,
                    "recovery_candidate": recovery_candidate,
                    "staging_root": recovery_candidate.parent,
                    "transaction_root": temp / "recovery" / "transactions",
                    "expected_source_sha256": hashlib.sha256(
                        recovery_candidate.read_bytes()
                    ).hexdigest(),
                    "destination": active_recovery / "app.py",
                    "quarantine_root": temp / "recovery" / "quarantine",
                    "ledger": temp / "recovery-ledger",
                    "evidence": {
                        "incident_id": "incident-one",
                        "root_cause": "synthetic regression",
                        "recovery_tests": ["synthetic"],
                        "rollback_rehearsal": "verified",
                        "approval_id": "approval",
                        "recovery_tests_passed": True,
                        "rollback_rehearsed": True,
                    },
                },
                "memory_ingest_distill": {"vault": vault, "sources": (_source(),)},
                "memory_maintenance": {"vault": vault},
                "nightly_project_health": {
                    "metrics": {
                        name: 1
                        for name in (
                            "tests",
                            "security",
                            "evidence",
                            "dependencies",
                            "memory",
                            "operations",
                        )
                    }
                },
                "project_close": {
                    "ledger": temp / "close-ledger",
                    "evidence": ("synthetic-test",),
                },
                "project_onboard": {
                    "project": onboard,
                    "ledger": temp / "onboard-ledger",
                },
                "project_pause_resume": {
                    "ledger": temp / "pause-ledger",
                    "action": "pause",
                    "evidence": ("checkpoint",),
                },
                "project_switch": {
                    "ledger": temp / "switch-ledger",
                    "old_scope": ScopeEnvelope(
                        "workspace",
                        "project-old",
                        "agent",
                        "session-old",
                        "stream",
                        "lease-old",
                        "intent",
                        "correlation",
                    ),
                    "new_scope": ScopeEnvelope(
                        "workspace",
                        "project-new",
                        "agent",
                        "session-new",
                        "stream",
                        "lease-new",
                        "intent",
                        "correlation",
                    ),
                    "switch_evidence": SwitchEvidence(
                        True, True, True, True, True, True, True, True
                    ),
                },
                "safe_cleanup": {
                    "active_root": cleanup_active,
                    "candidates": (cleanup_candidate,),
                    "transaction_root": temp / "cleanup" / "transactions",
                    "quarantine_root": temp / "cleanup" / "quarantine",
                    "ledger": temp / "cleanup-ledger",
                },
                "shared_capability_promote": {
                    "candidate": promotion_candidate,
                    "shared_root": temp / "shared",
                    "ledger": temp / "promotion-ledger",
                    "staging_root": promotion_candidate.parent,
                    "expected_source_sha256": hashlib.sha256(
                        promotion_candidate.read_bytes()
                    ).hexdigest(),
                    "evidence": {
                        "capability_id": "fixture",
                        "version": "1.0.0",
                        "provenance": ["synthetic"],
                        "license": "internal-reference",
                        "tests": ["unit"],
                        "benchmark": ["golden"],
                        "approval_id": "approval",
                        "tests_passed": True,
                        "benchmark_passed": True,
                    },
                },
                "workspace_bootstrap": {
                    "workspace_root": temp / "bootstrap-workspace",
                    "project": temp
                    / "bootstrap-workspace"
                    / "projects"
                    / "commissioned",
                    "source_root": ROOT,
                },
                "workstream_plan_dispatch": {
                    "workstreams": (
                        {
                            "work_id": "one",
                            "worker_id": "worker",
                            "lane": "light",
                            "owned_paths": ("src",),
                        },
                    ),
                    "resource_snapshot": {"agents": 0},
                },
            }
            self.assertEqual(set(effects), set(payloads))
            results = {}
            for workflow_id in sorted(payloads):
                context = ProjectStreamContext(
                    workflow_id,
                    "wsp_workspace"
                    if workflow_id == "workspace_bootstrap"
                    else "workspace",
                    ""
                    if workflow_id == "workspace_bootstrap"
                    else (
                        "prj_project" if workflow_id == "project_onboard" else "project"
                    ),
                    "agent",
                    "session",
                    "intent",
                    f"correlation-{workflow_id}",
                    PREFLIGHT,
                    effects[workflow_id],
                    bool(set(effects[workflow_id]) - {"read_local"}),
                    payloads[workflow_id],
                )
                result = execute_project_stream(
                    ROOT, context, checkpoint_root=temp / "checkpoints"
                )
                results[workflow_id] = result.status
                self.assertEqual(
                    result.status, "completed", f"{workflow_id}: {result.reasons}"
                )
                self.assertFalse(result.reasons, workflow_id)
            self.assertEqual(len(results), 17)


if __name__ == "__main__":
    unittest.main()
