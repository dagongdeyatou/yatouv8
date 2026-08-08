[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'

if (!(Test-Path -LiteralPath $cargo)) {
    throw "cargo not found at $cargo"
}

function Invoke-CargoStep {
    param([Parameter(Mandatory)] [string[]]$Arguments)

    & $cargo @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "cargo $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Resolve-Python {
    $candidates = @(
        'C:\ProgramData\anaconda3\python.exe',
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    throw 'Python not found; required for chrome-collector checks'
}

function Invoke-PythonStep {
    param([Parameter(Mandatory)] [string[]]$Arguments)

    $python = Resolve-Python
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Invoke-CargoStep -Arguments @('fmt', '--all', '--', '--check')
Invoke-CargoStep -Arguments @('check', '--workspace', '--all-targets')
Invoke-CargoStep -Arguments @('test', '--workspace')
Invoke-CargoStep -Arguments @('clippy', '--workspace', '--all-targets', '--', '-D', 'warnings')
Invoke-PythonStep -Arguments @(
    '-m', 'compileall', '-q',
    'tools/chrome-collector',
    'tools/google-vm-collector',
    'tools/google-vm-corpus',
    'tools/host-conformance',
    'tools/release',
    'tools/semantic-conformance',
    'tools/surface-codegen',
    'tools/trace-inspector'
)
Invoke-PythonStep -Arguments @('-m', 'unittest', 'discover', 'tools/chrome-collector/tests', '-v')
Invoke-PythonStep -Arguments @('-m', 'unittest', 'discover', 'tools/surface-codegen/tests', '-v')
Invoke-PythonStep -Arguments @('-m', 'unittest', 'discover', 'tools/trace-inspector/tests', '-v')
