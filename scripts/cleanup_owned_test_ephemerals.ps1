param([Parameter(Mandatory=$true)][string]$WorkspaceRoot,[Parameter(Mandatory=$true)][string]$ReceiptPath)
$ErrorActionPreference='Stop'
$workspace=[IO.Path]::GetFullPath($WorkspaceRoot).TrimEnd('\')
$tempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$workspaceCache=[IO.Path]::GetFullPath((Join-Path $workspace 'extension\.vscode-test')).TrimEnd('\')
$ownedPrefixes=@('pacify-x-vscode-test-cache','pacify-x-installed-vsix-','pacify-x-independent-ui-audit-','pacify-x-o04-vscode-')
$targets=@(Get-ChildItem -LiteralPath $tempRoot -Directory -Force | Where-Object { $candidate=$_.Name; @($ownedPrefixes | Where-Object { $candidate.StartsWith($_,[StringComparison]::OrdinalIgnoreCase) }).Count -gt 0 } | ForEach-Object { $_.FullName })+@($workspaceCache)
$before=[int64](Get-PSDrive C).Free
$processes=@(Get-CimInstance Win32_Process)
$records=@()
foreach($supplied in $targets){
 if(-not(Test-Path -LiteralPath $supplied)){continue}
 $target=[IO.Path]::GetFullPath($supplied).TrimEnd('\')
 $allowed=$target.StartsWith($tempRoot+'\',[StringComparison]::OrdinalIgnoreCase)-or $target.Equals($workspaceCache,[StringComparison]::OrdinalIgnoreCase)
 if(-not $allowed-or $target-eq$tempRoot-or $target-eq$workspace){throw "Unsafe cleanup target: $target"}
 $users=@($processes|Where-Object{$_.CommandLine-and$_.CommandLine.IndexOf($target,[StringComparison]::OrdinalIgnoreCase)-ge 0})
 if($users.Count){throw "Live process references $target"}
 $links=@(Get-ChildItem -LiteralPath $target -Recurse -Force -Attributes ReparsePoint)
 foreach($link in $links){
  $linkPath=[IO.Path]::GetFullPath($link.FullName)
  foreach($raw in @($link.Target)){if($raw){$destination=[IO.Path]::GetFullPath($raw);if(-not $destination.StartsWith($target+'\',[StringComparison]::OrdinalIgnoreCase)){throw "Reparse escape: $linkPath -> $destination"}}}
  Remove-Item -LiteralPath $linkPath -Force
 }
 if(@(Get-ChildItem -LiteralPath $target -Recurse -Force -Attributes ReparsePoint).Count){throw "Reparse point remains: $target"}
 $m=Get-ChildItem -LiteralPath $target -Recurse -File -Force|Measure-Object Length -Sum
 $records+=[pscustomobject]@{path=$target;classification='ephemeral';owner='PACIFY-X test tooling';file_count=[int64]$m.Count;logical_bytes=[int64]$m.Sum;reparse_points_removed=[int64]$links.Count;disposition='permanently_reclaimed_by_explicit_user_authority'}
 Remove-Item -LiteralPath $target -Recurse -Force
 if(Test-Path -LiteralPath $target){throw "Target remains: $target"}
}
$after=[int64](Get-PSDrive C).Free
$receipt=[ordered]@{schema_version='px.owned-test-ephemeral-cleanup/1.0';created_utc=(Get-Date).ToUniversalTime().ToString('o');authority='explicit_user_request_2026-08-13';hard_delete=$true;protected_data_touched=$false;records=$records;target_count=$records.Count;logical_bytes_reclaimed=[int64](($records|Measure-Object logical_bytes -Sum).Sum);free_bytes_before=$before;free_bytes_after=$after;free_bytes_gained=[int64]($after-$before);all_targets_absent=$true}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReceiptPath)|Out-Null
$json=$receipt|ConvertTo-Json -Depth 6
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReceiptPath),$json+"`n",[Text.UTF8Encoding]::new($false))
$json
