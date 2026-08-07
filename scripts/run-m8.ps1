[CmdletBinding()]
param(
    [string]$OutputRoot = ".yatou\evidence\reports\m8"
)

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path $python)) { $python = (Get-Command python.exe).Source }
$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss.fffffffZ')
$run = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Path $run -Force | Out-Null

& .\scripts\build-v8-source.ps1 | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'V8 build failed' }

$yatou = Join-Path $run 'yatou.json'
$chrome = Join-Path $run 'chrome.json'
$report = Join-Path $run 'm8.report.json'

& $cargo run --quiet --locked -p yatou-core --features v8-runtime --example session_runner -- `
    --script tools\host-conformance\probe.js | Set-Content -LiteralPath $yatou -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'yatouv8 M8 probe failed' }

& $python tools\host-conformance\collector.py --output $chrome
if ($LASTEXITCODE -ne 0) { throw 'Chrome M8 probe failed' }

& $python tools\host-conformance\finalize.py --chrome $chrome --yatou $yatou --output $report
if ($LASTEXITCODE -ne 0) { throw 'M8 conformance failed' }

Write-Host "M8 report: $((Resolve-Path $report).Path)"
