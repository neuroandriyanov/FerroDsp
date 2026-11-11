param([string]$PythonExe='', [switch]$NoConnect)
$ErrorActionPreference='Stop'
if (-not $PythonExe) {
    $candidate = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) { $PythonExe=$candidate }
}
if (-not $PythonExe -and (Get-Command py -ErrorAction SilentlyContinue)) {
    $PythonExe = & py -3.12 -c 'import sys; print(sys.executable)'
}
if (-not $PythonExe) {
    # Optional local preference; never copied into a portable release.
    $runtimeFile = Join-Path $PSScriptRoot 'local\runtime.json'
    if (Test-Path -LiteralPath $runtimeFile) {
        $savedRuntime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
        if (Test-Path -LiteralPath $savedRuntime.python_executable) { $PythonExe=$savedRuntime.python_executable }
    }
}
if (-not $PythonExe) { throw 'Для запуска исходников создайте pc_app\.venv по README. Готовый ZIP с EXE не требует Python.' }
$entry = Join-Path $PSScriptRoot 'app.py'
$appArguments = @($entry)
if (-not $NoConnect) { $appArguments += '--connect' }
# Keep the console for dependency/startup errors in a source checkout.
& $PythonExe @appArguments
exit $LASTEXITCODE
