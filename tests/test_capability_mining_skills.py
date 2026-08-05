from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(skill: str, script: str):
    path = ROOT / ".agents" / "skills" / skill / "scripts" / script
    spec = importlib.util.spec_from_file_location(
        f"test_{skill.replace('-', '_')}", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CapabilityMiningSkillTests(unittest.TestCase):
    def test_security_aggregation_minimizes_payloads_and_preserves_failure(self):
        module = load_script(
            "orchestrate-security-validation", "aggregate_security_findings.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scanner.json").write_text(
                json.dumps(
                    {
                        "tool": "scanner",
                        "status": "fail",
                        "findings": [
                            {
                                "severity": "high",
                                "location": "a.py:2",
                                "message": "sensitive detail",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = module.aggregate(root)
            self.assertFalse(result["complete"] is False)
            self.assertEqual(result["status_counts"]["fail"], 1)
            self.assertNotIn("sensitive detail", json.dumps(result))

    def test_dynamic_discovery_flags_unleased_address(self):
        module = load_script("dynamic-service-discovery", "audit_service_discovery.py")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "proxy.conf").write_text(
                "proxy_pass http://10.0.0.7:8080;\n", encoding="utf-8"
            )
            result = module.audit(root)
            self.assertEqual(len(result["findings"]), 1)
            (root / "proxy.conf").write_text(
                "resolver 127.0.0.11 valid=10s;\nproxy_pass http://10.0.0.7:8080;\n",
                encoding="utf-8",
            )
            self.assertEqual(module.audit(root)["findings"], [])

    def test_text_repair_is_deterministic_and_separate(self):
        module = load_script("repair-corrupted-text", "repair_text.py")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.txt"
            mapping = root / "mapping.json"
            source.write_text("alpha bad-token omega", encoding="utf-8")
            mapping.write_text(
                json.dumps({"version": "1", "replacements": {"bad-token": "fixed"}}),
                encoding="utf-8",
            )
            output, receipt = module.repair(source, mapping)
            self.assertEqual(output.decode(), "alpha fixed omega")
            self.assertEqual(
                source.read_text(encoding="utf-8"), "alpha bad-token omega"
            )
            self.assertTrue(receipt["changed"])

    def test_import_boundary_audit_checks_patterns_and_mirrors(self):
        module = load_script(
            "enforce-source-import-boundaries", "audit_import_boundaries.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sample.py").write_text(
                "from private.impl import thing\n", encoding="utf-8"
            )
            (root / "a.json").write_text("{}", encoding="utf-8")
            (root / "b.json").write_text('{"drift": true}', encoding="utf-8")
            policy = root / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "forbidden_import_patterns": ["^private\\."],
                        "mirrored_contracts": [
                            {"canonical": "a.json", "mirror": "b.json"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rules = {item["rule"] for item in module.audit(root, policy)["findings"]}
            self.assertEqual(rules, {"forbidden-import", "mirror-hash-mismatch"})

    def test_incomplete_audit_uses_payload_minimized_ids(self):
        module = load_script("audit-incomplete-implementations", "audit_incomplete.py")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sample.py").write_text(
                "def unfinished():\n    pass\n", encoding="utf-8"
            )
            result = module.audit(root)
            self.assertGreaterEqual(result["finding_count"], 1)
            self.assertNotIn("def unfinished", json.dumps(result))
            self.assertEqual(result["unreviewed_count"], result["finding_count"])
            self.assertFalse(result["complete"])
            finding = result["findings"][0]
            registry = root / "reviews.json"
            registry.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                **finding,
                                "classification": "test_fixture",
                                "rationale": "deliberate scanner fixture",
                                "owner": "tests",
                                "review_condition": "review when fixture changes",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            reviewed = module.audit(root, review_registry=registry)
            self.assertTrue(reviewed["complete"])
            self.assertEqual(reviewed["unreviewed_count"], 0)

            # Formatting-only line movement must not invalidate a semantic
            # review whose content-derived ID, path, and rule are unchanged.
            (root / "sample.py").write_text(
                "\n\ndef unfinished():\n    pass\n", encoding="utf-8"
            )
            moved = module.audit(root, review_registry=registry)
            self.assertTrue(moved["complete"])
            self.assertEqual(moved["unreviewed_count"], 0)

    def test_source_auditor_accounts_for_every_file(self):
        module = load_script(
            "audit-source-capabilities", "audit_source_capabilities.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "SKILL.md").write_text(
                "---\nname: example\ndescription: deterministic audit skill\n---\n# Example\n",
                encoding="utf-8",
            )
            result = module.audit(
                root, existing_catalog=None, excluded_names=set(), max_bytes=1_000_000
            )
            self.assertEqual(result["coverage"]["files"], 1)
            self.assertEqual(result["coverage"]["total_accounted_files"], 1)
            self.assertTrue(result["complete"])

    def test_source_auditor_streams_oversize_catalogs_and_accounts_for_exclusions(self):
        module = load_script(
            "audit-source-capabilities", "audit_source_capabilities.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "catalog.jsonl").write_text(
                '{"mechanism":"evidence index with sha256, rollback, and checkpoint"}\n'
                * 40,
                encoding="utf-8",
            )
            generated = root / "build"
            generated.mkdir()
            (generated / "derived.py").write_text(
                "raise NotImplementedError\n", encoding="utf-8"
            )
            result = module.audit(
                root, existing_catalog=None, excluded_names=set(), max_bytes=64
            )
            self.assertEqual(result["coverage"]["files"], 1)
            self.assertEqual(result["coverage"]["excluded_files"], 1)
            self.assertEqual(result["coverage"]["total_accounted_files"], 2)
            self.assertEqual(result["coverage"]["oversize_stream_scanned"], 1)
            self.assertGreater(result["mechanism_counts"]["evidence-integrity"], 0)
            self.assertGreater(result["mechanism_counts"]["reversible-validation"], 0)
            self.assertGreater(
                result["mechanism_counts"]["orchestration-checkpoint"], 0
            )
            self.assertEqual(result["excluded_boundaries"][0]["file_count"], 1)

    def test_source_inventory_reconciler_requires_an_owner_for_every_record(self):
        module = load_script(
            "audit-source-capabilities", "reconcile_source_inventory.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            product = root / "product"
            product.mkdir()
            (product / "owned.txt").write_text("current", encoding="utf-8")
            owner_hash = module.sha256_file(product / "owned.txt")
            inventory = root / "inventory.jsonl"
            inventory.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "source_tree": "old",
                                "path": "owned.txt",
                                "sha256": owner_hash,
                                "bytes": 7,
                            }
                        ),
                        json.dumps(
                            {
                                "source_tree": "old",
                                "path": "missing.txt",
                                "sha256": "a" * 64,
                                "bytes": 1,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            unresolved = module.reconcile(inventory, product, [], None)
            self.assertEqual(unresolved["summary"]["unresolved"], 1)
            rules = root / "rules.json"
            rules.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "superseded",
                                "source_tree": "old",
                                "path_glob": "missing.txt",
                                "disposition": "superseded",
                                "owner_path": "owned.txt",
                                "reason": "covered by the current owner",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            complete = module.reconcile(inventory, product, [], rules)
            self.assertTrue(complete["summary"]["complete"])
            self.assertEqual(complete["summary"]["unresolved"], 0)

    def test_skill_identity_reconciler_accounts_for_specialty_alias_and_vendor(self):
        module = load_script(
            "audit-source-capabilities", "reconcile_skill_identities.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inventory = root / "inventory.jsonl"
            structured = root / "structured.jsonl"
            catalog = root / "catalog.toml"
            specialty = root / "specialty.json"
            aliases = root / "aliases.json"
            source = [
                {
                    "id": "1",
                    "path": "a/SKILL.md",
                    "sha256": "1" * 64,
                    "source_tree": "first",
                },
                {
                    "id": "2",
                    "path": "b/SKILL.md",
                    "sha256": "2" * 64,
                    "source_tree": "first",
                },
                {
                    "id": "3",
                    "path": "c/SKILL.md",
                    "sha256": "3" * 64,
                    "source_tree": "reference-x",
                },
            ]
            inventory.write_text(
                "\n".join(map(json.dumps, source)) + "\n", encoding="utf-8"
            )
            structure = [
                {"id": "1", "structure": {"frontmatter": {"name": "special"}}},
                {"id": "2", "structure": {"frontmatter": {"name": "old-name"}}},
                {"id": "3", "structure": {"frontmatter": {"name": "vendor-only"}}},
            ]
            structured.write_text(
                "\n".join(map(json.dumps, structure)) + "\n", encoding="utf-8"
            )
            catalog.write_text('[[skills]]\nid = "target"\n', encoding="utf-8")
            specialty.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "special",
                                "active_semantic_mappings": ["target"],
                                "delivery_state": "mapped",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            aliases.write_text(
                json.dumps(
                    {
                        "vendor_source_prefixes": ["reference-"],
                        "aliases": [
                            {
                                "source_id": "old-name",
                                "targets": ["target"],
                                "disposition": "merge",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = module.reconcile(
                inventory, structured, catalog, specialty, aliases
            )
            self.assertTrue(report["summary"]["complete"])
            self.assertEqual(report["summary"]["skill_files"], 3)
            self.assertEqual(report["summary"]["unresolved"], 0)

    def test_classified_asset_reconciler_preserves_error_denominators(self):
        module = load_script(
            "audit-source-capabilities", "reconcile_classified_assets.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inventory = root / "inventory.jsonl"
            classified = root / "classified.jsonl"
            policy = root / "policy.json"
            skills = root / "skills.json"
            errors = root / "errors.jsonl"
            inventory.write_text(
                json.dumps({"id": "a", "content_kind": "text"}) + "\n", encoding="utf-8"
            )
            classified.write_text(
                json.dumps(
                    {
                        "id": "a",
                        "class": "builder",
                        "source_tree": "source",
                        "path": "build.py",
                        "sha256": "a" * 64,
                        "probable_domain": "engineering",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            policy.write_text(
                json.dumps(
                    {
                        "terminal_classes": {},
                        "capability_classes": {
                            "builder": {"disposition": "merge", "targets": ["target"]}
                        },
                        "inventory_error_classes": [
                            {
                                "id": "missing",
                                "contains": "FileNotFoundError",
                                "disposition": "broken_pointer",
                            }
                        ],
                        "default_inventory_error_disposition": "unresolved_error",
                    }
                ),
                encoding="utf-8",
            )
            skills.write_text(json.dumps({"records": []}), encoding="utf-8")
            errors.write_text(
                json.dumps(
                    {
                        "path": "gone",
                        "error": "FileNotFoundError: gone",
                        "source_tree": "source",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report = module.reconcile(
                inventory, classified, policy, skills, [], [errors]
            )
            self.assertTrue(report["summary"]["complete"])
            self.assertEqual(report["summary"]["inventory_records"], 1)
            self.assertEqual(report["summary"]["inventory_errors"], 1)
            self.assertEqual(report["summary"]["unresolved_inventory_errors"], 0)

    def test_historical_incomplete_reconciler_requires_a_boundary_rule(self):
        module = load_script(
            "audit-incomplete-implementations", "reconcile_incomplete_findings.py"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "snapshot" / "module.py"
            source.parent.mkdir()
            source.write_text("pass\n", encoding="utf-8")
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "finding_count": 1,
                        "findings": [
                            {
                                "id": "a",
                                "path": "snapshot/module.py",
                                "line": 1,
                                "rule": "python-pass",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            policy = root / "policy.json"
            policy.write_text(json.dumps({"rules": []}), encoding="utf-8")
            self.assertFalse(
                module.reconcile(report, root, policy)["summary"]["complete"]
            )
            policy.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "snapshot",
                                "path_glob": "snapshot/*",
                                "disposition": "historical",
                                "targets": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                module.reconcile(report, root, policy)["summary"]["complete"]
            )


if __name__ == "__main__":
    unittest.main()
