param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$integrationRoot = $PSScriptRoot
$pin = Get-Content -LiteralPath (Join-Path $integrationRoot 'upstream.json') -Raw | ConvertFrom-Json
$vendorRoot = Join-Path $integrationRoot 'vendor\MiroFish'
$runtimeRoot = Join-Path $integrationRoot 'runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$env:UV_CACHE_DIR = Join-Path $runtimeRoot 'uv-cache'
$env:npm_config_cache = Join-Path $runtimeRoot 'npm-cache'

if (!(Test-Path -LiteralPath (Join-Path $vendorRoot '.git'))) {
    & git clone --no-checkout --depth 1 $pin.repository $vendorRoot
    if ($LASTEXITCODE -ne 0) { throw 'MiroFish clone failed.' }
    & git -C $vendorRoot fetch --depth 1 origin $pin.commit
    if ($LASTEXITCODE -ne 0) { throw 'Pinned MiroFish fetch failed.' }
    & git -C $vendorRoot checkout --detach $pin.commit
    if ($LASTEXITCODE -ne 0) { throw 'Pinned MiroFish checkout failed.' }
}
$actualPin = & git -C $vendorRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actualPin -ne $pin.commit) {
    throw 'Existing vendor checkout differs from upstream.json; no reset was attempted.'
}
$vendorChanges = & git -C $vendorRoot status --porcelain --untracked-files=no
if ($vendorChanges) { throw 'Vendor source has tracked modifications; restore or inspect it before installation.' }

Push-Location (Join-Path $vendorRoot 'backend')
try {
    & uv sync --locked --no-dev --python $Python
    if ($LASTEXITCODE -ne 0) { throw 'MiroFish backend installation failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $vendorRoot 'frontend')
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'MiroFish frontend installation failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'MiroFish frontend build failed.' }
} finally { Pop-Location }
Write-Output ('Installed pinned MiroFish: ' + $actualPin)
Write-Output 'Run python integrations/mirofish/probe_runtime.py from the fraya root for credential-free readiness checks.'
