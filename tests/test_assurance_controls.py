from __future__ import annotations

import unittest

from runtime.assurance_controls import ASSURANCE_CONTROLS, run_assurance_control


class AssuranceControlTests(unittest.TestCase):
    def valid_payload(self) -> dict:
        evidence = [
            "inventory",
            "baseline",
            "functional",
            "security",
            "dependency",
            "user_workflows",
            "authorization",
            "resilience",
            "scaling",
            "chaos",
            "adversarial_repairs",
            "documentation",
            "operations",
        ]
        return {
            "observed_tools": {"git": {"available": True, "version": "2"}},
            "required_tools": ["git"],
            "proposed_changes": [],
            "credential_store": "git-credential-manager",
            "answers": {
                key: "reviewed"
                for key in (
                    "goal",
                    "users",
                    "data",
                    "accessibility",
                    "security",
                    "integrations",
                    "operations",
                    "acceptance",
                )
            },
            "facts": [{"id": "framework", "evidence": ["pyproject.toml"]}],
            "assumptions": [],
            "unknowns": [],
            "human_acceptance": True,
            "effects": ["read_local"],
            "allowed_effects": ["read_local"],
            "target_paths": ["project/src"],
            "owned_paths": ["project"],
            "budget": {"tool_calls": 2},
            "limits": {"tool_calls": 3},
            "source": "official",
            "sha256": "abc",
            "license": "MIT",
            "permissions": ["read_local"],
            "vulnerabilities": [],
            "malicious_indicators": [],
            "policy_compatible": True,
            "approval": True,
            "level": 7,
            "current_evidence_classes": evidence,
            "discovery_denominator": 3,
            "covered_items": 3,
            "evidence_revision": "2",
            "discovery_revision": "2",
            "opt_in": True,
            "retention_days": 7,
            "max_retention_days": 30,
            "telemetry": {
                "runtime_id": "local",
                "model_version": "1",
                "evidence_coverage": 1.0,
                "latency_ms": 10,
                "drift": "none",
                "benchmark": "passed",
            },
            "capability": "semantic-drift",
            "baseline": "v1",
            "validation_dataset": "cases",
            "false_positive_controls": ["review"],
            "safety_effects": ["read_local"],
        }

    def test_every_control_is_deterministic_and_routed(self) -> None:
        self.assertEqual(len(ASSURANCE_CONTROLS), 7)
        for control_id in ASSURANCE_CONTROLS:
            first = run_assurance_control(control_id, self.valid_payload()).as_dict()
            second = run_assurance_control(control_id, self.valid_payload()).as_dict()
            self.assertEqual(first, second)
            self.assertTrue(first["decision"])

    def test_containment_blocks_scope_effect_budget_and_override_violations(
        self,
    ) -> None:
        payload = self.valid_payload()
        payload.update(
            {
                "effects": ["install_global"],
                "target_paths": ["machine/global"],
                "budget": {"tool_calls": 9},
                "policy_override_requested": True,
                "approval": False,
            }
        )
        result = run_assurance_control("supervise-contained-execution", payload)
        self.assertEqual(result.decision, "block")
        self.assertEqual(
            set(result.reasons),
            {
                "effect_not_allowed",
                "target_outside_owned_scope",
                "budget_exceeded",
                "approval_missing",
                "policy_override_forbidden",
            },
        )

    def test_external_tool_stays_quarantined_without_static_proof_and_approval(
        self,
    ) -> None:
        payload = self.valid_payload()
        payload.update(
            {"sha256": "", "approval": False, "dynamic_analysis_requested": True}
        )
        result = run_assurance_control("quarantine-external-tools", payload)
        self.assertEqual(result.decision, "quarantine")
        self.assertEqual(result.outputs["execution"], "blocked")
        self.assertIn("dynamic_analysis_not_contained", result.reasons)

    def test_skeptical_certification_rejects_denominator_drift_and_unknowns(
        self,
    ) -> None:
        payload = self.valid_payload()
        payload.update(
            {"covered_items": 2, "unknowns": ["rotation"], "evidence_revision": "1"}
        )
        result = run_assurance_control("certify-skeptical-engineering", payload)
        self.assertEqual(result.decision, "not_certified")
        self.assertIn("evidence_superseded_by_discovery", result.reasons)

    def test_runtime_assurance_is_opt_in_redacted_and_fail_closed(self) -> None:
        disabled = run_assurance_control(
            "audit-ai-runtime-assurance", {"opt_in": False}
        )
        self.assertEqual(disabled.decision, "disabled")
        payload = self.valid_payload()
        payload["telemetry"] = {
            **payload["telemetry"],
            "raw_prompt": "private",
            "drift": "high",
        }
        degraded = run_assurance_control("audit-ai-runtime-assurance", payload)
        self.assertEqual(degraded.decision, "degraded")
        self.assertNotIn("raw_prompt", degraded.outputs["passport"])
        self.assertFalse(degraded.outputs["network_collection"])

    def test_commissioning_blocks_high_risk_unknown_and_change_intelligence_never_activates(
        self,
    ) -> None:
        payload = self.valid_payload()
        payload["unknowns"] = [{"id": "data-residency", "risk": "critical"}]
        commissioned = run_assurance_control(
            "commission-evidence-first-project", payload
        )
        self.assertEqual(commissioned.decision, "blocked")
        proposal = run_assurance_control(
            "propose-change-intelligence", self.valid_payload()
        )
        self.assertEqual(proposal.decision, "candidate")
        self.assertFalse(proposal.outputs["auto_activate"])


if __name__ == "__main__":
    unittest.main()
