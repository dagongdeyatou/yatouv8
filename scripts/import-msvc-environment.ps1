[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('amd64', 'arm64')]
    [string]$Architecture
)

$ErrorActionPreference = 'Stop'
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
