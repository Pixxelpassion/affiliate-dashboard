<#
.SYNOPSIS
    Registriert eine woechentliche Aufgabe im Windows Task Scheduler,
    die das Affiliate-Einnahmen-Dashboard aktualisiert.

.DESCRIPTION
    Ruft Aktualisieren.bat (Datenabruf + dashboard.html) jeden Montag um 07:00 Uhr
    unter dem aktuellen Benutzerkonto auf. Erneutes Ausfuehren ueberschreibt die
    bestehende Aufgabe (z. B. um Tag/Uhrzeit zu aendern).

    Hinweis: Mit source="gsheet" laeuft der Refresh automatisch (solange das Sheet
    gepflegt wird). Mit source="csv" wirkt der Task nur, wenn frische Exporte in
    data/inbox liegen.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "Affiliate-Einnahmen-Dashboard",
    [DayOfWeek]$Day = [DayOfWeek]::Monday,
    [string]$Time = "07:00"
)

$bat = Join-Path $PSScriptRoot "Aktualisieren.bat"
if (-not (Test-Path $bat)) { throw "Aktualisieren.bat nicht gefunden: $bat" }

# --no-open: im geplanten Lauf keinen Browser oeffnen
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c `"$bat`" --no-open" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Aufgabe '$TaskName' registriert: jeden $Day um $Time."
Write-Host "Testlauf: Start-ScheduledTask -TaskName `"$TaskName`""
