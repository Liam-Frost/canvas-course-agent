<#
Creates Windows Task Scheduler tasks for Canvas Course Agent.

Assumptions:
- You installed the CLI via pipx: `pipx install canvas-course-agent` OR `pipx install git+https://...`
- Your .env lives in a known location, e.g. $Env:USERPROFILE\canvas-course-agent\.env

Usage (PowerShell as your user):
  .\install-tasks.ps1 -ProjectDir "$env:USERPROFILE\canvas-course-agent" -EnvPath "$env:USERPROFILE\canvas-course-agent\.env"

#>

param(
  [Parameter(Mandatory=$true)] [string]$ProjectDir,
  [Parameter(Mandatory=$true)] [string]$EnvPath,
  [int]$SyncDays = 60
)

$CanvasAgent = "pipx"

# Wrap the command so working directory is correct.
$RemindCmd = "cd `"$ProjectDir`"; canvas-agent --env-path `"$EnvPath`" remind run --lookahead-min 2 --send-discord"
$SyncCmd   = "cd `"$ProjectDir`"; canvas-agent --env-path `"$EnvPath`" sync courses; canvas-agent --env-path `"$EnvPath`" sync assignments --days $SyncDays; canvas-agent --env-path `"$EnvPath`" sync quizzes --days $SyncDays"

$RemindTaskName = "CanvasCourseAgent-Remind"
$SyncTaskName   = "CanvasCourseAgent-Sync"

# Every 1 minute
$remindAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command $RemindCmd"
$remindTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration ([TimeSpan]::MaxValue)

# Daily at 00:00
$syncAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command $SyncCmd"
$syncTrigger = New-ScheduledTaskTrigger -Daily -At "00:00"

Register-ScheduledTask -TaskName $RemindTaskName -Action $remindAction -Trigger $remindTrigger -Force | Out-Null
Register-ScheduledTask -TaskName $SyncTaskName -Action $syncAction -Trigger $syncTrigger -Force | Out-Null

Write-Host "Installed tasks:" $RemindTaskName "," $SyncTaskName
Write-Host "Check: Get-ScheduledTask -TaskName $RemindTaskName, $SyncTaskName"
