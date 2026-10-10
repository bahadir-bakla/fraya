param(
    [Parameter(Mandatory = $true)][string[]]$Briefs,
    [string]$ToolApi = 'competition-v3/build-the-builder/tools/openapi.json',
    [string]$Out = 'local-runs/builder',
    [string]$Slot = 'codex-builder-rd',
    [string]$Cases = '',
    [string]$Style = '',
    [int]$Reps = 1,
    [int]$Repairs = 2,
    [int]$BudgetSeconds = 1800,
    [string]$Model = 'gpt-6.1-sol',
    [switch]$CompileOnly,
    [switch]$AllowSourceGaps,
    [string]$PolicyCheckpoint = '',
    [string]$WorkflowCheckpoint = ''
)
$ErrorActionPreference = 'Stop'
$projectPath = Join-Path $PSScriptRoot 'skill-creator-skill-lift'
$pythonPath = Join-Path $projectPath '.venv/Scripts/python.exe'
$briefPaths = @($Briefs | ForEach-Object { (Resolve-Path -LiteralPath $_).Path })
$apiPath = (Resolve-Path -LiteralPath $ToolApi).Path
$outPath = if ([IO.Path]::IsPathRooted($Out)) { [IO.Path]::GetFullPath($Out) } else { [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Out)) }
$kitPath = Join-Path $PSScriptRoot 'competition-v3/build-the-builder'
$builderArgs = @('-X', 'utf8', '-m', 'agent_forge', 'build-live') + $briefPaths + @(
    '--tool-api', $apiPath, '--kit', $kitPath, '--out', $outPath, '--slot', $Slot,
    '--cases', $Cases, '--style', $Style, '--reps', $Reps, '--repairs', $Repairs,
    '--budget-seconds', $BudgetSeconds, '--model', $Model)
if ($CompileOnly) { $builderArgs += '--compile-only' }
if ($AllowSourceGaps) { $builderArgs += '--allow-source-gaps' }
if ($PolicyCheckpoint) { $builderArgs += @('--policy-checkpoint', (Resolve-Path -LiteralPath $PolicyCheckpoint).Path) }
if ($WorkflowCheckpoint) { $builderArgs += @('--workflow-checkpoint', (Resolve-Path -LiteralPath $WorkflowCheckpoint).Path) }
Push-Location -LiteralPath $projectPath
try {
    & $pythonPath @builderArgs
    $builderExit = $LASTEXITCODE
}
finally { Pop-Location }
exit $builderExit
