[CmdletBinding()]
param(
    [string]$OutputDirectory = "dist",
    [string]$PythonExecutable = "C:\ProgramData\anaconda3\python.exe",
    [string]$MaturinPythonExecutable = "C:\ProgramData\anaconda3\python.exe",
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $PythonExecutable)) {
    throw "target Python executable not found: $PythonExecutable"
}
if (!(Test-Path -LiteralPath $MaturinPythonExecutable)) {
    $MaturinPythonExecutable = $PythonExecutable
}
$python = (Resolve-Path -LiteralPath $PythonExecutable).Path
$maturinPython = (Resolve-Path -LiteralPath $MaturinPythonExecutable).Path
$pythonTag = (& $python -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or !$pythonTag) { throw 'target Python inspection failed' }
$cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
$env:PATH = "$cargoBin;$env:PATH"

& .\scripts\build-v8-source.ps1 | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'V8 source build failed' }

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
& $maturinPython -m maturin build --release --locked --auditwheel repair `
    --interpreter $python --out $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'maturin wheel build failed' }

$wheel = Get-ChildItem -LiteralPath $OutputDirectory -Filter 'yatouv8-0.1.0-*.whl' |
    Where-Object Name -Like "*-$pythonTag-$pythonTag-win_amd64.whl" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (!$wheel) { throw "yatouv8 $pythonTag wheel was not created" }

if (!$SkipTests) {
    $testRoot = Join-Path ([IO.Path]::GetTempPath()) ("yatouv8-wheel-test-" + [guid]::NewGuid().ToString('N'))
    $testSite = Join-Path $testRoot 'site-packages'
    $previousPythonPath = $env:PYTHONPATH
    $buildPath = $env:PATH
    try {
        New-Item -ItemType Directory -Path $testSite -Force | Out-Null
        # Some redistributed CPython 3.10 builds force subprocess text mode.
        # pip's user-agent probe then crashes if rustc is visible because it
        # expects bytes from `rustc --version`. rustc is not needed to install
        # an already-built wheel, so keep it out of this isolated test step.
        $env:PATH = (($buildPath -split ';') |
            Where-Object { $_.TrimEnd('\') -ine $cargoBin.TrimEnd('\') }) -join ';'
        & $python -m pip install --disable-pip-version-check --no-input `
            --no-deps --target $testSite $wheel.FullName
        if ($LASTEXITCODE -ne 0) { throw 'wheel installation failed' }
        $env:PYTHONPATH = $testSite
        & $python -m unittest discover -s python\tests -v
        if ($LASTEXITCODE -ne 0) { throw 'installed-wheel tests failed' }
    }
    finally {
        $env:PATH = $buildPath
        $env:PYTHONPATH = $previousPythonPath
        if (Test-Path -LiteralPath $testRoot) {
            Remove-Item -LiteralPath $testRoot -Recurse -Force
        }
    }
}

$hash = (Get-FileHash -LiteralPath $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
[pscustomobject]@{
    wheel = $wheel.FullName
    python = $python
    python_tag = $pythonTag
    size_bytes = $wheel.Length
    sha256 = $hash
    tests = !$SkipTests
} | ConvertTo-Json
