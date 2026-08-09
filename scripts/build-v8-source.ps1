[CmdletBinding()]
param(
    [ValidateSet('debug', 'release')]
    [string]$Profile = 'debug'
)

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'

if (!(Test-Path -LiteralPath $cargo)) {
    throw "cargo not found at $cargo"
}

$pythonCandidates = @(
    'C:\ProgramData\anaconda3\python.exe',
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if ($pythonCandidates.Count -eq 0) {
    throw 'Python 3 was not found. Set the PYTHON environment variable explicitly.'
}

function Install-PinnedBuildTool {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$Url,
        [Parameter(Mandatory)] [string]$Sha256,
        [Parameter(Mandatory)] [string]$Executable
    )

    $toolRoot = Join-Path $env:LOCALAPPDATA 'yatouv8\toolchain\v8-150.4.0'
    $destination = Join-Path $toolRoot $Name
    $executablePath = Join-Path $destination $Executable
    if (Test-Path -LiteralPath $executablePath) {
        return $executablePath
    }

    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    $archive = Join-Path $env:TEMP "yatouv8-$Name.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $archive -TimeoutSec 180

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    if ($actualHash -ne $Sha256) {
        throw "$Name archive checksum mismatch: expected $Sha256, got $actualHash"
    }

    Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
    if (!(Test-Path -LiteralPath $executablePath)) {
        throw "$Name executable not found after extraction: $executablePath"
    }
    return $executablePath
}

function Install-PinnedLibClang {
    $packageVersion = 'llvmorg-23-init-10931-g20b6ec66-11'
    $packageName = "libclang-$packageVersion.tar.xz"
    $toolRoot = Join-Path $env:LOCALAPPDATA "yatouv8\toolchain\chromium-libclang-$packageVersion"
    $libClang = Join-Path $toolRoot 'bin\libclang.dll'
    $expectedDllHash = '4183C395FD0F28497244FE1CAFDC5AAFC6AE99E443EA5CEE0F61A53462EE4E97'
    if (Test-Path -LiteralPath $libClang) {
        $actualDllHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $libClang).Hash
        if ($actualDllHash -eq $expectedDllHash) {
            return (Split-Path -Parent $libClang)
        }
        throw "Existing Chromium libclang checksum mismatch: $actualDllHash"
    }

    $url = "https://commondatastorage.googleapis.com/chromium-browser-clang/Win/$packageName"
    $expectedHash = 'ED2DDE0E28C10605EEE91904168556D3FF33364B9DF1B92EE6C25EC7B62EE8F5'
    $downloadRoot = Join-Path $env:LOCALAPPDATA 'yatouv8\downloads'
    $archive = Join-Path $downloadRoot $packageName
    New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null

    if (!(Test-Path -LiteralPath $archive) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $expectedHash) {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive -TimeoutSec 900
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    if ($actualHash -ne $expectedHash) {
        throw "Chromium libclang archive checksum mismatch: expected $expectedHash, got $actualHash"
    }

    New-Item -ItemType Directory -Force -Path $toolRoot | Out-Null
    & tar -xf $archive -C $toolRoot
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $libClang)) {
        throw "Failed to extract Chromium libclang into $toolRoot"
    }
    $actualDllHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $libClang).Hash
    if ($actualDllHash -ne $expectedDllHash) {
        throw "Chromium libclang checksum mismatch: expected $expectedDllHash, got $actualDllHash"
    }
    return (Split-Path -Parent $libClang)
}

$gn = Install-PinnedBuildTool `
    -Name 'gn' `
    -Url 'https://chrome-infra-packages.appspot.com/dl/gn/gn/windows-amd64/+/git_revision:3357c4f51b1a9e676378c695dd9c7e9911c35ee6' `
    -Sha256 '77E77E2F0D7BEA1992769343C68AB4312B8151C5A433F30301B365DD8E0F8687' `
    -Executable 'gn.exe'

$ninja = Install-PinnedBuildTool `
    -Name 'ninja' `
    -Url 'https://chrome-infra-packages.appspot.com/dl/infra/3pp/tools/ninja/windows-amd64/+/version:3@1.12.1.chromium.4' `
    -Sha256 '0CF1CB1B9D2B8D2D14A9FD38B984F17DD853115DB682880B21CEEE45E91DEB50' `
    -Executable 'ninja.exe'

$libClangPath = Install-PinnedLibClang

$preparationManifest = Join-Path $env:TEMP 'yatouv8-v8-source-preparation.json'
& $pythonCandidates[0] tools\build\prepare_v8_source.py `
    --cargo $cargo `
    --output $preparationManifest | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw 'V8 source dependency preparation failed'
}
$preparation = Get-Content -Raw -LiteralPath $preparationManifest | ConvertFrom-Json
$icuData = $preparation.icu_data.path
$chromiumRust = $preparation.chromium_rust.path

$env:V8_FROM_SOURCE = '1'
$env:PYTHON = $pythonCandidates[0]
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:CARGO_TERM_COLOR = 'always'
$crtStaticFlag = '-Ctarget-feature=+crt-static'
if (!$env:RUSTFLAGS -or !$env:RUSTFLAGS.Contains($crtStaticFlag)) {
    $env:RUSTFLAGS = (($env:RUSTFLAGS, $crtStaticFlag) |
        Where-Object { $_ }) -join ' '
}
$env:GN = $gn
$env:NINJA = $ninja
$env:LIBCLANG_PATH = $libClangPath
$clangResourceInclude = Join-Path (Resolve-Path '.').Path "target\$Profile\clang\lib\clang\23\include"
$resourceIncludeArg = "-isystem`"$clangResourceInclude`""
$env:BINDGEN_EXTRA_CLANG_ARGS = if ($env:BINDGEN_EXTRA_CLANG_ARGS) {
    "$resourceIncludeArg $env:BINDGEN_EXTRA_CLANG_ARGS"
} else {
    $resourceIncludeArg
}
if (!$env:NUM_JOBS) {
    $env:NUM_JOBS = '8'
}

$arguments = @(
    'run',
    '-p', 'yatou-core',
    '--example', 'v8_smoke',
    '--features', 'v8-runtime',
    '--locked'
)

if ($Profile -eq 'release') {
    $arguments += '--release'
}

Write-Host "Building V8 150.4.0 from source with PYTHON=$env:PYTHON"
Write-Host "PYTHONUTF8=$env:PYTHONUTF8"
Write-Host "RUSTFLAGS=$env:RUSTFLAGS"
Write-Host "GN=$env:GN"
Write-Host "NINJA=$env:NINJA"
Write-Host "LIBCLANG_PATH=$env:LIBCLANG_PATH"
Write-Host "BINDGEN_EXTRA_CLANG_ARGS=$env:BINDGEN_EXTRA_CLANG_ARGS"
Write-Host "ICU_DATA=$icuData"
Write-Host "CHROMIUM_RUST=$chromiumRust"
& $cargo @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
