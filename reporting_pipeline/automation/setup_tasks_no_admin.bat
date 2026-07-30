@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: setup_tasks_no_admin.bat
:: Double-click to register both scheduled tasks — NO admin required.
:: ─────────────────────────────────────────────────────────────────────────────

echo Registering CIQ pipeline tasks...

:: Daily task — runs every hour
schtasks /create ^
  /tn "CIQ - Daily Pipeline" ^
  /tr "wsl bash /home/mabdelhameed2/CIQ/reporting_pipeline/automation/daily_pipeline.sh" ^
  /sc HOURLY ^
  /mo 1 ^
  /st 07:00 ^
  /f

:: Weekly task — every Monday at 08:00
schtasks /create ^
  /tn "CIQ - Weekly Pipeline" ^
  /tr "wsl bash /home/mabdelhameed2/CIQ/reporting_pipeline/automation/weekly_pipeline.sh" ^
  /sc WEEKLY ^
  /d MON ^
  /st 08:00 ^
  /f

echo.
echo Done! Tasks registered:
echo   CIQ - Daily Pipeline   (every hour)
echo   CIQ - Weekly Pipeline  (every Monday 08:00)
echo.
echo To run manually at any time:
echo   schtasks /run /tn "CIQ - Daily Pipeline"
echo   schtasks /run /tn "CIQ - Weekly Pipeline"
echo.
pause
