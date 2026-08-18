[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path $python)) { $python = (Get-Command python.exe).Source }
$temporary = Join-Path '.yatou' ('m10-tmp-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary -Force | Out-Null

try {
    & .\scripts\check.ps1
    if ($LASTEXITCODE -ne 0) { throw 'base quality gate failed' }

    & .\scripts\build-v8-source.ps1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'V8 source build failed' }
    & $cargo test --locked -p yatou-core --features v8-runtime --all-targets
    if ($LASTEXITCODE -ne 0) { throw 'V8 runtime tests failed' }
    & $cargo clippy --locked -p yatou-core --features v8-runtime --all-targets -- -D warnings
    if ($LASTEXITCODE -ne 0) { throw 'V8 runtime clippy failed' }

    $performance = Join-Path $temporary 'm10.performance.json'
    & $cargo run --quiet --locked -p yatou-core --features v8-runtime --example m10_quality |
        Set-Content -LiteralPath $performance -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'M10 performance gate failed' }

    & .\scripts\run-m6.ps1
    & .\scripts\run-m8.ps1
    & .\scripts\run-m9.ps1
    & .\scripts\build-wheel.ps1

    $wheel = Get-ChildItem dist -Filter 'yatouv8-0.1.1-*.whl' | Sort LastWriteTime -Desc | Select -First 1
    $sbom = Join-Path $temporary 'yatouv8-0.1.1.cdx.json'
    $audit = Join-Path $temporary 'm10.release-audit.json'
    & $python tools\release\generate_sbom.py --cargo $cargo --output $sbom
    if ($LASTEXITCODE -ne 0) { throw 'SBOM generation failed' }
    & $python tools\release\audit_release.py --wheel $wheel.FullName --sbom $sbom --output $audit
    if ($LASTEXITCODE -ne 0) { throw 'release audit failed' }

    $m6 = Get-ChildItem .yatou\evidence\reports\m6 -Recurse -Filter m6.report.json | Sort LastWriteTime -Desc | Select -First 1
    $m8 = Get-ChildItem .yatou\evidence\reports\m8 -Recurse -Filter m8.report.json | Sort LastWriteTime -Desc | Select -First 1
    $m9 = Get-ChildItem .yatou\evidence\corpus\m9 -Recurse -Filter m9.report.json | Sort LastWriteTime -Desc | Select -First 1
    $report = (& $python tools\release\finalize.py `
        --m6 $m6.FullName --m8 $m8.FullName --m9 $m9.FullName `
        --performance $performance --wheel $wheel.FullName --sbom $sbom --audit $audit |
        Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $report)) { throw 'M10 terminal report failed' }
    Write-Host "M10 terminal report: $((Resolve-Path $report).Path)"
}
finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
