@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo === YTD Previewer - uninstall ===
echo.

set PYTHONUNBUFFERED=1

where python >nul 2>&1
if %errorlevel%==0 (set "PY=python" & goto run_py)

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3" & goto run_py)

set "SETUP_EXE=%LOCALAPPDATA%\YTDPreviewer\setup.exe"
if exist "%SETUP_EXE%" (
  echo Python not in PATH - using installed setup.exe
  "%SETUP_EXE%" /uninstall
  goto after_run
)

if exist "%~dp0dist\setup\setup.exe" (
  echo Python not in PATH - using dist\setup\setup.exe
  "%~dp0dist\setup\setup.exe" /uninstall
  goto after_run
)

echo ERROR: Python not found and setup.exe not available.
echo Install Python 3, or run dist\setup\setup.exe and click Uninstall.
pause
exit /b 1

:run_py
echo Using: %PY%
echo.
%PY% -u -m ytdpreviewer.setup_windows uninstall
goto after_run

:after_run
if errorlevel 1 (
  echo.
  echo ERROR: uninstall failed.
  pause
  exit /b 1
)

echo.
echo If .ytd previews still appear, run as Administrator:
echo   scripts\uninstall_shell_admin.bat
echo.
echo You may delete the folder manually:
echo   %LOCALAPPDATA%\YTDPreviewer
echo.
pause
endlocal
