"""Conformance test for PX-GAP-0009: one canonical source-boundary owner.

Written to define the requirement. NOT executed in the implementation-first pass.
"""

import unittest

from runtime.source_boundary import (
    AUTHORED,
    CONFORMANCE_CORPUS,
    classify_path,
    conformance_report,
)
from runtime.repository_scope import is_external_environment_relative


class SourceBoundaryConformanceTest(unittest.TestCase):
    def test_corpus_classifications_are_exact(self):
        report = conformance_report()
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["classification_mismatches"], [])
        self.assertEqual(report["delegation_mismatches"], [])

    def test_repository_scope_delegates_to_canonical_owner(self):
        # Every corpus entry must agree between the two mechanisms.
        for path, expected in CONFORMANCE_CORPUS:
            external = is_external_environment_relative(path)
            self.assertEqual(
                external,
                expected != AUTHORED,
                f"{path}: repository_scope disagreed with source_boundary",
            )

    def test_mypy_cache_is_vendored(self):
        self.assertEqual(classify_path(".mypy_cache/3.12/x.json")["classification"], "vendored")

    def test_pytest_and_ruff_cache_are_runtime_state(self):
        self.assertEqual(classify_path(".pytest_cache/v/cache/lastfailed")["classification"], "runtime_state")
        self.assertEqual(classify_path(".ruff_cache/0.1/x")["classification"], "runtime_state")

    def test_vscode_test_is_vendored(self):
        self.assertEqual(classify_path(".vscode-test/vscode/out.js")["classification"], "vendored")

    def test_directory_reference_matches_contents(self):
        self.assertEqual(
            classify_path("extension/node_modules/")["classification"],
            classify_path("extension/node_modules/x.js")["classification"],
        )

    def test_venv_prefix_is_vendored(self):
        self.assertEqual(classify_path(".venv/lib/site.py")["classification"], "vendored")
        self.assertEqual(classify_path(".venv-custom/lib/site.py")["classification"], "vendored")


if __name__ == "__main__":
    unittest.main()