[CmdletBinding()]
param(
  [string]$VsixPath = ''
)

$ErrorActionPreference = 'Stop'
$package = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'package.json') | ConvertFrom-Json
$expectedName = "$($package.name)-$($package.version).vsix"
if (-not $VsixPath) { $VsixPath = Join-Path $PSScriptRoot "dist\$expectedName" }
$resolvedVsix = (Resolve-Path -LiteralPath $VsixPath).Path

$hashManifest = Join-Path $PSScriptRoot 'SHA256SUMS.txt'
$line = Get-Content -LiteralPath $hashManifest | Where-Object { $_ -match [regex]::Escape($expectedName) } | Select-Object -First 1
if (-not $line) { throw "SHA256SUMS.txt does not certify $expectedName." }
$expectedSha256 = ($line -split '\s+')[0].ToLowerInvariant()
$actualSha256 = (Get-FileHash -LiteralPath $resolvedVsix -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $expectedSha256) {
  throw "VSIX integrity check failed. Expected $expectedSha256, received $actualSha256."
}

$code = Get-Command code -ErrorAction Stop
$extensionId = "$($package.publisher).$($package.name)"
$installedBefore = & $code.Source --list-extensions --show-versions
if ($installedBefore -contains "$extensionId@$($package.version)") {
  throw "Refusing same-version replacement of $extensionId@$($package.version). Every changed VSIX payload requires a new package version."
}
& $code.Source --install-extension $resolvedVsix --force
if ($LASTEXITCODE -ne 0) { throw "VS Code rejected the VSIX with exit code $LASTEXITCODE." }

$installed = & $code.Source --list-extensions --show-versions | Where-Object { $_ -eq "$extensionId@$($package.version)" }
if (-not $installed) { throw "VS Code did not report $extensionId@$($package.version) after installation." }
Write-Host "Pacify-X $($package.version) installed and verified on disk. Run 'Developer: Reload Window' before opening the Pacify-X Control Plane."
