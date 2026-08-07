[CmdletBinding()]
param(
    [string]$Model = '.reference-cache\inside-recaptcha\model.js',
    [string]$Bytecode = '.reference-cache\inside-recaptcha\enc'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$python = 'C:\ProgramData\anaconda3\python.exe'

Push-Location $root
try {
    & .\scripts\build-v8-source.ps1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $chromeResult = & $python .\tools\google-vm-collector\collector.py `
        --model $Model --bytecode $Bytecode --output-root .\.yatou\evidence
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $runDir = ($chromeResult | ConvertFrom-Json).run_dir

    $env:V8_FROM_SOURCE = '1'
    $env:PYTHON = $python
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:RUSTFLAGS = '-Ctarget-feature=+crt-static'
    $env:GN = Join-Path $env:LOCALAPPDATA 'yatouv8\toolchain\v8-150.4.0\gn\gn.exe'
    $env:NINJA = Join-Path $env:LOCALAPPDATA 'yatouv8\toolchain\v8-150.4.0\ninja\ninja.exe'
    $env:LIBCLANG_PATH = Join-Path $env:LOCALAPPDATA 'yatouv8\toolchain\chromium-libclang-llvmorg-23-init-10931-g20b6ec66-11\bin'
    $include = Join-Path $root 'target\debug\clang\lib\clang\23\include'
    $env:BINDGEN_EXTRA_CLANG_ARGS = "-isystem`"$include`""

    $tempTrace = Join-Path $root '.yatou\evidence\.tmp\m6-yatou.ndjson'
    $tempResult = Join-Path $root '.yatou\evidence\.tmp\m6-yatou-result.json'
    & $cargo run -q -p yatou-core --example botguard_m6 --features v8-runtime --locked -- `
        $Model $Bytecode $tempTrace $tempResult
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $python .\tools\google-vm-collector\finalize.py `
        --run-dir $runDir --yatou-trace $tempTrace --yatou-result $tempResult `
        --model $Model --bytecode $Bytecode
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Remove-Item -LiteralPath $tempTrace, $tempResult -Force -ErrorAction SilentlyContinue
} finally {
    Pop-Location
}
