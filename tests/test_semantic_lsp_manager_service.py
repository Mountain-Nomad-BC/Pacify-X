import sys
import pytest

from runtime.semantic_lsp_manager import LanguageServerUnavailable, LspClientManager
from runtime.semantic_lsp_service import SemanticLanguageService
from tests.semantic_lsp_test_support import FAKE_SERVER


def _project(root):
    (root / "a.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
    (root / "b.py").write_text("from a import Alpha\nvalue = Alpha()\n", encoding="utf-8")


def test_manager_reuses_one_client_per_project_adapter(tmp_path):
    manager = LspClientManager(max_clients=1, allow_launch_overrides=True)
    argv = (sys.executable, str(FAKE_SERVER))
    one = manager.open(tmp_path, "pyright", argv=argv)
    two = manager.open(tmp_path, "pyright", argv=argv)
    assert one is two
    manager.close_all()


def test_manager_never_auto_installs_missing_server(tmp_path, monkeypatch):
    manager = LspClientManager()
    adapter = manager.registry.get("pyright")
    monkeypatch.setattr(type(adapter), "discover_argv", lambda self, environment=None: ())
    with pytest.raises(LanguageServerUnavailable, match="never auto-installs"):
        manager.open(tmp_path, "pyright")


def test_service_preview_and_write_gate(tmp_path):
    _project(tmp_path)
    manager = LspClientManager(allow_launch_overrides=True)
    service = SemanticLanguageService(manager=manager, allow_writes=False)
    argv = (sys.executable, str(FAKE_SERVER))
    try:
        preview = service.rename(tmp_path, "pyright", "b.py", 1, 9, "Beta", argv=argv)
        assert preview["written"] is False
        assert "Alpha" in (tmp_path / "a.py").read_text()
        with pytest.raises(PermissionError):
            service.rename(tmp_path, "pyright", "b.py", 1, 9, "Beta", write=True, argv=argv)
    finally:
        service.close_all()


def test_service_explicit_write_applies_server_plan(tmp_path):
    _project(tmp_path)
    manager = LspClientManager(allow_launch_overrides=True)
    service = SemanticLanguageService(manager=manager, allow_writes=True)
    argv = (sys.executable, str(FAKE_SERVER))
    try:
        result = service.rename(tmp_path, "pyright", "b.py", 1, 9, "Beta", write=True, argv=argv)
        assert result["written"] is True
        assert "class Beta" in (tmp_path / "a.py").read_text()
        assert "Beta()" in (tmp_path / "b.py").read_text()
    finally:
        service.close_all()


def test_manager_rejects_untrusted_launch_overrides_by_default(tmp_path):
    manager = LspClientManager()
    argv = (sys.executable, str(FAKE_SERVER))
    with pytest.raises(LanguageServerUnavailable, match="trusted launch authority"):
        manager.open(tmp_path, "pyright", argv=argv)


def test_manager_rejects_reuse_under_different_configuration(tmp_path):
    manager = LspClientManager(allow_launch_overrides=True)
    argv = (sys.executable, str(FAKE_SERVER))
    try:
        manager.open(tmp_path, "pyright", argv=argv, configuration={"python": {"analysis": {"mode": "strict"}}})
        with pytest.raises(LanguageServerUnavailable, match="different launch/configuration authority"):
            manager.open(tmp_path, "pyright", argv=argv, configuration={})
    finally:
        manager.close_all()
