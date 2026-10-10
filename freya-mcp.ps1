[CmdletBinding()]
param([switch]$Health)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'skill-creator-skill-lift\integrations\freya-mcp\.venv\Scripts\python.exe'
$taskServer = Join-Path $PSScriptRoot 'scripts\freya_dpapi_server.py'
$taskArgs = @('-X', 'utf8', '-B', $taskServer)
if ($Health) { $taskArgs += '--health' }
& $taskPython @taskArgs
exit $LASTEXITCODE
