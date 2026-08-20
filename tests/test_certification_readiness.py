from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from runtime.certification_readiness import (
    SCHEMA_VERSION,
    assess_certification_readiness,
    version_satisfies,
)
from runtime.cli import main as cli_main
from runtime.contracts import validate_instance


ROOT = Path(__file__).parents[1]


class CertificationReadinessTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        engine = root / "engine"
        extension = root / "extension"
        (engine / "runtime").mkdir(parents=True)
        (engine / "registry").mkdir()
        extension.mkdir()
        (engine / "pyproject.toml").write_text(
            """[project]
name = "fixture-engine"
version = "0.6.3"
requires-python = ">=3.11,<3.15"

[project.optional-dependencies]
build = ["build==1.5.0"]
release = ["build==1.5.0"]
""",
            encoding="utf-8",
        )
        (engine / "runtime" / "cli.py").write_text("", encoding="utf-8")
        (engine / "registry" / "capability_map.json").write_text(
            "{}\n", encoding="utf-8"
        )
        package = {
            "name": "fixture-extension",
            "version": "1.0.0",
            "engines": {"vscode": "^1.132.0"},
            "dependencies": {"zod": "4.4.3"},
            "devDependencies": {"playwright-core": "1.62.1"},
        }
        lock = {
            "name": "fixture-extension",
            "version": "1.0.0",
            "lockfileVersion": 3,
            "packages": {
                "": dict(package),
                "node_modules/playwright-core": {
                    "version": "1.62.1",
                    "engines": {"node": ">=20"},
                },
            },
        }
        (extension / "package.json").write_text(json.dumps(package), encoding="utf-8")
        (extension / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        for name, version in {
            "zod": "4.4.3",
            "playwright-core": "1.62.1",
        }.items():
            installed = extension / "node_modules" / name
            installed.mkdir(parents=True)
            (installed / "package.json").write_text(
                json.dumps({"name": name, "version": version}), encoding="utf-8"
            )
        return engine, extension

    @staticmethod
    def _resolve(
        requested: str | None,
        names: tuple[str, ...],
        absolute_candidates: tuple[Path, ...] = (),
    ) -> Path:
        del absolute_candidates
        return Path("/admitted-tools") / (requested or names[0])

    @staticmethod
    def _probe(
        executable: Path,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float = 8.0,
    ) -> dict[str, object]:
        del cwd, timeout_seconds
        if "-m" in arguments:
            output = json.dumps({"valid": True, "active_count": 1, "errors": []})
        elif "-c" in arguments:
            output = "1.5.0"
        else:
            versions = {
                "python3": "Python 3.14.5",
                "node": "v24.16.0",
                "npm": "11.13.0",
                "msedge": "Microsoft Edge 132.0.0.0",
                "code": "1.132.0\nfixture",
            }
            output = versions[executable.name]
        return {"ok": True, "exit_code": 0, "output": output, "diagnostic": ""}

    def test_ready_fixture_covers_every_required_prerequisite_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine, extension = self._fixture(Path(directory))
            with (
                mock.patch(
                    "runtime.certification_readiness._resolve_executable",
                    side_effect=self._resolve,
                ),
                mock.patch(
                    "runtime.certification_readiness._run_probe",
                    side_effect=self._probe,
                ),
            ):
                result = assess_certification_readiness(
                    engine, extension, python="python3"
                )
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["classification"], "ready")
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["summary"], {"required": 8, "ready": 8, "unready": 0})
        self.assertEqual(
            {item["id"] for item in result["prerequisites"]},
            {
                "python",
                "python-build",
                "node",
                "npm",
                "node-package-lock",
                "browser",
                "vscode",
                "engine",
            },
        )
        validate_instance(
            result, ROOT / "contracts" / "certification-readiness.schema.json"
        )

    def test_missing_browser_is_environment_unready_and_never_skipped(self) -> None:
        def resolve(
            requested: str | None,
            names: tuple[str, ...],
            absolute_candidates: tuple[Path, ...] = (),
        ) -> Path | None:
            if names[0] == "msedge":
                return None
            return self._resolve(requested, names, absolute_candidates)

        with tempfile.TemporaryDirectory() as directory:
            engine, extension = self._fixture(Path(directory))
            with (
                mock.patch(
                    "runtime.certification_readiness._resolve_executable",
                    side_effect=resolve,
                ),
                mock.patch(
                    "runtime.certification_readiness._run_probe",
                    side_effect=self._probe,
                ),
            ):
                result = assess_certification_readiness(
                    engine, extension, python="python3"
                )
        browser = next(
            item for item in result["prerequisites"] if item["id"] == "browser"
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["classification"], "environment-unready")
        self.assertEqual(browser["status"], "missing")
        self.assertNotIn("skip", json.dumps(result).casefold())
        validate_instance(
            result, ROOT / "contracts" / "certification-readiness.schema.json"
        )

    def test_lock_drift_and_floating_direct_dependency_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine, extension = self._fixture(Path(directory))
            package_path = extension / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["dependencies"]["zod"] = "^4.4.3"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with (
                mock.patch(
                    "runtime.certification_readiness._resolve_executable",
                    side_effect=self._resolve,
                ),
                mock.patch(
                    "runtime.certification_readiness._run_probe",
                    side_effect=self._probe,
                ),
            ):
                result = assess_certification_readiness(
                    engine, extension, python="python3"
                )
        lock = next(
            item
            for item in result["prerequisites"]
            if item["id"] == "node-package-lock"
        )
        self.assertEqual(result["classification"], "environment-unready")
        self.assertEqual(lock["status"], "invalid-configuration")
        self.assertIn("differs", lock["diagnostic"])
        self.assertIn("not exact-pinned", lock["diagnostic"])

    def test_supported_version_constraints_are_bounded_and_fail_closed(self) -> None:
        self.assertTrue(version_satisfies("v24.16.0", ">=18 >=20"))
        self.assertTrue(version_satisfies("v24.16.0", ">= 14"))
        self.assertTrue(version_satisfies("1.132.1", "^1.132.0"))
        self.assertFalse(version_satisfies("2.0.0", "^1.132.0"))
        self.assertTrue(version_satisfies("3.14.5", ">=3.11 <3.15"))
        with self.assertRaisesRegex(ValueError, "unsupported version constraint"):
            version_satisfies("1.0.0", "latest")

    def test_cli_returns_nonzero_environment_unready_report(self) -> None:
        report = {
            "schema_version": SCHEMA_VERSION,
            "classification": "environment-unready",
            "valid": False,
            "errors": ["browser: required executable was not found"],
        }
        stream = io.StringIO()
        with (
            mock.patch(
                "runtime.certification_readiness.assess_certification_readiness",
                return_value=report,
            ),
            contextlib.redirect_stdout(stream),
        ):
            exit_code = cli_main(
                [
                    "--root",
                    str(ROOT),
                    "release",
                    "readiness",
                    "--extension-root",
                    str(ROOT),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            json.loads(stream.getvalue())["classification"], "environment-unready"
        )


if __name__ == "__main__":
    unittest.main()
