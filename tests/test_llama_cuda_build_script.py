"""Source-level guards for the optional Windows llama.cpp CUDA build.

These checks deliberately do not download, build, or certify a model runtime.
"""

from pathlib import Path
import re
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "px_build_llama_cuda.ps1"


def test_script_parses_without_running_build():
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        pytest.skip("PowerShell parser unavailable")
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "'" + str(SCRIPT).replace("'", "''") + "', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_requested_ref_is_fetched_checked_out_and_verified_before_build():
    source = SCRIPT.read_text(encoding="utf-8")
    steps = [
        "git status --porcelain --untracked-files=all",
        "git fetch --tags origin -- $LlamaCppRef",
        "git rev-parse --verify 'FETCH_HEAD^{commit}'",
        "git checkout --detach $resolvedCommit",
        "git rev-parse HEAD",
        '$cmakeArgs = @(',
    ]
    positions = [source.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "git remote get-url origin" in source
    assert "if ($LASTEXITCODE -ne 0 -or $headCommit -ne $resolvedCommit)" in source


def test_lock_records_observed_toolchains_not_fixed_versions():
    source = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"\$nvccOutput\s*=.*--version", source)
    assert "Microsoft.VCToolsVersion.default.txt" in source
    assert re.search(r"cuda_toolkit\s*=\s*\$cudaVersion", source)
    assert re.search(r"msvc_toolset\s*=\s*\$msvcVersion", source)
    assert 'cuda_toolkit      = "13.4"' not in source
    assert 'msvc_toolset      = "14.51.36231"' not in source
