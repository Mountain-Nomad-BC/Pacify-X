# Process-local tool discovery, not a certification or release authority.
# No signing, downloads, installed-cache checks or historical artifact coupling.
param([string[]]$RequiredTools = @('python'))
$ErrorActionPreference = 'Stop'
if ($null -eq $RequiredTools -or $RequiredTools.Count -eq 0) {
    throw 'At least one tool name must be supplied.'
}
foreach ($name in $RequiredTools) {
    if ([string]::IsNullOrWhiteSpace($name) -or $name -notmatch '^[A-Za-z0-9_.-]+$') {
        throw 'Tool names must be literal application names without paths or wildcard syntax.'
    }
}
$originalPath = $env:PATH
$pathParts = @($originalPath)
foreach ($target in @('Machine', 'User')) {
    $persisted = [Environment]::GetEnvironmentVariable('Path', $target)
    if ($persisted) { $pathParts += $persisted }
}
$seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$ordered = foreach ($block in $pathParts) {
    foreach ($part in ($block -split ';')) {
        if ($part -and $part.Trim() -and $seen.Add($part.Trim())) { $part.Trim() }
    }
}
$env:PATH = ($ordered -join ';')
$tools = @()
$missing = @()
foreach ($name in $RequiredTools) {
    $application = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $application) { $missing += $name }
    else { $tools += [pscustomobject]@{ name = $name; path = $application.Source } }
}
if ($missing.Count -gt 0) {
    $env:PATH = $originalPath
    throw ('Required tools unavailable: ' + ($missing -join ', ') + '. No installation was attempted.')
}
[pscustomobject]@{
    schema_version = 'px.tool-discovery/1.0'
    mode = 'process-local-tool-discovery'
    tools = @($tools)
    certification_verified = $false
    historical_artifacts_required = $false
    installs_or_builds_performed = $false
}
