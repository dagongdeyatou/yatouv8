[CmdletBinding()]
param(
    [ValidateSet('debug', 'release')]
    [string]$Profile = 'debug',
    [string]$Target = ''
)

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'

if (!(Test-Path -LiteralPath $cargo)) {
    throw "cargo not found at $cargo"
}

$pythonCandidates = @(
    @(
        $env:PYTHON,
        'C:\ProgramData\anaconda3\python.exe',
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
)

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

function Import-VisualStudioEnvironment {
    param([Parameter(Mandatory)] [ValidateSet('amd64', 'arm64')] [string]$Architecture)

    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (!(Test-Path -LiteralPath $vswhere)) {
        throw "Visual Studio locator not found: $vswhere"
    }
    $vswhereArguments = @(
        '-latest', '-version', '[17.0,18.0)', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64'
    )
    if ($Architecture -eq 'arm64') {
        $vswhereArguments += 'Microsoft.VisualStudio.Component.VC.Tools.ARM64'
    }
    $vswhereArguments += @('-property', 'installationPath')
    $installation = (& $vswhere @vswhereArguments | Select-Object -First 1)
    if (!$installation) {
        throw "Visual Studio 2022 C++ build tools for $Architecture were not found"
    }
    Write-Host "VISUAL_STUDIO_2022=$installation"
    $vsDevCmd = Join-Path $installation 'Common7\Tools\VsDevCmd.bat'
    if (!(Test-Path -LiteralPath $vsDevCmd)) {
        throw "VsDevCmd.bat not found: $vsDevCmd"
    }

    $batch = "call `"$vsDevCmd`" -no_logo -arch=$Architecture -host_arch=amd64 >nul && set"
    $environment = & $env:ComSpec /d /s /c $batch
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to initialize Visual Studio for $Architecture"
    }
    foreach ($line in $environment) {
        if ($line -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
        }
    }
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

$rustc = Join-Path (Split-Path -Parent $cargo) 'rustc.exe'
if (!(Test-Path -LiteralPath $rustc)) {
    throw "rustc not found next to cargo: $rustc"
}
$rustcVersion = (& $rustc -vV) -join "`n"
if ($LASTEXITCODE -ne 0 -or $rustcVersion -notmatch '(?m)^host:\s*(\S+)\s*$') {
    throw 'Unable to determine the Rust host target'
}
$hostTarget = $Matches[1]
$effectiveTarget = if ($Target) { $Target } else { $hostTarget }
$isCross = $effectiveTarget -ne $hostTarget
$targetMsvcArchitecture = switch -Regex ($effectiveTarget) {
    '^aarch64-pc-windows-msvc$' { 'arm64'; break }
    '^x86_64-pc-windows-msvc$' { 'amd64'; break }
    default { throw "Unsupported Windows V8 target: $effectiveTarget" }
}
# Cross builds still execute GN, bindgen, Torque, and Rust build scripts on
# the x64 runner.  Build the V8-containing rlib under an x64 developer
# environment first; Chromium selects the ARM64 target toolchain from GN's
# target_cpu.  The final target executable/wheel is linked in a second stage
# after switching to the ARM64 developer environment.
$v8BuildMsvcArchitecture = if ($isCross) { 'amd64' } else { $targetMsvcArchitecture }
Import-VisualStudioEnvironment -Architecture $v8BuildMsvcArchitecture

if ($Target) {
    & (Join-Path (Split-Path -Parent $cargo) 'rustup.exe') target add `
        --toolchain '1.97.1' $Target | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Rust target $Target"
    }
}

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
# Chromium GN emits long relative dependency paths for its Rust sysroot.  A
# normal checkout-local Cargo target directory can exceed Win32's 260-character
# path limit before the `..` components are normalized, even when the final
# absolute path is shorter.  Keep the Windows V8/Cargo output root deliberately
# short; callers can override it when their build volume has another short path.
if (!$env:CARGO_TARGET_DIR) {
    $env:CARGO_TARGET_DIR = Join-Path $env:SystemDrive 'y8t'
}
New-Item -ItemType Directory -Force -Path $env:CARGO_TARGET_DIR | Out-Null
$targetProfileRoot = if ($Target) {
    Join-Path $env:CARGO_TARGET_DIR "$Target\$Profile"
} else {
    Join-Path $env:CARGO_TARGET_DIR $Profile
}
$clangResourceInclude = Join-Path $targetProfileRoot 'clang\lib\clang\23\include'
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
    $(if ($isCross) { 'build' } else { 'run' }),
    '-p', 'yatou-core',
    '--example', 'v8_smoke',
    '--features', 'v8-runtime',
    '--locked'
)

if ($Profile -eq 'release') {
    $arguments += '--release'
}
if ($Target) {
    $arguments += @('--target', $Target)
}

Write-Host "Building V8 150.4.0 from source for TARGET=$effectiveTarget (HOST=$hostTarget)"
Write-Host "PYTHON=$env:PYTHON"
Write-Host "PYTHONUTF8=$env:PYTHONUTF8"
Write-Host "RUSTFLAGS=$env:RUSTFLAGS"
Write-Host "GN=$env:GN"
Write-Host "NINJA=$env:NINJA"
Write-Host "LIBCLANG_PATH=$env:LIBCLANG_PATH"
Write-Host "CARGO_TARGET_DIR=$env:CARGO_TARGET_DIR"
Write-Host "BINDGEN_EXTRA_CLANG_ARGS=$env:BINDGEN_EXTRA_CLANG_ARGS"
Write-Host "ICU_DATA=$icuData"
Write-Host "CHROMIUM_RUST=$chromiumRust"
if ($isCross) {
    $v8Arguments = @(
        'build',
        '-p', 'yatou-core',
        '--lib',
        '--features', 'v8-runtime',
        '--locked'
    )
    if ($Profile -eq 'release') {
        $v8Arguments += '--release'
    }
    $v8Arguments += @('--target', $Target)
    Write-Host "Building target V8 rlib with x64 host tools before final cross link"
    & $cargo @v8Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    Import-VisualStudioEnvironment -Architecture $targetMsvcArchitecture
    Write-Host "Switched Visual Studio environment to $targetMsvcArchitecture for final target link"
}
& $cargo @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

[pscustomobject]@{
    host_target = $hostTarget
    target = $effectiveTarget
    profile = $Profile
    cross_compiled = $isCross
    smoke_executed = !$isCross
} | ConvertTo-Json
