@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if %errorlevel%==0 (
    py -B "Source\inventory_cli.py"
) else (
    python -B "Source\inventory_cli.py"
)
echo.
echo Program closed. The database remains saved in the Data folder.
pause
