"""Configuration admission must not silently commission an untrusted host."""
from types import SimpleNamespace

import pytest

from runtime.gremlin.host_configuration import CONFIGURATION_RELATIVE, load_configured_gremlin_runtime


@pytest.mark.parametrize("configuration_present", [False, True])
def test_uncommissioned_host_load_has_no_identity_or_key_effect(tmp_path, monkeypatch, configuration_present):
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    if configuration_present:
        configuration = tmp_path / CONFIGURATION_RELATIVE
        configuration.parent.mkdir(parents=True)
        configuration.write_text('{"authentication":{},"schema_version":"uncommissioned"}', encoding="utf-8")
    def image():
        return {p.relative_to(tmp_path).as_posix():p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    before = image()
    with pytest.raises((FileNotFoundError, ValueError)):
        load_configured_gremlin_runtime(tmp_path, recovery_verifier=SimpleNamespace(verify=lambda *args: None))
    assert image() == before
    assert not (tmp_path / ".engineering-bootstrap/studios").exists()
    assert not (tmp_path / "host-keys").exists()


def test_missing_independent_verifier_cannot_create_host_state(tmp_path):
    with pytest.raises(ValueError, match="independent recovery verifier"):
        load_configured_gremlin_runtime(tmp_path, recovery_verifier=None)
    assert list(tmp_path.iterdir()) == []


def test_host_configuration_uses_bootstrap_project_namespace():
    assert CONFIGURATION_RELATIVE.parts[0] == ".engineering-bootstrap"
