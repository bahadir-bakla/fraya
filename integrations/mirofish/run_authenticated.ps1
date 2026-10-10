param(
    [Parameter(Mandatory=$true)][string]$ProxyConfig,
    [string]$ProxyExecutable,
    [string]$Model = 'gpt-6-luna',
    [ValidateSet('services','smoke')][string]$Action = 'services',
    [ValidateRange(1,65535)][int]$BackendPort = 5001
)
$ErrorActionPreference = 'Stop'
$mirofishPython = Join-Path $PSScriptRoot 'vendor\MiroFish\backend\.venv\Scripts\python.exe'
$mirofishHelper = Join-Path $PSScriptRoot 'authenticated_runtime.py'
$mirofishRuntime = Join-Path $PSScriptRoot 'runtime'
New-Item -ItemType Directory -Force -Path $mirofishRuntime | Out-Null
$ProxyConfig = (Resolve-Path -LiteralPath $ProxyConfig).Path
if (!$ProxyExecutable) { $ProxyExecutable = Join-Path (Split-Path -Parent $ProxyConfig) 'cli-proxy-api.exe' }
$mirofishSettingsText = & $mirofishPython -B $mirofishHelper settings --proxy-config $ProxyConfig
if ($LASTEXITCODE -ne 0) { throw 'Cannot load the explicitly designated loopback proxy configuration.' }
$mirofishSettings = $mirofishSettingsText | ConvertFrom-Json
$mirofishProxyPort = ([Uri]$mirofishSettings.base_url).Port

function Wait-LocalListener([int]$Port, [int]$Seconds = 30) {
    $mirofishDeadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $mirofishDeadline) {
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Local service did not bind to port $Port within $Seconds seconds. Review redacted integration runtime logs."
}

if (!(Get-NetTCPConnection -LocalPort $mirofishProxyPort -State Listen -ErrorAction SilentlyContinue)) {
    $ProxyExecutable = (Resolve-Path -LiteralPath $ProxyExecutable).Path
    $mirofishArguments = @(('"'+$mirofishHelper+'"'), 'proxy', '--proxy-config', ('"'+$ProxyConfig+'"'),
                          '--proxy-executable', ('"'+$ProxyExecutable+'"'))
    $mirofishProxy = Start-Process -FilePath $mirofishPython -ArgumentList $mirofishArguments -WorkingDirectory $mirofishRuntime -WindowStyle Hidden -RedirectStandardOutput (Join-Path $mirofishRuntime 'cliproxy.stdout.log') -RedirectStandardError (Join-Path $mirofishRuntime 'cliproxy.stderr.log') -PassThru
    Wait-LocalListener $mirofishProxyPort
}
# A model inventory alone does not authorize starting the authenticated backend.
& $mirofishPython -B $mirofishHelper probe --proxy-config $ProxyConfig --model $Model
if ($LASTEXITCODE -ne 0) { throw 'An actual authenticated completion failed; backend launch was not attempted.' }

if (!(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)) {
    $mirofishArguments = @(('"'+$mirofishHelper+'"'), 'backend', '--proxy-config', ('"'+$ProxyConfig+'"'), '--port', "$BackendPort")
    $mirofishBackend = Start-Process -FilePath $mirofishPython -ArgumentList $mirofishArguments -WorkingDirectory $mirofishRuntime -WindowStyle Hidden -RedirectStandardOutput (Join-Path $mirofishRuntime 'mirofish.stdout.log') -RedirectStandardError (Join-Path $mirofishRuntime 'mirofish.stderr.log') -PassThru
    Wait-LocalListener $BackendPort 60
} else {
    $mirofishRecordPath = Join-Path $mirofishRuntime 'backend-service.json'
    if (!(Test-Path -LiteralPath $mirofishRecordPath)) { throw 'An unrecognized service already occupies the requested backend port.' }
    $mirofishRecord = Get-Content -LiteralPath $mirofishRecordPath -Raw | ConvertFrom-Json
    $mirofishListener = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction Stop)
    if ($mirofishRecord.base_url -ne "http://127.0.0.1:$BackendPort" -or $mirofishRecord.llm_base_url -ne $mirofishSettings.base_url -or $mirofishRecord.llm_model -ne $Model -or $mirofishRecord.startup_validation_bypassed -or $mirofishRecord.pid -notin $mirofishListener.OwningProcess) {
        throw 'The running backend does not match this scoped authenticated launch.'
    }
}
$mirofishHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 10
if ($mirofishHealth.status -ne 'ok') { throw 'The normal backend health check failed.' }
Write-Output "Authenticated services ready: MiroFish http://127.0.0.1:$BackendPort ; proxy $($mirofishSettings.base_url) ; model $Model"
if ($Action -eq 'smoke') {
    & $mirofishPython -B (Join-Path $PSScriptRoot 'run_authenticated_smoke.py') --proxy-config $ProxyConfig --backend-base-url "http://127.0.0.1:$BackendPort" --max-agents 2 --phase-timeout 240
    exit $LASTEXITCODE
}
