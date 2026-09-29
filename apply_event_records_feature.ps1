$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Update-FileByRegex {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Replacement,
        [Parameter(Mandatory = $true)][string]$AlreadyAppliedPattern
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "File not found: $Path"
    }

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8

    if ($content -match $AlreadyAppliedPattern) {
        Write-Host "Already applied: $Path"
        return
    }

    if ($content -notmatch $Pattern) {
        throw "Expected navigation markup was not found in $Path. Stop and inspect the file manually."
    }

    $updated = [regex]::Replace(
        $content,
        $Pattern,
        $Replacement,
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )

    Set-Content -LiteralPath $Path -Value $updated -Encoding UTF8
    Write-Host "Updated: $Path"
}

$indexPattern = '<button\s+type="button"\s+class="quick-nav-button"\s+data-planned-feature="[^"]*"\s*>\s*(?<label>[^<]+?)\s*</button>'
$indexReplacement = '<a href="{% url ''dashboard:event_record_list'' %}" class="quick-nav-button">${label}</a>'
$indexApplied = 'dashboard:event_record_list'
Update-FileByRegex -Path '.\templates\dashboard\index.html' -Pattern $indexPattern -Replacement $indexReplacement -AlreadyAppliedPattern $indexApplied

$devicePattern = '<span\s+class="device-nav-button nav-cyan is-disabled"\s+aria-disabled="true"\s*>\s*(?<label>[^<]+?)\s*</span>'
$deviceReplacement = '<a href="{% url ''dashboard:event_record_list'' %}" class="device-nav-button nav-cyan">${label}</a>'
$deviceApplied = 'href="\{% url ''dashboard:event_record_list'' %\}" class="device-nav-button nav-cyan"'
Update-FileByRegex -Path '.\templates\dashboard\device_list.html' -Pattern $devicePattern -Replacement $deviceReplacement -AlreadyAppliedPattern $deviceApplied

$snapshotPattern = '<span\s+class="top-action-button nav-cyan is-disabled"\s+aria-disabled="true"\s*>\s*(?<label>[^<]+?)\s*</span>'
$snapshotReplacement = '<a href="{% url ''dashboard:event_record_list'' %}" class="top-action-button nav-cyan">${label}</a>'
$snapshotApplied = 'href="\{% url ''dashboard:event_record_list'' %\}" class="top-action-button nav-cyan"'
Update-FileByRegex -Path '.\templates\dashboard\event_snapshot_list.html' -Pattern $snapshotPattern -Replacement $snapshotReplacement -AlreadyAppliedPattern $snapshotApplied

$requirementsPath = '.\requirements.txt'
if (-not (Test-Path -LiteralPath $requirementsPath)) {
    throw "File not found: $requirementsPath"
}

$requirements = Get-Content -LiteralPath $requirementsPath -Raw -Encoding UTF8
if ($requirements -notmatch '(?m)^openpyxl==3\.1\.5\s*$') {
    if (-not $requirements.EndsWith("`n")) {
        $requirements += "`r`n"
    }
    $requirements += "openpyxl==3.1.5`r`n"
    Set-Content -LiteralPath $requirementsPath -Value $requirements -Encoding UTF8
    Write-Host "Added openpyxl==3.1.5 to requirements.txt"
} else {
    Write-Host "requirements.txt already contains openpyxl"
}

Write-Host ""
Write-Host "Event records feature navigation has been applied."
Write-Host "Next commands:"
Write-Host "python -m pip install -r requirements.txt"
Write-Host "python manage.py check"
Write-Host "python manage.py runserver"
