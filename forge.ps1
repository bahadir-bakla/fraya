param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForgeArgs
)

$ErrorActionPreference = 'Stop'
$repoPath = Join-Path $PSScriptRoot 'skill-creator-skill-lift'
$pythonPath = Join-Path $repoPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Local Python environment missing. See LOCAL_SETUP.txt.'
}
Push-Location -LiteralPath $repoPath
try {
    & $pythonPath -X utf8 -m agent_forge @ForgeArgs
    $forgeExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $forgeExitCode
