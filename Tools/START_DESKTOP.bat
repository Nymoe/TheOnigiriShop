@echo off
setlocal
cd /d "%~dp0.."
if exist "TheOnigiriShop.exe" (
  if exist "Data\btm495.db" (
    start "" "TheOnigiriShop.exe" --database "%CD%\Data\btm495.db"
  ) else (
    start "" "TheOnigiriShop.exe"
  )
  exit /b 0
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -B "Source\desktop_app.py"
) else (
  python -B "Source\desktop_app.py"
)
if errorlevel 1 pause
