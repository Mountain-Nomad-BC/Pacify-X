# PX canonical llama.cpp CUDA build (adapted from Pacify-X Unified Model Fabric reference).
# One governed llama.cpp build reused by all GGUF workers (router mode).
[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:USERPROFILE\.px",
    [string]$LlamaCppRef = "master",
    [string]$CudaArchitectures = "89",
    [string]$VisualStudioRoot = "",
    [string]$CudaRootParam = "",
    [switch]$PortableCudaBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Ensure a complete system PATH so nested cmd/compilers resolve regardless of caller environment.
$env:Path = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem;$env:SystemRoot\System32\WindowsPowerShell\v1.0;" + $env:Path

# Tool locations are discovered, not hardcoded to one machine:
#   - VS Build Tools via vswhere (or -VisualStudioRoot)
#   - CUDA toolkit via CUDA_PATH / -CudaRoot
$vsRoot = if ($VisualStudioRoot) { $VisualStudioRoot }
    elseif ($env:PX_VS_BUILD_TOOLS) { $env:PX_VS_BUILD_TOOLS }
    else {
        $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
        if (Test-Path $vswhere) {
            $found = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1
            if ($found) { $found.Trim() } else { "$env:ProgramFiles(x86)\Microsoft Visual Studio\BuildTools" }
        } else { "$env:ProgramFiles(x86)\Microsoft Visual Studio\BuildTools" }
    }
$cudaRoot = if ($CudaRootParam) { $CudaRootParam }
    elseif ($env:CUDA_PATH) { $env:CUDA_PATH }
    else { "$env:ProgramFiles\NVIDIA GPU Computing Toolkit\CUDA" }
$vcvars = Join-Path $vsRoot "VC\Auxiliary\Build\vcvars64.bat"
$cmake = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$ninja = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"

foreach ($p in @($vcvars, $cmake, $ninja, (Join-Path $cudaRoot "bin\nvcc.exe"))) {
    if (-not (Test-Path $p)) { throw "Required tool not found: $p" }
}
$nvcc = Join-Path $cudaRoot "bin\nvcc.exe"
$nvccOutput = (& $nvcc --version 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw "nvcc --version failed with exit code $LASTEXITCODE" }
$cudaVersionMatch = [regex]::Match($nvccOutput, '\brelease\s+([0-9]+(?:\.[0-9]+)+)')
if (-not $cudaVersionMatch.Success) { throw "Could not identify the installed CUDA toolkit version" }
$cudaVersion = $cudaVersionMatch.Groups[1].Value
$msvcVersionPath = Join-Path $vsRoot "VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt"
if (-not (Test-Path $msvcVersionPath -PathType Leaf)) { throw "MSVC default toolset version file not found: $msvcVersionPath" }
$msvcVersion = (Get-Content -LiteralPath $msvcVersionPath -TotalCount 1).Trim()
if ($msvcVersion -notmatch '^\d+\.\d+\.\d+(?:\.\d+)?$') { throw "Invalid MSVC toolset version: $msvcVersion" }
if ($LlamaCppRef -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$' -or $LlamaCppRef.Contains('..')) {
    throw "LlamaCppRef must be a single Git ref or commit identifier"
}

$runtimeRoot = Join-Path $InstallRoot "runtime"
$repo = Join-Path $runtimeRoot "llama.cpp"
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

if (-not (Test-Path (Join-Path $repo ".git"))) {
    & git clone https://github.com/ggml-org/llama.cpp $repo
    if ($LASTEXITCODE -ne 0) { throw "llama.cpp clone failed with exit code $LASTEXITCODE" }
}

Push-Location $repo
try {
    $topLevel = (& git rev-parse --show-toplevel).Trim()
    if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath($topLevel) -ne [IO.Path]::GetFullPath($repo)) {
        throw "llama.cpp checkout is not the expected repository: $repo"
    }
    $origin = (& git remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or $origin -notin @('https://github.com/ggml-org/llama.cpp', 'https://github.com/ggml-org/llama.cpp.git')) {
        throw "llama.cpp origin is not the expected upstream: $origin"
    }
    $dirty = & git status --porcelain --untracked-files=all
    if ($LASTEXITCODE -ne 0 -or $dirty) { throw "llama.cpp checkout has local changes; refusing to switch refs" }
    & git fetch --tags origin -- $LlamaCppRef
    if ($LASTEXITCODE -ne 0) { throw "Could not fetch requested llama.cpp ref: $LlamaCppRef" }
    $resolvedCommit = (& git rev-parse --verify 'FETCH_HEAD^{commit}').Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedCommit -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Requested llama.cpp ref did not resolve to a commit: $LlamaCppRef"
    }
    & git checkout --detach $resolvedCommit
    if ($LASTEXITCODE -ne 0) { throw "Could not check out requested llama.cpp commit: $resolvedCommit" }
    $headCommit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $headCommit -ne $resolvedCommit) { throw "Checked-out llama.cpp commit differs from requested ref" }

    $cmakeArgs = @("-S", ".", "-B", "build", "-G", "Ninja", "-DGGML_CUDA=ON", "-DCMAKE_BUILD_TYPE=Release")
    if ($PortableCudaBuild) {
        $cmakeArgs += "-DGGML_NATIVE=OFF"
    } elseif ($CudaArchitectures) {
        $cmakeArgs += "-DCMAKE_CUDA_ARCHITECTURES=$CudaArchitectures"
    }

    # Configure + build inside a vcvars64 + CUDA environment, driven by a temporary batch file
    # (avoids cmd `&&` argument-splitting hazards with quoted paths).
    $batchPath = Join-Path $runtimeRoot "px_llama_build.bat"
    $configureLine = "`"$cmake`" " + ($cmakeArgs -join " ")
    $configureLine = [string]$configureLine
    $batchLines = @(
        "@echo off",
        "call `"$vcvars`"",
        "set `"CUDA_PATH=$cudaRoot`"",
        "set `"PATH=$cudaRoot\bin;$vsRoot\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%`"",
        "cd /d `"$repo`"",
        $configureLine,
        "if errorlevel 1 exit /b 1",
        "`"$cmake`" --build build --config Release --target llama-server llama-cli llama-bench",
        "if errorlevel 1 exit /b 1",
        "exit /b 0"
    )
    Set-Content -Path $batchPath -Value $batchLines -Encoding ASCII

    Write-Host "=== CMake configure + build (CUDA arch $CudaArchitectures) ==="
    $cmdExe = Join-Path $env:SystemRoot "System32\cmd.exe"
    & $cmdExe /c $batchPath
    if ($LASTEXITCODE -ne 0) { throw "CMake configure/build failed with exit code $LASTEXITCODE" }

    $candidates = @(
        (Join-Path $repo "build\bin\Release\llama-server.exe"),
        (Join-Path $repo "build\bin\llama-server.exe")
    )
    $server = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $server) { throw "llama-server.exe was not found after build" }

    $lock = [ordered]@{
        schema            = "px.runtime.llama_cpp_lock"
        schema_version    = 1
        source            = "https://github.com/ggml-org/llama.cpp"
        requested_ref     = $LlamaCppRef
        resolved_commit   = $resolvedCommit
        cuda_architectures = $CudaArchitectures
        portable_cuda_build = [bool]$PortableCudaBuild
        cuda_toolkit      = $cudaVersion
        msvc_toolset      = $msvcVersion
        configured_at     = (Get-Date).ToUniversalTime().ToString("o")
        server_path       = $server
        server_sha256     = (Get-FileHash $server -Algorithm SHA256).Hash.ToLowerInvariant()
        cmake_args        = $cmakeArgs
    }
    $lockPath = Join-Path $InstallRoot "runtime-lock.json"
    $lock | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $lockPath
    Write-Host "llama.cpp build ready: $server"
    Write-Host "Locked commit: $resolvedCommit"
    Write-Host "Runtime lock: $lockPath"
}
finally {
    Pop-Location
}
