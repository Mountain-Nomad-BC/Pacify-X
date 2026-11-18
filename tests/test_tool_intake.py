import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.commissioning import commission
from runtime.engineering_lifecycle import lifecycle_status
from runtime.tool_intake import (
    execute_scanner,
    record_tool_intake,
    scan_project_tooling,
)
import subprocess


ROOT = Path(__file__).resolve().parents[1]


class ToolIntakeTests(unittest.TestCase):
    def test_inventory_is_fail_closed_without_license_scanner_and_approval(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "package.json").write_text(
                json.dumps({"scripts": {"postinstall": "curl bad"}}), encoding="utf-8"
            )
            result = scan_project_tooling(project, ROOT)
        self.assertEqual(result["decision"], "quarantine")
        self.assertFalse(result["execution_allowed"])
        self.assertTrue(result["components"][0]["malicious_indicators"])

    def test_record_is_versioned_and_advances_lifecycle_without_admitting_tools(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            result = record_tool_intake(project, ROOT, apply=True)
            # This test owns tool-intake advancement, not the current source
            # registry's generated-projection freshness (gated separately).
            with patch("runtime.engineering_lifecycle.validate_registry",
                       return_value={"valid": True, "errors": []}):
                status = lifecycle_status(ROOT, project)
        self.assertTrue(result["applied"])
        self.assertEqual(result["decision"], "no_external_tooling")
        self.assertEqual(status["next_stage"], "architecture-and-planning")

    def test_scanner_execution_requires_separate_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PermissionError):
                scan_project_tooling(Path(directory), ROOT, execute_scanners=True)

    def test_scanner_path_shadowing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scanner = root / "scanner"
            scanner.write_text("x", encoding="utf-8")
            with self.assertRaises(PermissionError):
                execute_scanner(
                    ["scanner"],
                    project=root,
                    approved_executable=scanner,
                    corpus_digest="a" * 64,
                    network_allowed=True,
                    network_isolation_enforced=False,
                )

    def test_scanner_environment_is_scrubbed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scanner = root / "scanner"
            scanner.write_text("x", encoding="utf-8")
            captured = {}

            def runner(*args, **kwargs):
                captured.update(kwargs["env"])
                return subprocess.CompletedProcess(args[0], 0, "{}", "")

            execute_scanner(
                [str(scanner)],
                project=root,
                approved_executable=scanner,
                corpus_digest="a" * 64,
                network_allowed=True,
                network_isolation_enforced=False,
                runner=runner,
            )
            self.assertNotIn("SECRET", captured)
            self.assertNotIn("HOME", captured)
            self.assertEqual(captured["ENGINEERING_BOOTSTRAP_NETWORK"], "allow")

    def test_scanner_result_is_bound_to_input_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scanner = root / "scanner"
            scanner.write_text("x", encoding="utf-8")
            result = execute_scanner(
                [str(scanner)],
                project=root,
                approved_executable=scanner,
                corpus_digest="b" * 64,
                network_allowed=True,
                runner=lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "{}", ""),
            )
            self.assertEqual(result["input_corpus_sha256"], "b" * 64)

    def test_scanner_timeout_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scanner = root / "scanner"
            scanner.write_text("x", encoding="utf-8")
            result = execute_scanner(
                [str(scanner)],
                project=root,
                approved_executable=scanner,
                corpus_digest="c" * 64,
                network_allowed=True,
                runner=lambda *a, **k: (_ for _ in ()).throw(
                    subprocess.TimeoutExpired(a[0], 1)
                ),
            )
            self.assertEqual(result["status"], "timeout")

    def test_scanner_network_requires_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scanner = root / "scanner"
            scanner.write_text("x", encoding="utf-8")
            with self.assertRaises(PermissionError):
                execute_scanner(
                    [str(scanner)],
                    project=root,
                    approved_executable=scanner,
                    corpus_digest="d" * 64,
                )
            seen = {}
            execute_scanner(
                [str(scanner)],
                project=root,
                approved_executable=scanner,
                corpus_digest="d" * 64,
                network_allowed=True,
                network_isolation_enforced=False,
                runner=lambda *a, **k: (
                    seen.update(k["env"])
                    or subprocess.CompletedProcess(a[0], 0, "{}", "")
                ),
            )
            self.assertEqual(seen["ENGINEERING_BOOTSTRAP_NETWORK"], "allow")


if __name__ == "__main__":
    unittest.main()

import pytest


@pytest.mark.parametrize('allowed,enforced', [
    (False, True), (False, 'yes'), (False, 1),
    (0, False), (1, False), ('false', False), ([], False), ({}, False),
    (True, True), (False, False),
])
def test_scanner_caller_flags_cannot_impersonate_native_isolation(tmp_path, allowed, enforced):
    scanner = tmp_path / 'inert-scanner.exe'
    scanner.write_bytes(b'Never executed; counting runner only')
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, 'fixture-scanner 1.0' if argv[-1] == '--version' else '{}', '')
    with pytest.raises(PermissionError):
        execute_scanner([str(scanner), '--scan'], project=tmp_path,
            approved_executable=scanner, corpus_digest='a' * 64,
            network_allowed=allowed, network_isolation_enforced=enforced, runner=runner)
    assert calls == []


@pytest.mark.parametrize('allowed,enforced', [(0, False), (False, True), (False, False), (True, True)])
def test_scanner_public_entry_checks_network_contract_before_inventory(tmp_path, monkeypatch, allowed, enforced):
    calls = []
    def inventory(_):
        calls.append('inventory')
        raise AssertionError('Unaccepted scanner policy reached inventory')
    monkeypatch.setattr('runtime.tool_intake._inventory', inventory)
    with pytest.raises(PermissionError):
        scan_project_tooling(tmp_path, ROOT, execute_scanners=True, scanner_approval=True,
            scanner_network_allowed=allowed, scanner_network_isolation_enforced=enforced)
    assert calls == []
