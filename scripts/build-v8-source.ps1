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

function Get-V8RegistrySourceRoot {
    $cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE '.cargo' }
    $registryRoot = Join-Path $cargoHome 'registry\src'
    $v8Roots = Get-ChildItem -LiteralPath $registryRoot -Directory -ErrorAction Stop |
        ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Directory -Filter 'v8-150.4.0' }
    $v8Root = $v8Roots | Select-Object -First 1
    if (!$v8Root) {
        throw 'v8 150.4.0 source was not found in the Cargo registry cache'
    }
    return $v8Root.FullName
}

function Install-PinnedIcuData {
    param([Parameter(Mandatory)] [string]$V8Root)

    $icuData = Join-Path $V8Root 'third_party\icu\common\icudtl.dat'
    $expectedHash = '1CF67874B5A87A8363A86FB3F81E3CBBED54D389062DAB8FB52308D5CF8C8612'
    if (Test-Path -LiteralPath $icuData) {
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $icuData).Hash
        if ($actualHash -eq $expectedHash) {
            return $icuData
        }
        throw "Existing ICU data checksum mismatch: $actualHash"
    }

    $url = 'https://chromium.googlesource.com/chromium/deps/icu/+/ee5f27adc28bd3f15b2c293f726d14d2e336cbd5/common/icudtl.dat?format=TEXT'
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 180
    $encoded = if ($response.Content -is [byte[]]) {
        [Text.Encoding]::ASCII.GetString($response.Content)
    } else {
        [string]$response.Content
    }
    $bytes = [Convert]::FromBase64String($encoded)
    $actualHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
    if ($actualHash -ne $expectedHash) {
        throw "ICU data checksum mismatch: expected $expectedHash, got $actualHash"
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $icuData) | Out-Null
    [IO.File]::WriteAllBytes($icuData, $bytes)
    return $icuData
}

function Install-PinnedChromiumRustSources {
    param([Parameter(Mandatory)] [string]$V8Root)

    $target = Join-Path $V8Root 'third_party\rust'
    $probe = Join-Path $target 'chromium_crates_io\vendor\icu_calendar_data-v2\build.rs'
    if (Test-Path -LiteralPath $probe) {
        return $target
    }

    $url = 'https://chromium.googlesource.com/chromium/src/third_party/rust/+archive/26e8ff47f18a8d28d6187a04b6a16cb7332356f8.tar.gz'
    $expectedHash = '23326DC97CC82B2E0B551F823C8AFB0A91524ABCFE078C50D38DBDF37FE0EB92'
    $downloadRoot = Join-Path $env:LOCALAPPDATA 'yatouv8\downloads'
    $archive = Join-Path $downloadRoot 'chromium-third-party-rust-26e8ff47.tar.gz'
    New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null

    if (!(Test-Path -LiteralPath $archive) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $expectedHash) {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive -TimeoutSec 600
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    if ($actualHash -ne $expectedHash) {
        throw "Chromium Rust archive checksum mismatch: expected $expectedHash, got $actualHash"
    }

    New-Item -ItemType Directory -Force -Path $target | Out-Null
    & tar -xzf $archive -C $target
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $probe)) {
        throw 'Failed to hydrate Chromium Rust vendor sources'
    }
    return $target
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

& $cargo fetch --locked
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
$v8Root = Get-V8RegistrySourceRoot
$icuData = Install-PinnedIcuData -V8Root $v8Root
$chromiumRust = Install-PinnedChromiumRustSources -V8Root $v8Root

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
