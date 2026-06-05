@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
chcp 65001 >nul 2>&1

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo *** Run as Administrator ***
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)

echo === YTD Previewer - remove Explorer thumbnails (Administrator) ===
echo.

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

set "INSTALL=%LOCALAPPDATA%\YTDPreviewer"

echo [1/3] SharpShell + registry (HKLM)...
%PY% -m ytdpreviewer.setup_windows shell-uninstall
if errorlevel 1 (
  echo ERROR: shell-uninstall failed.
  pause
  exit /b 1
)

echo [2/3] Remove DLL from install folder...
taskkill /f /im explorer.exe >nul 2>&1
ping 127.0.0.1 -n 2 >nul
del /f /q "%INSTALL%\YtdThumbnail.dll" 2>nul
del /f /q "%INSTALL%\SharpShell.dll" 2>nul

echo [3/3] Verify HKLM removed...
reg query "HKLM\Software\Classes\CLSID\{8F3C2A1E-9D4B-4E67-B102-7E5D4A3B2C10}" >nul 2>&1
if errorlevel 1 (
  echo OK: COM class removed from HKLM.
) else (
  echo WARNING: CLSID still in HKLM - reboot or manual reg delete may be needed.
)

start explorer.exe
set PYTHONUNBUFFERED=1
%PY% -u -m ytdpreviewer.setup_windows shell-uninstall
echo Done. .ytd files should show generic icons after Explorer restarts.
pause
endlocal
