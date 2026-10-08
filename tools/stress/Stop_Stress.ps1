$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Stress_Common.ps1")

$runtimeDirectory = Get-StressRuntimeDirectory
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
Set-Content -LiteralPath (Get-StressStopRequestPath) -Value "stop" -Encoding ascii
Stop-AllStressPublishers
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (-not (Test-Path -LiteralPath (Get-StressStopRequestPath) -PathType Leaf)) {
        break
    }
    Start-Sleep -Milliseconds 100
}
if (Test-Path -LiteralPath (Get-StressStopRequestPath) -PathType Leaf) {
    Remove-Item -LiteralPath (Get-StressStopRequestPath) -Force
}
Write-Host "Stress publishers stopped. Production bridges and MediaMTX were not changed."
