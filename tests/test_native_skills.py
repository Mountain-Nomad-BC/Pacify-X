from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from runtime.native_skills import (
    BACKUP_SCHEMA,
    build_skill_index,
    copy_verified,
    hydrate_skill,
    query_skills,
    restore_backup,
    tree_hash,
    validate_native_packages,
    validate_skill_index,
    verify_backup,
)


class NativeSkillTests(unittest.TestCase):
    def test_backup_is_hash_verified_and_restore_reproduces_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("---\nname: original\ndescription: original\n---\n", encoding="utf-8")
            snapshot = root / "snapshot"
            receipt = copy_verified(source, snapshot / "workspace-original")
            manifest = {
                "schema_version": BACKUP_SCHEMA,
                "sources": [{
                    "id": "workspace-original", "relative_backup": "workspace-original",
                    "file_count": receipt["file_count"], "tree_sha256": receipt["tree_sha256"]
                }]
            }
            (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(verify_backup(snapshot)["valid"])
            restored = root / "restored"
            restore = restore_backup(snapshot, "workspace-original", restored)
            self.assertTrue(restore["restored"])
            self.assertEqual(tree_hash([{**row} for row in receipt["files"]]), restore["tree_sha256"])

    def test_restore_reconstructs_manifest_bound_crlf_bytes_from_git_lf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            backup = snapshot / "workspace-original"
            backup.mkdir(parents=True)
            relative = "skill/SKILL.md"
            checkout_bytes = b"---\nname: original\n---\n"
            custody_bytes = checkout_bytes.replace(b"\n", b"\r\n")
            body = backup / relative
            body.parent.mkdir(parents=True)
            body.write_bytes(checkout_bytes)
            files = [{
                "path": relative,
                "size_bytes": len(custody_bytes),
                "sha256": hashlib.sha256(custody_bytes).hexdigest(),
            }]
            inventory = snapshot / "workspace-original.inventory.json"
            inventory.write_text(json.dumps({"files": files}), encoding="utf-8")
            manifest = {
                "schema_version": BACKUP_SCHEMA,
                "sources": [{
                    "id": "workspace-original",
                    "relative_backup": "workspace-original",
                    "inventory": inventory.name,
                    "inventory_size_bytes": inventory.stat().st_size,
                    "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
                    "file_count": 1,
                    "tree_sha256": tree_hash(files),
                }],
            }
            (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            self.assertTrue(verify_backup(snapshot)["valid"])
            restored = root / "restored"
            receipt = restore_backup(snapshot, "workspace-original", restored)
            self.assertEqual((restored / relative).read_bytes(), custody_bytes)
            self.assertEqual(receipt["tree_sha256"], tree_hash(files))

    def test_default_query_cannot_bleed_vendor_enterprise_or_preserved_domains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".px").mkdir()
            body = root / ".px" / "skills" / "standard" / "SKILL.md"
            body.parent.mkdir(parents=True)
            content = "---\nname: standard\ndescription: deploy model safely\n---\n"
            body.write_text(content, encoding="utf-8")
            records = [
                self._record("standard", "px-standard", ".px/skills/standard/SKILL.md", content, True),
                self._record("microsoft-vendor/deploy", "microsoft-vendor", ".px/vendor/SKILL.md", content, False),
                self._record("ms-enterprise/skill/deploy", "enterprise-restricted", None, None, False),
                self._record("user-preserved/deploy", "user-preserved", ".px/user/SKILL.md", content, False),
            ]
            (root / ".px" / "skill-index.json").write_text(json.dumps(build_skill_index(records)), encoding="utf-8")
            decision = query_skills(root, "deploy model")
            self.assertEqual([row["id"] for row in decision["candidates"]], ["standard"])
            denied = query_skills(root, "deploy", domains=["microsoft-vendor"])
            self.assertEqual(denied["candidates"], [])
            self.assertEqual(denied["denied_domains"], ["microsoft-vendor"])
            admitted = query_skills(root, "deploy", domains=["microsoft-vendor"], grants=["allow-microsoft-vendor"])
            self.assertEqual([row["id"] for row in admitted["candidates"]], ["microsoft-vendor/deploy"])
            self.assertFalse(admitted["candidates"][0]["selection_eligible"])
            with self.assertRaises(PermissionError):
                hydrate_skill(root, "microsoft-vendor/deploy", domains=["microsoft-vendor"], grants=["allow-microsoft-vendor"])

    def test_query_returns_at_most_three_and_hydrates_exactly_one_hash_bound_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = []
            for index in range(6):
                body = root / ".px" / "skills" / f"skill-{index}" / "SKILL.md"
                body.parent.mkdir(parents=True)
                content = f"---\nname: skill-{index}\ndescription: audit runtime {index}\n---\n"
                body.write_text(content, encoding="utf-8")
                records.append(self._record(f"skill-{index}", "px-standard", f".px/skills/skill-{index}/SKILL.md", content, True))
            (root / ".px" / "skill-index.json").write_text(json.dumps(build_skill_index(records)), encoding="utf-8")
            decision = query_skills(root, "audit runtime", limit=99)
            self.assertEqual(len(decision["candidates"]), 3)
            self.assertTrue(all(row["selection_eligible"] for row in decision["candidates"]))
            self.assertEqual(decision["hydrated"], 0)
            hydrated = hydrate_skill(root, decision["candidates"][0]["id"])
            self.assertEqual(hydrated["hydrated_count"], 1)
            self.assertEqual(hydrated["references_loaded"], 0)

    def test_index_derivatives_are_built_from_one_set_and_drift_is_refused(self) -> None:
        records = [
            self._record("one", "px-standard", ".px/skills/one/SKILL.md", "one", True),
            self._record("two", "microsoft-vendor", None, None, False),
        ]
        index = build_skill_index(records)
        self.assertEqual(index["record_count"], 2)
        self.assertEqual(index["counts"]["px-standard"], 1)
        self.assertEqual(index["counts"]["microsoft-vendor"], 1)
        self.assertTrue(validate_skill_index(index)["valid"])
        index["counts"]["px-standard"] = 2
        with self.assertRaises(ValueError, msg="denominator drift must fail closed"):
            validate_skill_index(index)

    def test_live_native_packages_and_domain_index_validate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / ".px" / "skill-index.json").is_file():
            self.skipTest("native migration has not run")
        result = validate_native_packages(root)
        self.assertTrue(result["valid"], result["errors"])
        self.assertLessEqual(result["maximum_candidates"], 3)
        preserved = root / ".px" / "preserved-skills" / "initial"
        if (preserved / "manifest.json").is_file():
            self.assertTrue(verify_backup(preserved)["valid"])

    def test_assurance_and_certification_skills_package_required_local_contracts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        required = {
            "audit-ai-runtime-assurance": ("policies/runtime-assurance-privacy.json",),
            "certify-skeptical-engineering": ("contracts/skeptical-certification.schema.json", "policies/skeptical-certification.json"),
            "quarantine-external-tools": ("contracts/external-tool-intake.schema.json", "policies/external-tool-quarantine.json"),
        }
        for skill_id, paths in required.items():
            package = root / ".px" / "skills" / skill_id
            index = json.loads((package / "resources/index.json").read_text(encoding="utf-8"))
            for relative in paths:
                self.assertIn(relative, index["resources"])
                self.assertTrue((package / relative).is_file(), f"{skill_id}:{relative}")

    def test_codex_visible_tree_is_only_the_bounded_facade_taxonomy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        expected = {
            "px-query-skills", "px-skill", "px-orchestrate", "px-plan", "px-engineer",
            "px-debug-repair", "px-audit", "px-test-verify", "px-research", "px-learn",
            "px-knowledge-memory", "px-security", "px-runtime-environment",
            "px-data-integrations", "px-release", "px-govern",
        }
        actual = {path.name for path in (root / ".agents" / "skills").iterdir() if path.is_dir()}
        self.assertEqual(actual, expected)
        self.assertGreaterEqual(len(actual), 10)
        self.assertLessEqual(len(actual), 20)
        self.assertEqual(len(list((root / ".agents" / "skills").glob("*/SKILL.md"))), len(expected))
        self.assertTrue(all("TODO" not in path.read_text(encoding="utf-8") for path in (root / ".agents" / "skills").glob("*/SKILL.md")))

    def test_live_workspace_original_backup_restores_exactly(self) -> None:
        root = Path(__file__).resolve().parents[1]
        snapshot = root / ".px" / "preserved-skills" / "initial"
        if not snapshot.is_dir():
            self.skipTest("native migration has not run")
        with tempfile.TemporaryDirectory() as directory:
            receipt = restore_backup(snapshot, "workspace-original", Path(directory) / "restored")
            manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
            expected = next(row["tree_sha256"] for row in manifest["sources"] if row["id"] == "workspace-original")
            self.assertEqual(receipt["tree_sha256"], expected)

    @staticmethod
    def _record(skill_id: str, domain: str, body: str | None, content: str | None, native: bool) -> dict[str, object]:
        status = "active" if domain == "px-standard" else "preserved-not-admitted"
        return {
            "id": skill_id, "description": "deploy model audit runtime", "tags": ["deploy", "audit"],
            "domain": domain, "origin": "test", "native": native, "adapted": False,
            "default_eligible": domain == "px-standard", "body_available": body is not None,
            "body": body, "body_sha256": hashlib.sha256((content or "").encode()).hexdigest() if content is not None else None,
            "package_root": str(Path(body).parent) if body else None, "status": status, "admission": status,
        }


if __name__ == "__main__":
    unittest.main()
