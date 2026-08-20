param(
    [Parameter(Mandatory = $true)][string]$ReceiptPath
)

$ErrorActionPreference = 'Stop'
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$before = [int64](Get-PSDrive C).Free
$processes = @(Get-CimInstance Win32_Process)
$candidates = @()
$discoveryRetained = @()

foreach ($item in @(Get-ChildItem -LiteralPath $tempRoot -Force -Directory)) {
    try {
      $reason = $null
      if ($item.Name -like 'px-enterprise-*') {
        $stateRoot = Join-Path $item.FullName '.engineering-bootstrap'
        if (Test-Path -LiteralPath $stateRoot -PathType Container) {
            $reason = 'px-enterprise-test-state'
        }
    }
      elseif ($item.Name -like 'tmp*') {
        $framework = Join-Path $item.FullName 'framework'
        $repository = Join-Path $item.FullName 'repository'
        $hasFrameworkSignature = (Test-Path -LiteralPath (Join-Path $framework 'runtime') -PathType Container) -and (
            (Test-Path -LiteralPath (Join-Path $framework '.px')) -or
            (Test-Path -LiteralPath (Join-Path $framework 'policies')) -or
            (Test-Path -LiteralPath (Join-Path $framework 'registry')) -or
            (Test-Path -LiteralPath (Join-Path $framework 'engineering_loop_bootstrap.egg-info')) -or
            (Test-Path -LiteralPath (Join-Path $framework '.git'))
        )
        $hasRepositorySignature = (Test-Path -LiteralPath $repository -PathType Container) -and (
            (Test-Path -LiteralPath (Join-Path $repository '.git')) -or
            ((Test-Path -LiteralPath (Join-Path $repository 'runtime')) -and (Test-Path -LiteralPath (Join-Path $repository 'pyproject.toml')))
        )
        $hasPackageSignature = (Test-Path -LiteralPath (Join-Path $item.FullName 'engineering_loop_bootstrap-1.2.3-py3-none-any.whl')) -or
            (Test-Path -LiteralPath (Join-Path $item.FullName 'engineering_loop_bootstrap-1.2.3.tar.gz'))
        $hasReleaseFixtureSignature = (Test-Path -LiteralPath (Join-Path $item.FullName 'release_ed25519')) -and
            (Test-Path -LiteralPath (Join-Path $item.FullName 'release_ed25519.pub'))
        if ($hasFrameworkSignature) { $reason = 'px-framework-test-fixture' }
        elseif ($hasRepositorySignature) { $reason = 'px-repository-test-fixture' }
        elseif ($hasPackageSignature) { $reason = 'px-package-build-test-fixture' }
        elseif ($hasReleaseFixtureSignature) { $reason = 'px-release-signing-test-fixture' }
        elseif ($item.Name -match '^tmp.*-(artifacts|build-custody)$') { $reason = 'px-release-output-test-fixture' }
    }
      if ($reason) {
        $candidates += [pscustomobject]@{ Item = $item; OwnershipEvidence = $reason }
      }
    }
    catch {
        $discoveryRetained += [pscustomobject]@{ path = $item.FullName; reason = $_.Exception.GetType().Name; message = $_.Exception.Message }
    }
}

$records = @()
$retained = @()
foreach ($candidate in $candidates) {
    $item = $candidate.Item
    $target = [IO.Path]::GetFullPath($item.FullName).TrimEnd('\')
    try {
        if ([IO.Path]::GetDirectoryName($target) -ne $tempRoot) { throw "Target is not an immediate temp child" }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Top-level target is a reparse point" }
        $users = @($processes | Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
        if ($users.Count) { throw "A live process references the target" }
        $links = @(Get-ChildItem -LiteralPath $target -Recurse -Force -Attributes ReparsePoint -ErrorAction Stop)
        foreach ($link in $links) {
            $linkPath = [IO.Path]::GetFullPath($link.FullName)
            foreach ($raw in @($link.Target)) {
                if ($null -ne $raw -and [string]$raw -ne '') {
                    $destination = [IO.Path]::GetFullPath([string]$raw)
                    if (-not $destination.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) {
                        throw "Reparse target escapes fixture: $linkPath -> $destination"
                    }
                }
            }
            if ($link.PSIsContainer) { [IO.Directory]::Delete($linkPath, $false) }
            else { [IO.File]::Delete($linkPath) }
        }
        $measure = Get-ChildItem -LiteralPath $target -Recurse -File -Force -ErrorAction Stop | Measure-Object Length -Sum
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $target) { throw "Target remains after reclamation" }
        $records += [pscustomobject]@{
            path = $target
            owner = 'PACIFY-X generated test fixture'
            ownership_evidence = $candidate.OwnershipEvidence
            classification = 'ephemeral'
            file_count = [int64]$measure.Count
            logical_bytes = [int64]$measure.Sum
            reparse_points_removed = [int64]$links.Count
            disposition = 'permanently_reclaimed_by_explicit_user_authority'
        }
    }
    catch {
        $retained += [pscustomobject]@{
            path = $target
            ownership_evidence = $candidate.OwnershipEvidence
            reason = $_.Exception.GetType().Name
            message = $_.Exception.Message
        }
    }
}

$after = [int64](Get-PSDrive C).Free
$receipt = [ordered]@{
    schema_version = 'px.generated-test-fixture-cleanup/1.0'
    created_utc = (Get-Date).ToUniversalTime().ToString('o')
    authority = 'explicit_user_request_2026-08-13'
    allowed_root = $tempRoot
    hard_delete = $true
    protected_data_touched = $false
    quarantine_data_touched = $false
    candidate_count = $candidates.Count
    removed_target_count = $records.Count
    retained_count = $retained.Count + $discoveryRetained.Count
    removed_file_count = [int64](($records | Measure-Object file_count -Sum).Sum)
    logical_bytes_reclaimed = [int64](($records | Measure-Object logical_bytes -Sum).Sum)
    free_bytes_before = $before
    free_bytes_after = $after
    free_bytes_gained = [int64]($after - $before)
    records = $records
    retained = @($retained) + @($discoveryRetained)
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReceiptPath) | Out-Null
$json = $receipt | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReceiptPath), $json + "`n", [Text.UTF8Encoding]::new($false))
$json
