[CmdletBinding()]
param(
    [string]$PythonExecutable = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$integrationRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$requirementsPath = Join-Path $integrationRoot 'requirements.txt'
$lockPath = Join-Path $integrationRoot 'requirements-lock.txt'
$venvRoot = Join-Path $integrationRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw 'requirements.txt is not ready. The server owner supplies the pinned dependencies.'
}

# Prefer the server owner's transitive lock, including UTF-8 files with a BOM.
$installRequirements = $requirementsPath
if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
    $installRequirements = $lockPath
}

# Check the agreed pins without changing either dependency file.
$expectedPins = @('mcp==1.27.1', 'httpx==0.28.1', 'python-dotenv==1.0.1')
foreach ($dependencyFile in @($requirementsPath, $installRequirements) | Select-Object -Unique) {
    $requirementsText = Get-Content -LiteralPath $dependencyFile -Raw
    foreach ($pin in $expectedPins) {
        $pinPattern = '(?m)^\s*' + [regex]::Escape($pin) + '\s*(?:#.*)?$'
        if ($requirementsText -notmatch $pinPattern) {
            throw ('Dependency file must contain the agreed pin {0}: {1}' -f $pin, $dependencyFile)
        }
    }
}

if (Test-Path -LiteralPath $venvRoot) {
    $venvItem = Get-Item -LiteralPath $venvRoot -Force
    if (-not $venvItem.PSIsContainer -or
        ($venvItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw '.venv must be a regular directory inside this integration.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $venvRoot 'pyvenv.cfg') -PathType Leaf) -or
        -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'The existing .venv is incomplete. Resolve it explicitly before rerunning install.ps1.'
    }
} else {
    $basePython = (Get-Command -Name $PythonExecutable -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    & $basePython -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'Use Python 3.11 or newer with -PythonExecutable.'
    }
    & $basePython -I -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed (exit $LASTEXITCODE)."
    }
}

# Refuse a reused interpreter that can expose system packages or install elsewhere.
& $venvPython -I -B -c "import pathlib, sys; root = pathlib.Path(sys.argv[1]).resolve(); active = pathlib.Path(sys.prefix).resolve(); cfg = (root / 'pyvenv.cfg').read_text().lower(); sys.exit(0 if active == root and sys.prefix != sys.base_prefix and sys.version_info >= (3, 11) and 'include-system-site-packages = false' in cfg else 1)" $venvRoot
if ($LASTEXITCODE -ne 0) {
    throw '.venv must use its own Python 3.11+ interpreter without system site-packages.'
}

# The explicit interpreter/prefix and disabled cache keep installation local.
& $venvPython -I -m pip --isolated --require-virtualenv --disable-pip-version-check install --no-user --no-cache-dir --prefix $venvRoot --requirement $installRequirements
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed (exit $LASTEXITCODE). Retry only this .venv with permitted network access."
}
& $venvPython -I -m pip --isolated --disable-pip-version-check check
if ($LASTEXITCODE -ne 0) {
    throw "Dependency consistency check failed (exit $LASTEXITCODE)."
}

Write-Output "Dependencies installed in $venvRoot."
Write-Output 'Freya remains unconfigured until credentials are supplied, project configuration is applied, and Codex reloads.'
