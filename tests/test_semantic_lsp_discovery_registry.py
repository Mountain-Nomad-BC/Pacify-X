import os
from pathlib import Path

from runtime.semantic_lsp_adapters import POWERSHELL, TYPESCRIPT
from runtime.semantic_lsp_discovery import discover_executables
from runtime.semantic_lsp_registry import LspAdapterRegistry


def test_discovery_honors_supplied_path(tmp_path):
    exe = tmp_path / ("fake.exe" if os.name == "nt" else "fake")
    exe.write_text("x", encoding="utf-8")
    exe.chmod(0o755)
    found = discover_executables((exe.name,), environment={"PATH": str(tmp_path)})
    assert found and Path(found[0].path) == exe.resolve()


def test_typescript_adapter_has_correct_language_ids():
    assert TYPESCRIPT.language_id_for_path("src/a.tsx") == "typescriptreact"
    assert TYPESCRIPT.language_id_for_path("src/a.jsx") == "javascriptreact"


def test_registry_resolves_suffixes():
    registry = LspAdapterRegistry()
    assert registry.for_path("x.py").key == "pyright"
    assert registry.for_path("x.ps1").key == "powershell-editor-services"


def test_powershell_editor_services_argv_is_complete_and_side_effect_free(tmp_path):
    shell = tmp_path / ("pwsh.exe" if os.name == "nt" else "pwsh")
    shell.write_text("fake", encoding="utf-8")
    start_script = tmp_path / "Start-EditorServices.ps1"
    start_script.write_text("# fake", encoding="utf-8")
    bundled = tmp_path / "modules"
    env = {
        "PATH": "",
        "PX_POWERSHELL_EXECUTABLE": str(shell),
        "PX_POWERSHELL_EDITOR_SERVICES_START_SCRIPT": str(start_script),
        "PX_POWERSHELL_EDITOR_SERVICES_BUNDLED_MODULES_PATH": str(bundled),
        "PX_POWERSHELL_EDITOR_SERVICES_LOG_PATH": str(tmp_path / "pses.log"),
        "PX_POWERSHELL_EDITOR_SERVICES_SESSION_DETAILS_PATH": str(tmp_path / "session.json"),
    }
    argv = POWERSHELL.discover_argv(environment=env)
    assert len(argv) == 1
    command = argv[0]
    assert command[:5] == (str(shell.resolve()), "-NoLogo", "-NoProfile", "-File", str(start_script.resolve()))
    assert "-Stdio" in command
    assert command[command.index("-BundledModulesPath") + 1] == str(bundled.resolve())
    assert command[command.index("-SessionDetailsPath") + 1] == str((tmp_path / "session.json").resolve())
    assert not (tmp_path / "pses.log").exists()
    assert not (tmp_path / "session.json").exists()
