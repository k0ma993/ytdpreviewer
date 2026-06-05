@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
chcp 65001 >nul 2>&1

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

echo Applying Explorer thumbnail registry fixes...
%PY% -c "from ytdpreviewer.setup_windows import _apply_thumbnail_com_extras; _apply_thumbnail_com_extras('{8F3C2A1E-9D4B-4E67-B102-7E5D4A3B2C10}'); print('OK: DisableProcessIsolation + thumbnail category')"

echo.
echo If previews are still green: RIGHT-CLICK scripts\install_shell_admin.bat - Run as administrator
call scripts\refresh_explorer_thumbs.bat
endlocal
