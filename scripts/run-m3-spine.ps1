[CmdletBinding()]
param(
    [string]$TracePath = '.yatou\evidence\traces\m3\trace-spine-v1.ndjson'
)

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
}

function Assert-NativeSuccess {
    param([Parameter(Mandatory)] [string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

& $cargo run -q -p yatou-core --example trace_spine -- $TracePath
Assert-NativeSuccess 'trace generation and replay'

& $cargo run -q -p yatou-schema --example validate_trace -- $TracePath
Assert-NativeSuccess 'Rust trace validation'

& $python 'tools\trace-inspector\trace_inspector.py' $TracePath --ledger
Assert-NativeSuccess 'independent trace inspection'

$snapshot = Get-ChildItem `
    '.yatou\evidence\baselines\win11-chrome150.0.7871.188-headful-m2-v2\runs' `
    -Recurse -Filter snapshot.json |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (!$snapshot) {
    throw 'accepted headful M2 v2 snapshot not found'
}

& $python 'tools\trace-inspector\admit_trace.py' $TracePath `
    --snapshot $snapshot.FullName --evidence-root '.yatou\evidence'
Assert-NativeSuccess 'trace evidence admission'
