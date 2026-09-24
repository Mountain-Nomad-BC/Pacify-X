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

Write-Host "Certification environment ready:" -ForegroundColor Green
foreach ($tool in $required.Keys | Sort-Object) {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    Write-Host ("  {0,-12} {1}" -f $tool, $cmd.Source)
}