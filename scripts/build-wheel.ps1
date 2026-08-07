[CmdletBinding()]
param(
    [string]$OutputDirectory = "dist",
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$python = 'C:\ProgramData\anaconda3\python.exe'
if (!(Test-Path -LiteralPath $python)) { $python = (Get-Command python.exe).Source }
$cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
$env:PATH = "$cargoBin;$env:PATH"

& .\scripts\build-v8-source.ps1 | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'V8 source build failed' }

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
& $python -m maturin build --release --locked --auditwheel repair --out $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'maturin wheel build failed' }

$wheel = Get-ChildItem -LiteralPath $OutputDirectory -Filter 'yatouv8-0.1.0-*.whl' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (!$wheel) { throw 'yatouv8 wheel was not created' }

if (!$SkipTests) {
    $venv = Join-Path ([IO.Path]::GetTempPath()) ("yatouv8-wheel-test-" + [guid]::NewGuid().ToString('N'))
    try {
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'test venv creation failed' }
        $venvPython = Join-Path $venv 'Scripts\python.exe'
        & $venvPython -m pip install --disable-pip-version-check --no-input $wheel.FullName
        if ($LASTEXITCODE -ne 0) { throw 'wheel installation failed' }
        & $venvPython -m unittest discover -s python\tests -v
        if ($LASTEXITCODE -ne 0) { throw 'installed-wheel tests failed' }
    }
    finally {
        if (Test-Path -LiteralPath $venv) { Remove-Item -LiteralPath $venv -Recurse -Force }
    }
}

$hash = (Get-FileHash -LiteralPath $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
[pscustomobject]@{
    wheel = $wheel.FullName
    size_bytes = $wheel.Length
    sha256 = $hash
    tests = !$SkipTests
} | ConvertTo-Json
