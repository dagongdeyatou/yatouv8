[CmdletBinding()]
param(
    [string]$OutputRoot = ".yatou\evidence\reports\trusted-types"
)

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    $python = (Get-Command python.exe).Source
}
$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss.fffffffZ')
$run = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Path $run -Force | Out-Null

& .\scripts\build-v8-source.ps1 | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'V8 build failed' }

$probe = 'tools\host-conformance\trusted-types-probe.js'
$yatou = Join-Path $run 'yatou.json'
$chrome = Join-Path $run 'chrome.json'
$report = Join-Path $run 'trusted-types.report.json'

& $cargo run --quiet --locked -p yatou-core --features v8-runtime `
    --example session_runner -- --script $probe |
    Set-Content -LiteralPath $yatou -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'yatouv8 Trusted Types probe failed' }

& $python tools\host-conformance\collector.py `
    --probe $probe --output $chrome
if ($LASTEXITCODE -ne 0) { throw 'Chrome Trusted Types probe failed' }

& $python tools\host-conformance\finalize.py `
    --chrome $chrome `
    --yatou $yatou `
    --output $report `
    --milestone trusted-types
if ($LASTEXITCODE -ne 0) { throw 'Trusted Types conformance failed' }

Write-Host "Trusted Types report: $((Resolve-Path $report).Path)"
