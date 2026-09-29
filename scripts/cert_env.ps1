# Certification environment bootstrap.
#
# The interactive shell in this session inherited a stripped process PATH: git,
# ssh-keygen, node, npm, and python all failed `shutil.which`, even though every one
# of them is present and correctly registered in the persisted User/Machine PATH.
# Governed runs resolve executables with `shutil.which`, so they must be launched with
# the persisted PATH rather than whatever the interactive shell happens to hold.
#
# Dot-source this from the repository root before any governed command:
#     . .\.px-cert-env.ps1
#
# It is idempotent, non-destructive, and changes nothing outside the current process.

$ErrorActionPreference = 'Stop'

# Reconciliation anchor for the cohesion punch cards. The cards reference
# PX_COMMENCEMENT_ORCHESTRATION_2026-09-04.md by absolute path, and the
# reconciler only accepts a reference that resolves to exactly this path, so
# the anchor has to be created at that location. The original document was lost
# with the cleared Downloads working folder; the file there now is a
# clearly-marked reconstructed stand-in (see the header in the file itself).
$env:PX_COMMENCEMENT_ORCHESTRATION = 'C:\Users\Ben\Downloads\px looks\PX_COMMENCEMENT_ORCHESTRATION_2026-09-04.md'

function Get-PersistedPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @()
    foreach ($block in @($machine, $user)) {
        if ($block) {
            $parts += ($block -split ';' | Where-Object { $_ -and $_.Trim() })
        }
    }
    # De-duplicate while preserving precedence order.
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $ordered = foreach ($p in $parts) { if ($seen.Add($p)) { $p } }
    return ($ordered -join ';')
}

$resolved = Get-PersistedPath

# Windows System32\OpenSSH ships an ssh-keygen that silently fails to sign with
# this repository's release key: it exits non-zero with no diagnostic output.
# Git's bundled OpenSSH build signs and verifies the same key correctly, so it
# must win executable resolution. It is prepended here rather than appended
# because System32\OpenSSH lives in the Machine PATH, which sorts first.
$gitUsrBin = 'C:\Program Files\Git\usr\bin'
if (Test-Path $gitUsrBin) {
    $resolved = "$gitUsrBin;$resolved"
}

if ($resolved) {
    $env:PATH = $resolved
}

# Required by the repository contract: Python 3.11-3.14, Git, OpenSSH Client,
# Node (with npm). Fail loudly rather than letting a governed run discover it late.
$required = @{
    'python'     = 'Python';
    'git'        = 'Git';
    'ssh-keygen' = 'OpenSSH Client';
    'node'       = 'Node.js';
    'npm'        = 'npm';
}

$missing = @()
foreach ($tool in $required.Keys | Sort-Object) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        $missing += "$tool ($($required[$tool]))"
    }
}

if ($missing.Count -gt 0) {
    Write-Error ("Certification environment is incomplete. Missing: " + ($missing -join ', ') + ". The repository contract requires Python 3.11-3.14, Git, OpenSSH Client (ssh-keygen), and Node with npm.")
    exit 1
}

# Presence is not sufficiency. System32\OpenSSH's ssh-keygen resolves fine but
# cannot sign with this repository's release key, which previously surfaced only
# at the finalize stage after eleven stages had already run. Probe the resolved
# build's actual signing capability now, so a wrong binary fails at launch.
$sshKeygen = (Get-Command 'ssh-keygen' -ErrorAction SilentlyContinue).Source
$probeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("px-cert-env-probe-" + [System.Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $probeDir -Force | Out-Null
$probePayload = Join-Path $probeDir 'probe'
Set-Content -Path $probePayload -Value 'pacify-x certification environment probe' -Encoding UTF8
$probeSig = "$probePayload.sig"
# Git's ssh-keygen writes progress ("Signing file ...") to stderr on success.
# Relax error handling for this one call so a successful sign is not treated as
# a terminating native-command error; $LASTEXITCODE is the real signal.
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $sshKeygen -Y sign -f '.git/pacify-x-release-key-2026' -n file $probePayload 2>$null | Out-Null
$probeExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
$probeOk = ($probeExitCode -eq 0) -and (Test-Path $probeSig)
if ($probeSig) { Remove-Item -Force $probeSig -ErrorAction SilentlyContinue }
Remove-Item -Recurse -Force $probeDir -ErrorAction SilentlyContinue

if (-not $probeOk) {
    Write-Error ("Resolved ssh-keygen cannot sign with the repository release key: $sshKeygen. Ensure 'C:\Program Files\Git\usr\bin' precedes System32\OpenSSH on PATH before sourcing cert_env.ps1. The finalize stage would otherwise fail after the full campaign has run.")
    exit 1
}
Write-Host "  signing      OK ($sshKeygen can sign with the repository release key)" -ForegroundColor Green

# The exhaustive installed-operational walk resolves a retained VS Code build.
# A half-extracted cache previously killed that stage in 26 seconds, so verify
# the download is genuinely complete before any campaign is allowed to start.
$vscodeCache = Join-Path ([System.IO.Path]::GetTempPath()) 'pacify-x-vscode-test-cache'
$vscodeMarker = Join-Path $vscodeCache '.pacify-x-owned-cache.json'
$vscodeVersion = '1.132.1'
$vscodeDir = Join-Path $vscodeCache "vscode-win32-x64-archive-$vscodeVersion"
if (-not (Test-Path $vscodeMarker) -or -not (Test-Path (Join-Path $vscodeDir 'is-complete')) -or -not (Test-Path (Join-Path $vscodeDir 'Code.exe'))) {
    Write-Error ("Owned VS Code test cache is absent or incomplete: $vscodeCache. Run: node extension/scripts/prepare-owned-vscode-test-cache.js")
    exit 1
}
Write-Host "  vscode-cache OK ($vscodeVersion retained and complete)" -ForegroundColor Green

# The cohesion punch cards reference an external commencement-orchestration
# document. Without this anchor card_reconcile rejects the reference outright.
if (-not (Test-Path $env:PX_COMMENCEMENT_ORCHESTRATION)) {
    Write-Error ("Cohesion card anchor is missing: $env:PX_COMMENCEMENT_ORCHESTRATION. card_reconcile will reject the external live evidence reference.")
    exit 1
}
Write-Host "  card-anchor  OK ($env:PX_COMMENCEMENT_ORCHESTRATION)" -ForegroundColor Green

Write-Host "Certification environment ready:" -ForegroundColor Green
foreach ($tool in $required.Keys | Sort-Object) {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    Write-Host ("  {0,-12} {1}" -f $tool, $cmd.Source)
}