@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if %errorlevel%==0 (
  py -B -m unittest discover -v %*
) else (
  python -B -m unittest discover -v %*
)
set "test_result=%errorlevel%"
echo.
pause
exit /b %test_result%
