@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
chcp 65001 >nul 2>&1

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo *** Run this file as Administrator ***
  echo Right-click install_shell_admin.bat -^> Run as administrator
  echo.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)

echo === YTD Previewer - Explorer thumbnails .ytd + .ydd (Administrator) ===
echo.

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

set "DLL_SRC=shell\YtdThumbnail\bin\Release\net48\YtdThumbnail.dll"
set "INSTALL=%LOCALAPPDATA%\YTDPreviewer"

echo [1/5] Build shell extensions...
dotnet build shell\YtdThumbnail\YtdThumbnail.csproj -c Release
if errorlevel 1 goto :build_fail
dotnet build shell\RegisterShell\RegisterShell.csproj -c Release
if errorlevel 1 goto :build_fail
goto :build_ok
:build_fail
  echo ERROR: dotnet build failed.
  pause
  exit /b 1
:build_ok
if not exist "%DLL_SRC%" (
  echo ERROR: %DLL_SRC% not found after build.
  pause
  exit /b 1
)

echo [2/5] Stop Explorer and copy DLL...
taskkill /f /im explorer.exe >nul 2>&1
ping 127.0.0.1 -n 2 >nul
if not exist "%INSTALL%" mkdir "%INSTALL%"
copy /y "%DLL_SRC%" "%INSTALL%\YtdThumbnail.dll"
copy /y "shell\YtdThumbnail\bin\Release\net48\SharpShell.dll" "%INSTALL%\" >nul 2>&1
copy /y "shell\RegisterShell\bin\Release\net48\RegisterShell.exe" "%INSTALL%\" >nul 2>&1
if errorlevel 1 (
  echo WARNING: copy to LocalAppData failed, trying ProgramData...
  if not exist "%ProgramData%\YTDPreviewer" mkdir "%ProgramData%\YTDPreviewer"
  copy /y "%DLL_SRC%" "%ProgramData%\YTDPreviewer\YtdThumbnail.dll"
  if errorlevel 1 (
    echo ERROR: could not copy YtdThumbnail.dll.
    start explorer.exe
    pause
    exit /b 1
  )
)

echo [3/5] Register COM in HKLM + shellex...
%PY% -m ytdpreviewer.setup_windows shell-admin
if errorlevel 1 (
  echo ERROR: setup failed.
  start explorer.exe
  pause
  exit /b 1
)

echo [4/5] Verify registration...
reg query "HKLM\Software\Classes\CLSID\{8F3C2A1E-9D4B-4E67-B102-7E5D4A3B2C10}\InprocServer32" /v Assembly >nul 2>&1
if errorlevel 1 reg query "HKCR\CLSID\{8F3C2A1E-9D4B-4E67-B102-7E5D4A3B2C10}\InprocServer32" /v Assembly >nul 2>&1
if errorlevel 1 (
  echo.
  echo ERROR: YTD COM class is NOT in HKLM.
  start explorer.exe
  pause
  exit /b 1
)
reg query "HKLM\Software\Classes\CLSID\{4C8E1F2A-6B3D-4E59-9C01-2F7E6D5A4B3C}\InprocServer32" /v Assembly >nul 2>&1
if errorlevel 1 (
  echo.
  echo ERROR: YDD COM class is NOT in HKLM.
  start explorer.exe
  pause
  exit /b 1
)
echo OK: COM registered in HKLM (.ytd + .ydd handlers).

echo [5/5] Registry tweaks + restart Explorer...
%PY% -c "from ytdpreviewer.setup_windows import _apply_thumbnail_com_extras; _apply_thumbnail_com_extras('{8F3C2A1E-9D4B-4E67-B102-7E5D4A3B2C10}'); _apply_thumbnail_com_extras('{4C8E1F2A-6B3D-4E59-9C01-2F7E6D5A4B3C}')"
del /f /q "%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db" 2>nul
start explorer.exe

echo.
echo Done. Open .ytd / .ydd folder in Extra large icons or Content view.
echo First .ydd preview may take 2-10 seconds (3D model render).
pause
endlocal
