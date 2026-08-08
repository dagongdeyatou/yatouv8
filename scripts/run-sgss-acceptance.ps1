[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
if (!(Test-Path -LiteralPath $cargo)) { throw "cargo not found at $cargo" }

& $cargo run --locked -q -p yatou-core --features v8-runtime --example surface_acceptance
if ($LASTEXITCODE -ne 0) { throw 'surface acceptance failed' }

& $cargo run --locked -q -p yatou-core --features v8-runtime --example sgss_acceptance
if ($LASTEXITCODE -ne 0) { throw 'SG_SS local acceptance failed' }

$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path -LiteralPath $python)) { $python = (Get-Command python.exe).Source }
& $python -m unittest discover python/tests -v
if ($LASTEXITCODE -ne 0) { throw 'Python runtime acceptance failed' }
