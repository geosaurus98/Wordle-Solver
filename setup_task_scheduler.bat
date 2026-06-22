@echo off
REM One-time setup: register a Windows Task Scheduler job that runs daily_report at 8:00 AM.
REM Run this once as an administrator (right-click -> Run as administrator).

set TASK_NAME=DailyPuzzleSolver
set SCRIPT_PATH=%~dp0run_daily.bat
set START_TIME=08:00

echo Registering scheduled task "%TASK_NAME%"...
echo Script: %SCRIPT_PATH%
echo Time:   %START_TIME% daily

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%SCRIPT_PATH%\"" ^
  /sc daily ^
  /st %START_TIME% ^
  /ru "%USERNAME%" ^
  /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Task registered successfully.
    echo.
    echo NEXT STEPS:
    echo   1. Set your Gmail App Password environment variable:
    echo      setx GMAIL_APP_PASSWORD "xxxx-xxxx-xxxx-xxxx"
    echo      (Generate at https://myaccount.google.com/apppasswords)
    echo.
    echo   2. Test the script manually:
    echo      cd "%~dp0"
    echo      python -m sedecordle_bot.daily_report --no-email --print-html
    echo.
    echo   3. Once confirmed working, let the task run at 8:00 AM.
) else (
    echo.
    echo ERROR: Failed to register task. Try running as Administrator.
)

pause
