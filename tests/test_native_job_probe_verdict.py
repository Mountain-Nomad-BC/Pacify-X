"""A result label cannot substitute for retained operating evidence."""
import pytest
from tests import test_native_job_operating_probe as owner


@pytest.mark.parametrize("payload", [{}, {"passed": True},
    {"schema_version": "px.native-job-operating-proof/1.0", "passed": True}])
def test_incomplete_probe_verdict_cannot_satisfy_operating_gate(monkeypatch, payload):
    monkeypatch.setattr(owner.probe, "run_probe", lambda: payload)
    with pytest.raises(AssertionError):
        owner.test_native_job_containment_operating_probe()


def test_unsupported_host_cannot_be_a_skipped_success(monkeypatch):
    monkeypatch.setattr(owner.sys, "platform", "unsupported-probe-fixture")
    with pytest.raises(pytest.fail.Exception, match="unavailable"):
        owner.test_native_job_containment_operating_probe()
