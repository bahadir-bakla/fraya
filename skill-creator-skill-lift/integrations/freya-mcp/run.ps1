[CmdletBinding()]
param(
    [string]$Workspace = '',
    [string]$Kit = '',
    [string]$EnvFile = '',
    [switch]$Health
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-AbsolutePath {
    param(
        [string]$Path,
        [string]$Label,
        [ValidateSet('Container', 'Leaf')]
        [string]$PathType
    )

    # Reject drive-relative (C:foo) and root-relative (\foo) paths too.
    if ($Path -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+(?:\\|$))') {
        throw "$Label must be an explicit absolute Windows path."
    }
    if (-not (Test-Path -LiteralPath $Path -PathType $PathType)) {
        throw "$Label does not exist or has the wrong path type."
    }
    return (Get-Item -LiteralPath $Path -Force).FullName
}

$serverExitCode = 1
$locationPushed = $false
try {
    $integrationRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
    if ([string]::IsNullOrWhiteSpace($Workspace)) {
        $Workspace = [System.IO.Path]::GetFullPath((Join-Path $integrationRoot '..\..\..'))
    }
    $workspacePath = Resolve-AbsolutePath -Path $Workspace -Label 'Workspace' -PathType Container
    if ([string]::IsNullOrWhiteSpace($Kit)) {
        $Kit = Join-Path $workspacePath 'competition-v3\build-the-builder'
    }
    $kitPath = Resolve-AbsolutePath -Path $Kit -Label 'Kit' -PathType Container

    $serverArgs = @('-B', '-m', 'freya_mcp.server', '--workspace', $workspacePath, '--kit', $kitPath)
    if ($PSBoundParameters.ContainsKey('EnvFile')) {
        $envFilePath = Resolve-AbsolutePath -Path $EnvFile -Label 'EnvFile' -PathType Leaf
        $serverArgs += @('--env-file', $envFilePath)
    }
    if ($Health) {
        $serverArgs += '--health'
    }

    $venvPython = Join-Path $integrationRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'The integration .venv is missing. Run install.ps1 after requirements.txt is ready.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $integrationRoot 'freya_mcp\server.py') -PathType Leaf)) {
        throw 'freya_mcp/server.py is not ready. The server owner supplies that entrypoint.'
    }

    # -m resolves freya_mcp from this directory, regardless of the caller's cwd.
    # Do not read credentials, discover .env files, or print banners to stdout.
    Push-Location -LiteralPath $integrationRoot
    $locationPushed = $true
    & $venvPython @serverArgs
    $serverExitCode = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine(('Freya MCP launcher: ' + $_.Exception.Message))
} finally {
    if ($locationPushed) {
        Pop-Location
    }
}

exit $serverExitCode
