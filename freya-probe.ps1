$ErrorActionPreference = 'Stop'
$taskKeyPath = Join-Path $PSScriptRoot '.local-secrets\freya-key.dpapi'
$taskSecureValue = ConvertTo-SecureString (Get-Content -LiteralPath $taskKeyPath -Raw).Trim()
$taskCredential = [System.Management.Automation.PSCredential]::new('freya', $taskSecureValue)
$taskPreviousKey = $env:FREYA_API_KEY
try {
    $env:FREYA_API_KEY = $taskCredential.GetNetworkCredential().Password
    & (Join-Path $PSScriptRoot 'skill-creator-skill-lift\.venv\Scripts\python.exe') -X utf8 (Join-Path $PSScriptRoot 'scripts\freya_connection_probe.py')
    $taskResult = $LASTEXITCODE
} finally {
    $env:FREYA_API_KEY = $taskPreviousKey
    Remove-Variable taskCredential, taskSecureValue
}
exit $taskResult
