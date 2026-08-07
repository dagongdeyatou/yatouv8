[CmdletBinding()]
param(
    [ValidateSet('headless', 'headful')]
    [string]$Mode = 'headless',
    [string]$BaselineId = '',
    [string]$OutputRoot = '.yatou\evidence'
)

$ErrorActionPreference = 'Stop'
$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

$arguments = @(
    (Join-Path $PSScriptRoot 'collector.py'),
    '--mode', $Mode,
    '--output-root', $OutputRoot
)
if ($BaselineId) {
    $arguments += @('--baseline-id', $BaselineId)
}

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Chrome collector failed with exit code $LASTEXITCODE"
}
