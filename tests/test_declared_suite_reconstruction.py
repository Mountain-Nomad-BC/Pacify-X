import hashlib
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class DeclaredSuiteReconstructionTests(unittest.TestCase):
    def test_build_declared_suite_reconstruction_py_executes_on_a_complete_synthetic_denominator(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            rows = []
            candidates = []
            recoveries = []
            for index in range(260):
                source_count = 1 if index < 259 else 874
                sources = []
                for child in range(source_count):
                    path = f"pack/skill-{index:03d}/artifact-{child:03d}.md"
                    rows.append(
                        {"pack": "01-fixture", "path": path, "artifact_type": "skill"}
                    )
                    sources.append({"path": "manifest:" + path})
                identifier = f"fixture-{index:03d}"
                candidates.append(
                    {
                        "kind": "skill",
                        "id": identifier,
                        "presence": "manifest-only",
                        "sources": sources,
                    }
                )
                recoveries.append(
                    {
                        "kind": "skill",
                        "source_id": identifier,
                        "canonical_owner": "audit-source-capabilities",
                    }
                )
            missing = temp / "missing.csv"
            with missing.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=("pack", "path", "artifact_type")
                )
                writer.writeheader()
                writer.writerows(rows)
            (temp / "candidates.json").write_text(
                json.dumps({"candidates": candidates}), encoding="utf-8"
            )
            (temp / "recovery.json").write_text(
                json.dumps({"records": recoveries}), encoding="utf-8"
            )
            (temp / "exact.json").write_text(
                json.dumps({"records": []}), encoding="utf-8"
            )
            output = temp / "ledger.json"
            script = (
                ROOT
                / ".px/skills/audit-source-capabilities/scripts/build_declared_suite_reconstruction.py"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--missing-csv",
                    str(missing),
                    "--candidates",
                    str(temp / "candidates.json"),
                    "--recovery-map",
                    str(temp / "recovery.json"),
                    "--exact-recovery",
                    str(temp / "exact.json"),
                    "--output-json",
                    str(output),
                    "--output-markdown",
                    str(temp / "plan.md"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            ledger = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(ledger["summary"]["assigned_source_paths"], 1133)
            self.assertEqual(ledger["summary"]["unassigned_source_paths"], 0)

    def test_current_recovery_map_covers_every_declared_outcome_once(self) -> None:
        recovery = _load("registry/declared_capability_recovery_map.json")
        records = recovery["records"]
        self.assertEqual(recovery["record_count"], len(records))
        self.assertEqual(len(records), 260)
        self.assertEqual(
            len({(record["kind"], record["source_id"]) for record in records}), 260
        )
        verified = [
            record
            for record in records
            if record["coverage_state"] == "authoritative_implementation_verified"
        ]
        rejected = [
            record
            for record in records
            if record["coverage_state"] == "current_canonical_owner_selected"
        ]
        self.assertEqual(len(verified), 257)
        self.assertEqual(len(rejected), 3)
        self.assertTrue(
            all(
                record["source_body_state"] == "exact_authoritative_recovery"
                for record in verified
            )
        )
        for record in verified:
            package = ROOT / record["owner_package"]
            self.assertTrue(package.is_file(), record["source_id"])
            self.assertTrue(record["owner_body_sha256"], record["source_id"])

    def test_reconstruction_cards_are_closed_and_hash_bound_to_current_owners(
        self,
    ) -> None:
        progress = _load("evidence/declared-suite/reconstruction-progress.json")
        self.assertEqual(progress["status"], "complete")
        self.assertEqual(
            progress["summary"],
            {
                "errors": [],
                "open_cards": 0,
                "pending_final_evidence_cards": 0,
                "total_cards": 375,
                "valid": True,
                "verified_cards": 375,
            },
        )
        recovery = _load("registry/declared_capability_recovery_map.json")
        for record in recovery["records"]:
            package = _load(record["owner_package"])
            body = ROOT / package["body"]
            self.assertTrue(body.is_file(), record["source_id"])
            self.assertEqual(
                hashlib.sha256(body.read_bytes()).hexdigest(), package["body_sha256"]
            )


if __name__ == "__main__":
    unittest.main()
