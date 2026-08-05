from __future__ import annotations

import subprocess

import pytest

import runtime.external_toolchain as toolchain


def test_authority_probe_has_stable_feature_level_schema():
    result = toolchain.openssh_authority_status()
    assert set(result) == {
        "executable",
        "present",
        "ed25519_generation",
        "ssh_signature_sign",
        "ssh_signature_verify",
        "authoritative_signing_available",
        "finding_codes",
    }
    assert result["authoritative_signing_available"] == all(
        result[field]
        for field in (
            "ed25519_generation",
            "ssh_signature_sign",
            "ssh_signature_verify",
        )
    )


def test_missing_openssh_is_actionable_and_basic_probe_does_not_raise(monkeypatch):
    monkeypatch.setattr(toolchain.shutil, "which", lambda _name: None)
    result = toolchain.openssh_authority_status()
    assert not result["authoritative_signing_available"]
    assert result["finding_codes"] == ["SSH_KEYGEN_NOT_FOUND"]
    with pytest.raises(RuntimeError, match="AUTHORITATIVE_SIGNING_UNAVAILABLE"):
        toolchain.require_openssh_authority()


def test_probe_failure_is_a_finding_not_a_startup_failure(monkeypatch):
    monkeypatch.setattr(toolchain.shutil, "which", lambda _name: "ssh-keygen")

    def fail(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ssh-keygen", 20)

    result = toolchain.openssh_authority_status(runner=fail)
    assert result["finding_codes"] == ["SSH_TOOLCHAIN_PROBE_FAILED:TimeoutExpired"]
    assert not result["authoritative_signing_available"]
