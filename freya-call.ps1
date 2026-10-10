[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Request,
    [Parameter(Mandatory = $true)][string]$OutFile
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'skill-creator-skill-lift\integrations\freya-mcp\.venv\Scripts\python.exe'
& $taskPython -X utf8 (Join-Path $PSScriptRoot 'scripts\freya_mcp_client.py') $Request --out $OutFile
exit $LASTEXITCODE
