"""Native PowerShell syntax observations of exact images; never run source bodies."""
from __future__ import annotations

import base64
import hashlib
import math
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from .input_files import directory_root
from .json_io import decode_json_object
from .resource_lifecycle import ResourceManager, RunState

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_SYMBOLS = 4096
MAX_NAME_CHARS = 512
SCHEMA = "px.powershell-source/1.0"


class PowerShellSourceError(ValueError):
    pass


class PowerShellSyntaxError(PowerShellSourceError):
    pass


class PowerShellBudgetError(PowerShellSourceError):
    pass


class PowerShellUnavailable(PowerShellSourceError):
    pass


def discover_parser() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def parse_powershell_source(root: Path, source: str, *, timeout_seconds: float = 30) -> dict:
    """Parse a bounded Unicode image using native AST, with owned process custody.

    Source is written inside an owned workspace and read once by a fixed parser
    program. Its native byte digest must match the acquired image. No source
    expression, command, declaration, import or top-level body is evaluated.
    """
    root = directory_root(root)
    if type(source) is not str:
        raise TypeError("PowerShell source image must be text")
    raw = source.encode("utf-8", errors="strict")
    if len(raw) > MAX_SOURCE_BYTES:
        raise PowerShellBudgetError("PowerShell source image exceeds byte budget")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30):
        raise ValueError("PowerShell parser timeout must be positive and at most 30 seconds")
    executable = discover_parser()
    if executable is None:
        raise PowerShellUnavailable("Native PowerShell syntax parser is unavailable")
    run = "powershell-source-" + uuid4().hex
    manager = ResourceManager(root / ".agentic_engineering_os_px/resource-lifecycle/ledger.json")
    owned_root = root / ".agentic_engineering_os_px/test-evidence/source-observation"
    owned_root.mkdir(parents=True, exist_ok=True)
    workspace = manager.create_workspace(
        owned_root, project_id="powershell-source", run_id=run,
        lane_id="metadata", creator=__name__, prefix="powershell-",
    )
    image = Path(workspace.path) / "source.txt"
    literal = "'" + str(image).replace("'", "''") + "'"
    # Only this fixed program is executed. The source image is data to ParseInput.
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$raw = [IO.File]::ReadAllBytes(__IMAGE__)
$text = [Text.UTF8Encoding]::new($false, $true).GetString($raw)
$hasher = [Security.Cryptography.SHA256]::Create()
try { $digest = [BitConverter]::ToString($hasher.ComputeHash($raw)).Replace('-', '').ToLowerInvariant() }
finally { $hasher.Dispose() }
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
$symbols = @(); $budget = $false
if (-not $errors.Count) {
    $nodes = @($ast.FindAll({ param($node)
        ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -or
        (($node -is [System.Management.Automation.Language.TypeDefinitionAst]) -and $node.IsClass)
    }, $true))
    if ($nodes.Count -gt __MAX_SYMBOLS__) { $budget = $true }
    else {
        foreach ($node in $nodes) {
            if ($node.Name.Length -gt __MAX_NAME__) { $budget = $true; break }
            $kind = if ($node -is [System.Management.Automation.Language.TypeDefinitionAst]) { 'class' } else { 'function' }
            $symbols += @{name=$node.Name;kind=$kind;line=$node.Extent.StartLineNumber;
                          start_offset=$node.Extent.StartOffset;end_offset=$node.Extent.EndOffset}
        }
    }
}
if ($budget -or $errors.Count) { $symbols = @() }
@{schema_version='px.powershell-source/1.0';parser_version=$PSVersionTable.PSVersion.ToString();
  source_sha256=$digest;symbols=@($symbols);error_ids=@($errors | Select-Object -First 8 | ForEach-Object { $_.ErrorId });
  budget_exhausted=[bool]$budget} | ConvertTo-Json -Depth 5 -Compress
""".replace("__MAX_SYMBOLS__", str(MAX_SYMBOLS)).replace("__MAX_NAME__", str(MAX_NAME_CHARS)).replace("__IMAGE__", literal)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    custody_safe = True
    try:
        image.write_bytes(raw)
        record, process = manager.spawn_owned_process(
            [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=Path(workspace.path), project_id="powershell-source", run_id=run,
            lane_id="metadata", creator=__name__, text=False,
            ownership="supervised", parent_resource_id=workspace.resource_id,
        )
        try:
            stdout, _stderr = process.communicate(timeout=timeout_seconds)
        except BaseException as error:
            cleanup = manager.terminate_owned_process(record.resource_id, graceful_timeout_seconds=1)
            custody_safe = not cleanup.errors
            if not custody_safe:
                raise PowerShellSourceError("PowerShell parser process custody could not close") from error
            if isinstance(error, subprocess.TimeoutExpired):
                raise PowerShellBudgetError("PowerShell syntax parsing exceeded duration budget") from error
            raise
        manager.complete_process(record.resource_id)
        if process.returncode != 0:
            raise PowerShellSourceError("Native PowerShell parser failed; no source metadata published")
        if len(stdout) > MAX_SOURCE_BYTES:
            raise PowerShellBudgetError("PowerShell parser result exceeds byte budget")
        try:
            value = decode_json_object(stdout, max_bytes=MAX_SOURCE_BYTES)
        except ValueError as error:
            raise PowerShellSourceError("Native parser result is not strict bounded JSON") from error
        fields = {"schema_version", "parser_version", "source_sha256", "symbols", "error_ids", "budget_exhausted"}
        if (set(value) != fields or value["schema_version"] != SCHEMA
                or value["source_sha256"] != hashlib.sha256(raw).hexdigest()
                or type(value["budget_exhausted"]) is not bool
                or type(value["symbols"]) is not list or type(value["error_ids"]) is not list
                or type(value["parser_version"]) is not str or not 1 <= len(value["parser_version"]) <= 64):
            raise PowerShellSourceError("Invalid native parser result or source-image binding")
        if value["budget_exhausted"] or len(value["symbols"]) > MAX_SYMBOLS:
            raise PowerShellBudgetError("PowerShell declarations exceed metadata budget")
        if value["error_ids"]:
            raise PowerShellSyntaxError("Native PowerShell syntax errors; whole image rejected")
        maximum_line = source.count("\n") + 1
        maximum_offset = len(source.encode("utf-16-le")) // 2
        for symbol in value["symbols"]:
            if (type(symbol) is not dict or set(symbol) != {"name", "kind", "line", "start_offset", "end_offset"}
                    or type(symbol["name"]) is not str or not 1 <= len(symbol["name"]) <= MAX_NAME_CHARS
                    or "\0" in symbol["name"] or type(symbol["kind"]) is not str
                    or symbol["kind"] not in {"class", "function"}
                    or type(symbol["line"]) is not int or not 1 <= symbol["line"] <= maximum_line
                    or type(symbol["start_offset"]) is not int or type(symbol["end_offset"]) is not int
                    or not 0 <= symbol["start_offset"] < symbol["end_offset"] <= maximum_offset):
                raise PowerShellSourceError("Invalid native declaration geometry")
        value["parser_executable_sha256"] = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        return value
    finally:
        if custody_safe:
            receipt = manager.reclaim_ephemeral_path(workspace.resource_id, reason="Native syntax observation ended")
            if receipt.errors or receipt.resources_failed or receipt.resources_skipped:
                raise PowerShellSourceError("PowerShell parser workspace custody could not close")
        else:
            manager.mark_run_ended(run, RunState.RECOVERABLE, retain_reason="Unresolved parser process custody")
