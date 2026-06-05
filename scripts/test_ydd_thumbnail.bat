@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
  echo Usage: test_ydd_thumbnail.bat path\to\file.ydd
  pause
  exit /b 1
)
set "OUT=%TEMP%\ytdprev_ydd_thumb.png"
python -m ytdpreviewer.main --ydd-thumbnail "%~1" "%OUT%" 256 --3d
if errorlevel 1 (
  echo Failed.
  pause
  exit /b 1
)
echo OK: %OUT%
start "" "%OUT%"
pause
