[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$code = Get-Command code -ErrorAction Stop
& $code.Source --uninstall-extension 'mountain-nomad-bc.pacify-x-vscode'
if ($LASTEXITCODE -ne 0) { throw "VS Code uninstall failed with exit code $LASTEXITCODE." }
Write-Host 'Pacify-X extension removed. User settings remain until removed through VS Code Settings.'
