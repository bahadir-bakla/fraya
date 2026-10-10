param([ValidateSet('backend','frontend')][string]$Service = 'backend')
$ErrorActionPreference = 'Stop'
$pin = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'upstream.json') -Raw | ConvertFrom-Json
$vendorRoot = Join-Path $PSScriptRoot 'vendor\MiroFish'
$actualPin = & git -C $vendorRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actualPin -ne $pin.commit) { throw 'Run install.ps1 to prepare the pinned upstream checkout.' }
if ($Service -eq 'backend') {
    # Prevent python-dotenv from searching unrelated parent .env files.
    $mirofishDotenvExists = Test-Path -LiteralPath (Join-Path $vendorRoot '.env')
    $env:PYTHON_DOTENV_DISABLED = if ($mirofishDotenvExists) { '0' } else { '1' }
    if (!$env:FLASK_HOST) { $env:FLASK_HOST = '127.0.0.1' }
    if (!$env:FLASK_PORT) { $env:FLASK_PORT = '5001' }
    $env:FLASK_DEBUG = 'False'
    $backendRoot = Join-Path $vendorRoot 'backend'
    $backendPython = Join-Path $backendRoot '.venv\Scripts\python.exe'
    Push-Location $backendRoot
    try { & $backendPython run.py; $serviceExit = $LASTEXITCODE } finally { Pop-Location }
} else {
    # Upstream vite.config.js opens a browser. Override that in memory without editing vendor source.
    Push-Location (Join-Path $vendorRoot 'frontend')
    try {
        & node --input-type=module -e "import {createServer} from 'vite'; const server=await createServer({server:{host:'127.0.0.1',port:3000,strictPort:true,open:false}}); await server.listen(); server.printUrls();"
        $serviceExit = $LASTEXITCODE
    } finally { Pop-Location }
}
exit $serviceExit
