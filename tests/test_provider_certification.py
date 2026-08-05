from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from runtime.memory_fabric import ProviderIsolationConfig
from runtime.provider_certification import (
    ProviderOperationError,
    run_provider_isolation_suite,
)


class FakeProvider:
    stores: dict[str, dict[str, dict[str, object]]] = {}

    def __init__(self, config: ProviderIsolationConfig) -> None:
        self.namespace = config.database_namespace
        self.store = self.stores.setdefault(self.namespace, {})
        self.fail_next = set()
        self.logs = []

    def put(self, key: str, value: str, *, created_by: str) -> None:
        self.store[key] = {
            "value": value,
            "created_by": created_by,
            "superseded": False,
        }

    def get(self, key: str):
        return self.store.get(key)

    def search(self, query: str):
        if "search" in self.fail_next:
            self.fail_next.remove("search")
            try:
                raise RuntimeError("backend down")
            except RuntimeError as cause:
                raise ProviderOperationError(
                    "search", "backend_unavailable", "provider search failed"
                ) from cause
        return tuple(
            item
            for item in self.store.values()
            if not item["superseded"]
            and query.casefold() in str(item["value"]).casefold()
        )

    def prompt_log(self):
        return tuple(self.logs)

    def correct(self, key: str, value: str, *, created_by: str) -> None:
        if key in self.store:
            self.store[key]["superseded"] = True
        self.store[key + "-correction"] = {
            "value": value,
            "created_by": created_by,
            "superseded": False,
        }

    def inject_failure(self, operation: str) -> None:
        self.fail_next.add(operation)


class ProviderCertificationTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeProvider.stores = {}

    def test_certificate_is_based_on_executed_isolation_probes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ProviderIsolationConfig(
                "prj", root / "provider", "db-prj", "idx-prj", "proc-prj", False
            )
            decision, certificate = run_provider_isolation_suite(
                FakeProvider,
                config,
                provider_id="fake",
                provider_version="1",
                evidence_root=root / "evidence",
            )
            self.assertEqual(decision.decision, "certified_accelerator")
            self.assertTrue(all(item.passed for item in certificate.tests))
            self.assertEqual(len(certificate.tests), 7)
            self.assertTrue(certificate.evidence_refs)

    def test_shared_process_is_rejected_before_probe_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ProviderIsolationConfig(
                "prj", Path(directory), "db", "idx", "proc", True
            )
            with self.assertRaisesRegex(ValueError, "isolated"):
                run_provider_isolation_suite(
                    FakeProvider, config, provider_id="fake", provider_version="1"
                )

    def test_unrelated_exception_cannot_satisfy_backend_failure_probe(self) -> None:
        class WrongFailureProvider(FakeProvider):
            def search(self, query: str):
                if "search" in self.fail_next:
                    self.fail_next.remove("search")
                    raise KeyError("unrelated failure")
                return super().search(query)

        with tempfile.TemporaryDirectory() as directory:
            config = ProviderIsolationConfig(
                "prj", Path(directory), "db", "idx", "proc", False
            )
            decision, certificate = run_provider_isolation_suite(
                WrongFailureProvider, config, provider_id="wrong", provider_version="1"
            )
            self.assertEqual(decision.decision, "disabled")
            result = next(
                item
                for item in certificate.tests
                if item.name == "backend_errors_propagated"
            )
            self.assertFalse(result.passed)
            self.assertEqual(result.error_code, "KeyError")


if __name__ == "__main__":
    unittest.main()
