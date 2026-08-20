param([Parameter(Mandatory=$true)][string]$ReceiptPath)
$ErrorActionPreference='Stop'
$temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$root=[IO.Path]::GetFullPath((Join-Path $temp ('pytest-of-'+[Environment]::UserName))).TrimEnd('\')
if(-not $root.StartsWith($temp+'\',[StringComparison]::OrdinalIgnoreCase)-or $root-eq$temp){throw 'Unsafe pytest cleanup root'}
$users=@(Get-CimInstance Win32_Process|Where-Object{$_.CommandLine-and$_.CommandLine.IndexOf($root,[StringComparison]::OrdinalIgnoreCase)-ge 0})
if($users.Count){throw 'A live process references the pytest cleanup root'}
$before=[int64](Get-PSDrive C).Free
$removedFiles=[int64]0;$removedBytes=[int64]0;$removedTargets=[int64]0;$removedLinks=[int64]0;$retained=@()
foreach($item in @(Get-ChildItem -LiteralPath $root -Force)){
 try{
  $target=[IO.Path]::GetFullPath($item.FullName)
  if(-not $target.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Child escaped pytest root'}
  if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne 0){$links=@($item)}else{$links=@(Get-ChildItem -LiteralPath $target -Recurse -Force -Attributes ReparsePoint -ErrorAction Stop)}
  foreach($link in $links){
   $linkPath=[IO.Path]::GetFullPath($link.FullName)
   $destinations=@($link.Target)
   foreach($raw in $destinations){if($null-ne$raw-and[string]$raw-ne''){$destination=[IO.Path]::GetFullPath([string]$raw);if(-not $destination.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw "Reparse target escapes pytest root: $linkPath -> $destination"}}}
   if($link.PSIsContainer){[IO.Directory]::Delete($linkPath,$false)}else{[IO.File]::Delete($linkPath)};$removedLinks++
  }
  if(Test-Path -LiteralPath $target){$m=Get-ChildItem -LiteralPath $target -Recurse -File -Force -ErrorAction Stop|Measure-Object Length -Sum;$removedFiles+=[int64]$m.Count;$removedBytes+=[int64]$m.Sum;Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop}
  if(Test-Path -LiteralPath $target){throw 'Target remains after reclamation'}
  $removedTargets++
 }catch{$retained+=[pscustomobject]@{path=$item.FullName;reason=$_.Exception.GetType().Name;message=$_.Exception.Message;stack=$_.ScriptStackTrace}}
}
if(Test-Path -LiteralPath $root){$remaining=@(Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue);if($remaining.Count-eq 0){Remove-Item -LiteralPath $root -Force}}
$after=[int64](Get-PSDrive C).Free
$receipt=[ordered]@{schema_version='px.pytest-ephemeral-cleanup/1.0';created_utc=(Get-Date).ToUniversalTime().ToString('o');authority='explicit_user_request_2026-08-13';root=$root;classification='ephemeral';hard_delete=$true;protected_data_touched=$false;removed_target_count=$removedTargets;removed_file_count=$removedFiles;logical_bytes_reclaimed=$removedBytes;reparse_points_removed=$removedLinks;retained=$retained;retained_count=$retained.Count;root_absent=(-not(Test-Path -LiteralPath $root));free_bytes_before=$before;free_bytes_after=$after;free_bytes_gained=[int64]($after-$before)}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReceiptPath)|Out-Null
$json=$receipt|ConvertTo-Json -Depth 6
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReceiptPath),$json+"`n",[Text.UTF8Encoding]::new($false))
$json
