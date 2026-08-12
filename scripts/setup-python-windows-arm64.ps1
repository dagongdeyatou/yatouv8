[CmdletBinding()]
param(
    [string]$Manifest = 'tools\build\python_windows_arm64_assets.json',
    [string]$Destination = (Join-Path ([IO.Path]::GetTempPath()) 'yatouv8-python-arm64'),
    [string]$GitHubOutput = $env:GITHUB_OUTPUT
)

$ErrorActionPreference = 'Stop'

function Get-VerifiedAsset {
    param(
        [Parameter(Mandatory)] [string]$Uri,
        [Parameter(Mandatory)] [string]$ExpectedSha256,
        [Parameter(Mandatory)] [string]$DestinationPath
    )

    $parent = Split-Path -Parent $DestinationPath
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path -LiteralPath $DestinationPath) {
        $actual = (Get-FileHash -LiteralPath $DestinationPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -eq $ExpectedSha256) {
            return (Resolve-Path -LiteralPath $DestinationPath).Path
        }
    }

    $temporary = "$DestinationPath.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $temporary
        $actual = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $ExpectedSha256) {
            throw "asset checksum mismatch for $Uri; expected $ExpectedSha256, got $actual"
        }
        Move-Item -LiteralPath $temporary -Destination $DestinationPath -Force
    }
    finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
    return (Resolve-Path -LiteralPath $DestinationPath).Path
}

$contract = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
if ($contract.schema -ne 'yatouv8.python-windows-arm64-assets.v1') {
    throw "unsupported Windows ARM64 Python asset schema: $($contract.schema)"
}
if ($contract.runtime.python_version -ne '3.10' -or $contract.runtime.architecture -ne 'arm64') {
    throw 'this bootstrap is restricted to native Windows ARM64 CPython 3.10'
}

$root = Join-Path $Destination $contract.runtime.version
$downloads = Join-Path $Destination 'downloads'
$runtimeArchive = Get-VerifiedAsset `
    -Uri $contract.runtime.url `
    -ExpectedSha256 $contract.runtime.sha256 `
    -DestinationPath (Join-Path $downloads "python-$($contract.runtime.version)-embed-arm64.zip")
$pipWheel = Get-VerifiedAsset `
    -Uri $contract.pip.url `
    -ExpectedSha256 $contract.pip.sha256 `
    -DestinationPath (Join-Path $downloads "pip-$($contract.pip.version)-py3-none-any.whl")

# The job gets a fresh RUNNER_TEMP. Extract into a versioned directory and
# enable only the paths needed by the embeddable distribution.
New-Item -ItemType Directory -Force -Path $root | Out-Null
Expand-Archive -LiteralPath $runtimeArchive -DestinationPath $root -Force
$pth = Join-Path $root 'python310._pth'
@('python310.zip', '.', 'Lib\site-packages') | Set-Content -LiteralPath $pth -Encoding ascii
$sitePackages = Join-Path $root 'Lib\site-packages'
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

$python = Join-Path $root 'python.exe'
if (!(Test-Path -LiteralPath $python)) {
    throw "embedded Python executable not found: $python"
}
& $python -c `
    'import pathlib,sys,zipfile; pathlib.Path(sys.argv[2]).mkdir(parents=True, exist_ok=True); zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' `
    $pipWheel $sitePackages
if ($LASTEXITCODE -ne 0) { throw 'pip wheel bootstrap failed' }

$runtimeContract = (& $python -c `
    'import json,platform,struct,sys; print(json.dumps({"version": f"{sys.version_info.major}.{sys.version_info.minor}", "machine": platform.machine().lower(), "pointer_bits": struct.calcsize("P") * 8}))') |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'native ARM64 Python runtime inspection failed' }
if ($runtimeContract.version -ne '3.10' -or $runtimeContract.pointer_bits -ne 64) {
    throw "unexpected Python runtime contract: $($runtimeContract | ConvertTo-Json -Compress)"
}
if ($runtimeContract.machine -notin @('arm64', 'aarch64')) {
    throw "Python runtime is not native ARM64: $($runtimeContract.machine)"
}
& $python -m pip --version | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'embedded pip bootstrap verification failed' }

$resolvedPython = (Resolve-Path -LiteralPath $python).Path
if ($GitHubOutput) {
    "python-path=$resolvedPython" | Out-File -FilePath $GitHubOutput -Encoding utf8 -Append
}

[pscustomobject]@{
    schema = 'yatouv8.python-windows-arm64-bootstrap.v1'
    python_path = $resolvedPython
    version = $runtimeContract.version
    machine = $runtimeContract.machine
    pointer_bits = $runtimeContract.pointer_bits
} | ConvertTo-Json -Compress
