@echo off
cd /d "%~dp0"
if exist "dist\setup\setup.exe" (
  start "" "dist\setup\setup.exe"
  exit /b 0
)
if exist "dist\setup_build\setup.exe" (
  start "" "dist\setup_build\setup.exe"
  exit /b 0
)
echo Run build.bat first.
pause
exit /b 1
