@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul 2>&1

echo === YTD Previewer - install (dev) ===
echo.

where py >nul 2>&1
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

%PY% --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python not found. Install Python 3.10+ from python.org
  pause
  exit /b 1
)

echo [1/5] Dependencies...
%PY% -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo ERROR: pip failed.
  pause
  exit /b 1
)

echo [2/5] Icons...
%PY% scripts\generate_icons.py
if errorlevel 1 (
  echo ERROR: icon generation failed.
  pause
  exit /b 1
)

echo [3/5] Explorer thumbnails DLL...
dotnet build shell\YtdThumbnail\YtdThumbnail.csproj -c Release >nul 2>&1
if errorlevel 1 (
  echo WARNING: dotnet build failed. Explorer previews need YtdThumbnail.dll
)

echo [4/5] Register .ytd / .ydd...
%PY% -m ytdpreviewer.setup_windows dev
if errorlevel 1 (
  echo ERROR: setup_windows failed.
  pause
  exit /b 1
)

echo [5/5] Background process...
if exist "%LOCALAPPDATA%\YTDPreviewer\YTDPreviewer.exe" (
  start "" "%LOCALAPPDATA%\YTDPreviewer\YTDPreviewer.exe" --background
) else (
  start "" pythonw "%LOCALAPPDATA%\YTDPreviewer\tray.pyw"
)

echo.
echo Done.
echo   .ytd - double-click preview; context menu Export to PNG
echo   Explorer texture previews: scripts\install_shell_admin.bat (Administrator)
echo   Then: scripts\refresh_explorer_thumbs.bat
echo   .ydd - 3D preview; .png - context menu Build YTD
echo.
pause
endlocal
