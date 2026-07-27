@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

echo === YTD Previewer build ===
echo.

%PY% --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.10+ is required.
  pause
  exit /b 1
)

echo [1/6] Dependencies...
%PY% -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 goto :fail

echo [2/6] Icons...
%PY% scripts\generate_icons.py
if errorlevel 1 goto :fail

echo [3/6] YTDPreviewer.exe...
%PY% -m PyInstaller ytdpreviewer.spec --noconfirm
if errorlevel 1 goto :fail

echo [4/6] Explorer thumbnails DLL...
dotnet build shell\YtdThumbnail\YtdThumbnail.csproj -c Release >nul 2>&1
dotnet build shell\RegisterShell\RegisterShell.csproj -c Release >nul 2>&1
call scripts\build_ydd_properties.bat
if errorlevel 1 goto :fail
if exist "shell\YtdThumbnail\bin\Release\net48\YtdThumbnail.dll" (
  copy /Y "shell\YtdThumbnail\bin\Release\net48\YtdThumbnail.dll" "dist\YTDPreviewer\" >nul
  if exist "shell\YtdThumbnail\bin\Release\net48\SharpShell.dll" copy /Y "shell\YtdThumbnail\bin\Release\net48\SharpShell.dll" "dist\YTDPreviewer\" >nul
)
if exist "shell\RegisterShell\bin\Release\net48\RegisterShell.exe" (
  copy /Y "shell\RegisterShell\bin\Release\net48\RegisterShell.exe" "dist\YTDPreviewer\" >nul
)
copy /Y "build\YddProperties\YddProperties.dll" "dist\YTDPreviewer\" >nul
copy /Y "shell\YddProperties\YTDPreviewer.propdesc" "dist\YTDPreviewer\" >nul

echo [5/6] Installer bundle...
if exist "dist\release" rmdir /s /q "dist\release"
mkdir "dist\release" 2>nul
xcopy /E /I /Y "dist\YTDPreviewer\*" "dist\release\" >nul
if errorlevel 1 goto :fail
mkdir "dist\release\assets" 2>nul
copy /Y "assets\app.ico" "dist\release\assets\" >nul
copy /Y "assets\ytd.ico" "dist\release\assets\" >nul
copy /Y "assets\ydd.ico" "dist\release\assets\" >nul
if exist "assets\logo" xcopy /E /I /Y "assets\logo" "dist\release\assets\logo\" >nul

echo [5b/6] version.json...
%PY% scripts\write_version_json.py
if errorlevel 1 goto :fail
copy /Y "dist\version.json" "dist\release\version.json" >nul
copy /Y "dist\version.txt" "dist\release\version.txt" >nul
copy /Y "dist\version.json" "dist\YTDPreviewer\version.json" >nul
copy /Y "dist\version.txt" "dist\YTDPreviewer\version.txt" >nul

if exist "shell\YtdThumbnail\bin\Release\net48\YtdThumbnail.dll" (
  copy /Y "shell\YtdThumbnail\bin\Release\net48\YtdThumbnail.dll" "dist\release\" >nul
  if exist "shell\YtdThumbnail\bin\Release\net48\SharpShell.dll" copy /Y "shell\YtdThumbnail\bin\Release\net48\SharpShell.dll" "dist\release\" >nul
)
if exist "shell\RegisterShell\bin\Release\net48\RegisterShell.exe" (
  copy /Y "shell\RegisterShell\bin\Release\net48\RegisterShell.exe" "dist\release\" >nul
  copy /Y "shell\RegisterShell\bin\Release\net48\RegisterShell.exe" "dist\YTDPreviewer\" >nul
)

echo [5c/6] app_bundle.zip...
pushd "dist"
if exist "app_bundle.zip" del /f /q "app_bundle.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'release\*' -DestinationPath 'app_bundle.zip' -Force"
if errorlevel 1 (
  popd
  goto :fail
)
popd

echo [6/6] Setup (onedir)...
echo   Tip: close any setup.exe installer windows before this step.
set "SETUP_COLLECT_NAME=setup_build"
set "SETUP_FINAL_DIR=setup"
call :free_setup_build
echo   PyInstaller output folder: dist\!SETUP_COLLECT_NAME!
%PY% -m PyInstaller setup.spec --noconfirm
if errorlevel 1 goto :fail
if not exist "dist\!SETUP_COLLECT_NAME!\setup.exe" goto :fail

rem Promote to dist\setup when possible (old folder may be locked)
if exist "dist\setup" rmdir /s /q "dist\setup" 2>nul
if exist "dist\setup" (
  if exist "dist\setup_old" rmdir /s /q "dist\setup_old" 2>nul
  move "dist\setup" "dist\setup_old" >nul 2>&1
)
if not exist "dist\setup" move "dist\!SETUP_COLLECT_NAME!" "dist\setup" >nul 2>&1
if not exist "dist\setup\setup.exe" (
  set "SETUP_FINAL_DIR=!SETUP_COLLECT_NAME!"
)
if exist "dist\setup\setup.exe" if exist "dist\!SETUP_COLLECT_NAME!\setup.exe" (
  rem The old elevated installer may still lock dist\setup. Never package that stale folder.
  set "SETUP_FINAL_DIR=!SETUP_COLLECT_NAME!"
)

if exist "dist\setup.exe" del /f /q "dist\setup.exe" 2>nul

echo [6b/6] setup.zip (portable installer folder)...
if exist "dist\setup.zip" del /f /q "dist\setup.zip" 2>nul
if exist "dist\!SETUP_FINAL_DIR!\setup.exe" (
  pushd "dist"
  powershell -NoProfile -Command "Compress-Archive -Path '!SETUP_FINAL_DIR!\*' -DestinationPath 'setup.zip' -Force"
  popd
)

echo.
echo Done:
if exist "dist\!SETUP_FINAL_DIR!\setup.exe" (
  echo   dist\!SETUP_FINAL_DIR!\setup.exe
  echo   dist\setup.zip
) else (
  echo   setup.exe not found in dist\setup
)
echo   dist\release\YTDPreviewer.exe
echo.
if not defined CI pause
exit /b 0

:free_setup_build
taskkill /f /im setup.exe /t >nul 2>&1
taskkill /f /im YTDPreviewer.exe /t >nul 2>&1
powershell -NoProfile -Command "$r=(Resolve-Path 'dist').Path; Get-CimInstance Win32_Process -EA SilentlyContinue | ? { $_.ExecutablePath -and ($_.ExecutablePath -like ($r+'\setup_build\*') -or $_.ExecutablePath -like ($r+'\setup\*')) } | %% { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }"
ping 127.0.0.1 -n 3 >nul
if not exist "dist\setup_build" exit /b 0
rmdir /s /q "dist\setup_build" 2>nul
if not exist "dist\setup_build" exit /b 0
set "SETUP_COLLECT_NAME=setup_out_%RANDOM%%RANDOM%"
echo   setup_build is locked - building to dist\!SETUP_COLLECT_NAME! instead
exit /b 0

:fail
echo.
echo BUILD FAILED.
if not defined CI pause
exit /b 1
