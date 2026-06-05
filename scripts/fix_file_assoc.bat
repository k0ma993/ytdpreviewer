@echo off

setlocal EnableExtensions

cd /d "%~dp0\.."



where py >nul 2>&1

if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")



echo === Fix YTD Previewer associations ===

echo.



echo [1/4] Remove old registry (autostart, icons, setup.exe handlers)...

%PY% -m ytdpreviewer.setup_windows uninstall

if errorlevel 1 goto :fail



echo [2/4] Regenerate icons (app only, not .ytd type icons)...

%PY% scripts\generate_icons.py

if errorlevel 1 goto :fail



echo [3/4] Repair open command (if already installed)...

if exist "%LOCALAPPDATA%\YTDPreviewer\YTDPreviewer.exe" (

  %PY% -m ytdpreviewer.setup_windows repair

) else (

  echo Skip repair: install app first from dist\setup\setup.exe

)



echo [4/4] Explorer texture previews need Administrator:

echo   Right-click scripts\install_shell_admin.bat -^> Run as administrator

echo   Then: scripts\refresh_explorer_thumbs.bat

echo.

echo Diagnose: %PY% -m ytdpreviewer.setup_windows diagnose

echo.

pause

exit /b 0



:fail

echo FAILED.

pause

exit /b 1

