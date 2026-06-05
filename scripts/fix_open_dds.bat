@echo off
setlocal
cd /d "%~dp0.."
echo Repairing .dds file association for YTD Previewer...
python -m ytdpreviewer.setup_windows repair
if errorlevel 1 (
  echo Failed. Run from project folder with Python installed.
  pause
  exit /b 1
)
echo Done. Try double-clicking a .dds file.
pause
