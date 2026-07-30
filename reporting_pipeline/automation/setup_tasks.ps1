# ─────────────────────────────────────────────────────────────────────────────
# setup_tasks.ps1
#
# Run this ONCE (as Administrator) to register both scheduled tasks.
#   Right-click this file → "Run with PowerShell" (as Admin)
#
# Tasks created:
#   CIQ - Daily Pipeline   → runs every hour, executes daily_pipeline.sh in WSL
#   CIQ - Weekly Pipeline  → runs every Monday at 08:00, executes weekly_pipeline.sh
# ─────────────────────────────────────────────────────────────────────────────

$wslPath = "wsl.exe"

# ── Daily task (every hour) ───────────────────────────────────────────────────
$dailyAction = New-ScheduledTaskAction `
    -Execute $wslPath `
    -Argument "bash /home/mabdelhameed2/CIQ/reporting_pipeline/automation/daily_pipeline.sh"

$dailyTrigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) `
    -Once -At (Get-Date -Hour 7 -Minute 0 -Second 0)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName "CIQ - Daily Pipeline" `
    -TaskPath "\CIQ\" `
    -Action $dailyAction `
    -Trigger $dailyTrigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "✓ Daily task registered (runs every hour)" -ForegroundColor Green

# ── Weekly task (every Monday 08:00) ─────────────────────────────────────────
$weeklyAction = New-ScheduledTaskAction `
    -Execute $wslPath `
    -Argument "bash /home/mabdelhameed2/CIQ/reporting_pipeline/automation/weekly_pipeline.sh"

$weeklyTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday -At "08:00"

Register-ScheduledTask `
    -TaskName "CIQ - Weekly Pipeline" `
    -TaskPath "\CIQ\" `
    -Action $weeklyAction `
    -Trigger $weeklyTrigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "✓ Weekly task registered (every Monday 08:00)" -ForegroundColor Green
Write-Host ""
Write-Host "To run either task manually:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskPath '\CIQ\' -TaskName 'CIQ - Daily Pipeline'"
Write-Host "  Start-ScheduledTask -TaskPath '\CIQ\' -TaskName 'CIQ - Weekly Pipeline'"
