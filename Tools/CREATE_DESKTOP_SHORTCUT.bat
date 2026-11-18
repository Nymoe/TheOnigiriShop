@echo off
setlocal
cd /d "%~dp0.."
if not exist "TheOnigiriShop.exe" (
  echo Build the executable using Tools\BUILD_WINDOWS_EXE.bat first.
  pause
  exit /b 1
)
if exist "Data\btm495.db" (
  start "" /wait "TheOnigiriShop.exe" --create-shortcut --database "%CD%\Data\btm495.db"
) else (
  start "" /wait "TheOnigiriShop.exe" --create-shortcut --choose-database
)
