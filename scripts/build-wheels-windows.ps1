[CmdletBinding()]
param(
    [ValidateSet('windows-x86_64', 'windows-arm64')]
    [string]$TargetId = 'windows-x86_64',
    [Parameter(Mandatory)]
    [ValidateCount(5, 5)]
    [string[]]$PythonExecutables,
    [Parameter(Mandatory)]
    [string]$MaturinPythonExecutable,
    [string]$OutputDirectory = 'dist'
)

$ErrorActionPreference = 'Stop'
$expectedVersions = @('3.10', '3.11', '3.12', '3.13', '3.14')
$interpreters = @{}
foreach ($candidate in $PythonExecutables) {
    if (!(Test-Path -LiteralPath $candidate)) {
        throw "target Python executable not found: $candidate"
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    $version = (& $resolved -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or !$version) {
        throw "target Python inspection failed: $resolved"
    }
    if ($interpreters.ContainsKey($version)) {
        throw "duplicate target Python version: $version"
    }
    $interpreters[$version] = $resolved
}

$actualVersions = @($interpreters.Keys | Sort-Object)
if (($actualVersions -join ',') -ne ($expectedVersions -join ',')) {
    throw "expected CPython 3.10-3.14, found $($actualVersions -join ', ')"
}
if (!(Test-Path -LiteralPath $MaturinPythonExecutable)) {
    throw "maturin Python executable not found: $MaturinPythonExecutable"
}
$maturinPython = (Resolve-Path -LiteralPath $MaturinPythonExecutable).Path

$target = (& $maturinPython tools\build\wheel_matrix.py target --target $TargetId) |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $target.os -ne 'windows') {
    throw "unknown Windows wheel target: $TargetId"
}
$rustTarget = $target.rust_target
$platformTag = $target.platform_tag
$msvcArchitecture = if ($rustTarget -eq 'aarch64-pc-windows-msvc') { 'arm64' } else { 'amd64' }

& .\scripts\import-msvc-environment.ps1 -Architecture $msvcArchitecture
if (!$env:CARGO_TARGET_DIR) {
    $env:CARGO_TARGET_DIR = Join-Path $env:SystemDrive 'y8t'
}
New-Item -ItemType Directory -Force -Path $env:CARGO_TARGET_DIR | Out-Null
$crtStaticFlag = '-Ctarget-feature=+crt-static'
if (!$env:RUSTFLAGS -or !$env:RUSTFLAGS.Contains($crtStaticFlag)) {
    $env:RUSTFLAGS = (($env:RUSTFLAGS, $crtStaticFlag) | Where-Object { $_ }) -join ' '
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $OutputDirectory -Filter 'yatouv8-0.1.1-*.whl' |
    Where-Object Name -Like "*-$platformTag.whl" |
    Remove-Item -Force

# rusty_v8 150.4.0 publishes exact Windows x64/ARM64 release assets. Verify the
# locked SHA-256 values before use, then reuse one target asset for all five
# CPython ABI links. Linux/macOS continue exercising V8_FROM_SOURCE builds.
$previousPython = $env:PYTHON
$previousV8Archive = $env:RUSTY_V8_ARCHIVE
$previousV8Binding = $env:RUSTY_V8_SRC_BINDING_PATH
$previousV8FromSource = $env:V8_FROM_SOURCE
try {
    $env:PYTHON = $maturinPython
    $assetManifest = Join-Path $env:TEMP "yatouv8-rusty-v8-$rustTarget.json"
    $assetCache = Join-Path $env:LOCALAPPDATA 'yatouv8\rusty-v8'
    & $maturinPython tools\build\prepare_rusty_v8_windows.py `
        --target $rustTarget --cache $assetCache --output $assetManifest | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'rusty_v8 asset preparation failed' }
    $assets = Get-Content -Raw -LiteralPath $assetManifest | ConvertFrom-Json
    $env:RUSTY_V8_ARCHIVE = $assets.archive.path
    $env:RUSTY_V8_SRC_BINDING_PATH = $assets.binding.path
    Remove-Item Env:V8_FROM_SOURCE -ErrorAction SilentlyContinue
    $env:YATOU_V8_SOURCE_PREPARED_TARGET = $rustTarget

    foreach ($version in $expectedVersions) {
        & .\scripts\build-wheel.ps1 `
            -TargetId $TargetId `
            -PythonExecutable $interpreters[$version] `
            -MaturinPythonExecutable $maturinPython `
            -OutputDirectory $OutputDirectory `
            -SkipV8Build `
            -SkipTests | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "$TargetId CPython $version wheel build failed"
        }
    }
}
finally {
    $env:PYTHON = $previousPython
    $env:RUSTY_V8_ARCHIVE = $previousV8Archive
    $env:RUSTY_V8_SRC_BINDING_PATH = $previousV8Binding
    $env:V8_FROM_SOURCE = $previousV8FromSource
    Remove-Item Env:YATOU_V8_SOURCE_PREPARED_TARGET -ErrorAction SilentlyContinue
}

& $maturinPython tools\build\wheel_matrix.py verify-dist `
    --target $TargetId --dist $OutputDirectory | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'complete wheel-set verification failed' }

$wheels = Get-ChildItem -LiteralPath $OutputDirectory -Filter 'yatouv8-0.1.1-*.whl' |
    Where-Object Name -Like "*-$platformTag.whl" |
    Sort-Object Name
if ($wheels.Count -ne 5) {
    throw "expected five $TargetId wheels, found $($wheels.Count)"
}

[pscustomobject]@{
    target_id = $TargetId
    rust_target = $rustTarget
    platform_tag = $platformTag
    v8_asset_download_count = 1
    wheels = @($wheels | ForEach-Object {
        [pscustomobject]@{
            name = $_.Name
            size_bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
} | ConvertTo-Json -Depth 4
