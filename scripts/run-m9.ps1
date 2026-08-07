[CmdletBinding()]
param(
    [string]$OutputRoot = ".yatou\evidence\corpus\m9"
)

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path $python)) { $python = (Get-Command python.exe).Source }

$manifest = (& $python tools\google-vm-corpus\collector.py --output-root $OutputRoot | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or !(Test-Path $manifest)) { throw 'M9 corpus collection failed' }
$run = Split-Path -Parent $manifest
$chrome = Join-Path $run 'chrome.loaders.json'
$report = Join-Path $run 'm9.report.json'

& $python tools\google-vm-corpus\chrome_loader.py --manifest $manifest --output $chrome
if ($LASTEXITCODE -ne 0) { throw 'M9 Chrome loader collection failed' }

& .\scripts\build-v8-source.ps1 | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'V8 build failed' }

$corpus = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
$probes = @($corpus.entries | Where-Object { $_.name -like '*-probe' } | Sort-Object ordinal)
$yatouArguments = @()
foreach ($probe in $probes) {
    $source = Join-Path $run $probe.filename
    $destination = Join-Path $run ($probe.name + '.yatou.json')
    & $cargo run --quiet --locked -p yatou-core --features v8-runtime --example session_runner -- `
        --script $source | Set-Content -LiteralPath $destination -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "yatouv8 loader failed: $($probe.name)" }
    $yatouArguments += @('--yatou', $destination)
}

& $python tools\google-vm-corpus\finalize.py --manifest $manifest --chrome $chrome @yatouArguments --output $report
if ($LASTEXITCODE -ne 0) { throw 'M9 admission failed' }
Write-Host "M9 report: $((Resolve-Path $report).Path)"
