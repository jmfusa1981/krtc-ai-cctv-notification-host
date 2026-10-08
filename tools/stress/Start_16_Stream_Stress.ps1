param(
    [string]$FfmpegPath = "C:\Program Files\ffmpeg\bin\ffmpeg.exe"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Stress_Common.ps1")
$stopRequestPath = Get-StressStopRequestPath
if (Test-Path -LiteralPath $stopRequestPath -PathType Leaf) {
    Remove-Item -LiteralPath $stopRequestPath -Force
}
Start-StressPublishers -Count 16 -FfmpegPath $FfmpegPath
