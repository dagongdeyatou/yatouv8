[CmdletBinding()]
param(
    [string]$OutputDirectory = "dist",
    [string]$PythonExecutable = "C:\ProgramData\anaconda3\python.exe",
    [string]$MaturinPythonExecutable = "C:\ProgramData\anaconda3\python.exe",
    [ValidateSet('windows-x86_64', 'windows-arm64')]
    [string]$TargetId = 'windows-x86_64',
    [switch]$SkipV8Build,
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
$pythonVersion = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or !$pythonVersion) { throw 'target Python version inspection failed' }
$cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
$env:PATH = "$cargoBin;$env:PATH"

$targetJson = & $python tools\build\wheel_matrix.py target --target $TargetId
if ($LASTEXITCODE -ne 0) { throw "unknown wheel target: $TargetId" }
$target = $targetJson | ConvertFrom-Json
if ($target.os -ne 'windows') { throw "$TargetId is not a Windows target" }
$rustTarget = $target.rust_target
$platformTag = $target.platform_tag

$rustcVersion = (& (Join-Path $cargoBin 'rustc.exe') -vV) -join "`n"
if ($LASTEXITCODE -ne 0 -or $rustcVersion -notmatch '(?m)^host:\s*(\S+)\s*$') {
    throw 'Unable to determine the Rust host target'
}
$hostTarget = $Matches[1]
$isCross = $hostTarget -ne $rustTarget
$runTests = !$SkipTests -and !$isCross
$maturinInterpreter = if ($isCross) { "python$pythonVersion" } else { $python }

if ($SkipV8Build) {
    if ($env:YATOU_V8_SOURCE_PREPARED_TARGET -ne $rustTarget) {
        throw "V8 source build for $rustTarget has not been prepared in this process"
    }
}
else {
    & .\scripts\build-v8-source.ps1 -Profile release -Target $rustTarget | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'V8 source build failed' }
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$previousCross = $env:PYO3_CROSS
$previousCrossVersion = $env:PYO3_CROSS_PYTHON_VERSION
try {
    if ($isCross) {
        $env:PYO3_CROSS = '1'
        $env:PYO3_CROSS_PYTHON_VERSION = $pythonVersion
    }
    & $maturinPython -m maturin build --release --locked --auditwheel repair `
        --compatibility pypi --target $rustTarget --interpreter $maturinInterpreter `
        --out $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'maturin wheel build failed' }
}
finally {
    $env:PYO3_CROSS = $previousCross
    $env:PYO3_CROSS_PYTHON_VERSION = $previousCrossVersion
}

$wheel = Get-ChildItem -LiteralPath $OutputDirectory -Filter 'yatouv8-0.1.2-*.whl' |
    Where-Object Name -Like "*-$pythonTag-$pythonTag-$platformTag.whl" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (!$wheel) { throw "yatouv8 $pythonTag $platformTag wheel was not created" }

& $python tools\build\wheel_matrix.py verify-dist `
    --target $TargetId --dist $OutputDirectory --python-version $pythonVersion | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'wheel payload verification failed' }

if ($runTests) {
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
    target_id = $TargetId
    rust_target = $rustTarget
    platform_tag = $platformTag
    python = $python
    python_tag = $pythonTag
    size_bytes = $wheel.Length
    sha256 = $hash
    cross_compiled = $isCross
    tests = $runTests
} | ConvertTo-Json
