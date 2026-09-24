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

$runtimeRoot = Join-Path $InstallRoot "runtime"
$repo = Join-Path $runtimeRoot "llama.cpp"
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

if (-not (Test-Path (Join-Path $repo ".git"))) {
    git clone https://github.com/ggml-org/llama.cpp $repo
}

Push-Location $repo
try {
    $resolvedCommit = (git rev-parse HEAD).Trim()

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
        cuda_toolkit      = "13.4"
        msvc_toolset      = "14.51.36231"
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
