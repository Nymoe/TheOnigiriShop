@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if %errorlevel%==0 (
  py -B -m PyInstaller --noconfirm --distpath . --workpath Build "Tools\TheOnigiriShop.spec"
) else (
  python -B -m PyInstaller --noconfirm --distpath . --workpath Build "Tools\TheOnigiriShop.spec"
)
if errorlevel 1 (
  echo Build failed. Read the error above and close Onigiri Shop before rebuilding.
  echo If build tools are missing: py -m pip install pyinstaller matplotlib
  pause
  exit /b 1
)
echo Built: %CD%\TheOnigiriShop.exe
echo Run Tools\CREATE_DESKTOP_SHORTCUT.bat to link your existing restaurant database.
pause
