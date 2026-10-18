@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py inventory_cli.py
) else (
    python inventory_cli.py
)
echo.
echo Program closed. The database remains saved in this folder.
pause
