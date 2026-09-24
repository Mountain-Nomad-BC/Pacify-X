"""PX-native language-server adapter declarations.

Adapters describe known executables and language IDs only.  Wave 2 never installs
language servers, invokes a shell, or downloads dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Mapping, Protocol

from .semantic_lsp_discovery import discover_executables


class Adapter(Protocol):
    key: str
    language: str
    suffixes: tuple[str, ...]
    def discover_argv(self, *, environment: Mapping[str, str] | None = None) -> tuple[tuple[str, ...], ...]: ...
    def language_id_for_path(self, relative_path: str) -> str: ...


@dataclass(frozen=True, slots=True)
class LanguageServerAdapter:
    key: str
    language: str
    suffixes: tuple[str, ...]
    executable_names: tuple[str, ...]
    override_variable: str
    stdio_args: tuple[str, ...]
    language_ids: Mapping[str, str]

    def discover_argv(self, *, environment: Mapping[str, str] | None = None) -> tuple[tuple[str, ...], ...]:
        candidates = discover_executables(
            self.executable_names,
            environment=environment,
            override_variable=self.override_variable,
        )
        return tuple((item.path, *self.stdio_args) for item in candidates)

    def language_id_for_path(self, relative_path: str) -> str:
        suffix = PurePosixPath(relative_path).suffix.casefold()
        return self.language_ids.get(suffix, self.language)


PYRIGHT = LanguageServerAdapter(
    key="pyright",
    language="python",
    suffixes=(".py", ".pyi"),
    executable_names=("pyright-langserver", "basedpyright-langserver"),
    override_variable="PX_PYRIGHT_LANGSERVER",
    stdio_args=("--stdio",),
    language_ids={".py": "python", ".pyi": "python"},
)
TYPESCRIPT = LanguageServerAdapter(
    key="typescript-language-server",
    language="typescript",
    suffixes=(".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"),
    executable_names=("typescript-language-server",),
    override_variable="PX_TYPESCRIPT_LANGSERVER",
    stdio_args=("--stdio",),
    language_ids={
        ".ts": "typescript", ".tsx": "typescriptreact",
        ".js": "javascript", ".jsx": "javascriptreact",
        ".mjs": "javascript", ".cjs": "javascript",
    },
)


@dataclass(frozen=True, slots=True)
class PowerShellEditorServicesAdapter:
    key: str = "powershell-editor-services"
    language: str = "powershell"
    suffixes: tuple[str, ...] = (".ps1", ".psm1", ".psd1")

    def discover_argv(self, *, environment: Mapping[str, str] | None = None) -> tuple[tuple[str, ...], ...]:
        env = dict(os.environ if environment is None else environment)
        script = env.get("PX_POWERSHELL_EDITOR_SERVICES_START_SCRIPT")
        if not script:
            return ()
        script_path = Path(script).expanduser().resolve(strict=False)
        if not script_path.is_file():
            return ()
        shells = discover_executables(
            ("pwsh", "powershell"),
            environment=env,
            override_variable="PX_POWERSHELL_EXECUTABLE",
        )
        key = hashlib.sha256(str(script_path).encode("utf-8")).hexdigest()[:12]
        temp_root = Path(tempfile.gettempdir())
        bundled = Path(
            env.get("PX_POWERSHELL_EDITOR_SERVICES_BUNDLED_MODULES_PATH", str(script_path.parent))
        ).expanduser().resolve(strict=False)
        log_path = Path(
            env.get("PX_POWERSHELL_EDITOR_SERVICES_LOG_PATH", str(temp_root / f"pacify-x-pses-{key}.log"))
        ).expanduser().resolve(strict=False)
        session_path = Path(
            env.get(
                "PX_POWERSHELL_EDITOR_SERVICES_SESSION_DETAILS_PATH",
                str(temp_root / f"pacify-x-pses-{key}-session.json"),
            )
        ).expanduser().resolve(strict=False)
        args = (
            "-NoLogo", "-NoProfile", "-File", str(script_path),
            "-HostName", "PACIFY-X",
            "-HostProfileId", "pacify-x",
            "-HostVersion", "1.0.0",
            "-BundledModulesPath", str(bundled),
            "-LogPath", str(log_path),
            "-LogLevel", "Information",
            "-SessionDetailsPath", str(session_path),
            "-Stdio",
        )
        return tuple((shell.path, *args) for shell in shells)

    def language_id_for_path(self, relative_path: str) -> str:
        return "powershell"


POWERSHELL = PowerShellEditorServicesAdapter()
BUILTIN_ADAPTERS: tuple[Adapter, ...] = (PYRIGHT, TYPESCRIPT, POWERSHELL)
