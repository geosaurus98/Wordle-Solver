@echo off
REM Daily puzzle solver — runs all games and emails results to geosaurus98@gmail.com
REM Place this in: C:\Users\George\Documents\GitHub\Solvers\run_daily.bat

cd /d "%~dp0"

REM Activate virtual env if one exists alongside the repo
if exist "..\venv\Scripts\activate.bat" (
    call "..\venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

python -m daily_puzzles.daily_report

exit /b %ERRORLEVEL%
