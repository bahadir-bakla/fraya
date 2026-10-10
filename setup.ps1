[CmdletBinding()]
param([string]$PythonExecutable = 'python')
$ErrorActionPreference = 'Stop'
$taskRepo = Join-Path $PSScriptRoot 'skill-creator-skill-lift'
$taskPython = Join-Path $taskRepo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $PythonExecutable -m venv (Join-Path $taskRepo '.venv')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-local.txt')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $taskRepo 'integrations\freya-mcp\install.ps1') -PythonExecutable $PythonExecutable
exit $LASTEXITCODE
