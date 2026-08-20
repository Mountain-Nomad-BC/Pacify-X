[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$OutputDirectory,
  [string]$Version = '',
  [string]$ArtifactPath = ''
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$package = Get-Content -LiteralPath (Join-Path $repositoryRoot 'extension\package.json') -Raw | ConvertFrom-Json
if (-not $Version) { $Version = [string]$package.version }
if ($Version -ne [string]$package.version) { throw "Requested audit version $Version does not match extension package version $($package.version)." }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) { throw "Output directory does not exist: $outputRoot" }
$vsix = if ($ArtifactPath) { [IO.Path]::GetFullPath($ArtifactPath) } else { Join-Path $repositoryRoot "extension\dist\$($package.name)-$Version.vsix" }
if (-not (Test-Path -LiteralPath $vsix -PathType Leaf)) { throw "Exact VSIX is missing: $vsix" }
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$archive = Join-Path $outputRoot "PACIFY_X_CLEAN_FULL_AUDIT_$Version`_$stamp.zip"
& python (Join-Path $repositoryRoot 'scripts\clean_source_export.py') --root $repositoryRoot --output $archive --artifact $vsix
if ($LASTEXITCODE -ne 0) { throw "Governed clean-export finalization failed with exit code $LASTEXITCODE." }
$sha = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$archive.sha256", "$sha  $([IO.Path]::GetFileName($archive))`n", [Text.UTF8Encoding]::new($false))
[pscustomobject]@{ schema_version='px.clean-audit-bundle-wrapper/1.0'; valid=$true; archive=$archive; sha256=$sha; version=$Version } | ConvertTo-Json
