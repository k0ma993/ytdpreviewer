@echo off
setlocal
if "%~1"=="" (
  echo Usage: warm_ytd_folder.bat "C:\path\to\folder"
  exit /b 1
)
cd /d "%~dp0.."
python -m ytdpreviewer.thumb_warm "%~1"
exit /b %ERRORLEVEL%
