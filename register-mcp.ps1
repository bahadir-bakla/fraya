$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'skill-creator-skill-lift\integrations\freya-mcp\.venv\Scripts\python.exe'
$taskServer = Join-Path $PSScriptRoot 'scripts\freya_dpapi_server.py'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
& codex mcp add freya -- $taskPython -X utf8 -B $taskServer
exit $LASTEXITCODE
