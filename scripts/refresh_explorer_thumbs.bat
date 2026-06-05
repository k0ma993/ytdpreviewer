@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

echo Clearing thumbnail cache and restarting Explorer...

del /f /q "%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db" 2>nul
del /f /q "%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db" 2>nul
del /f /q "%LOCALAPPDATA%\YTDPreviewer\thumbcache\*.png" 2>nul
rmdir /s /q "%LOCALAPPDATA%\YTDPreviewer\thumbcache" 2>nul

taskkill /f /im explorer.exe >nul 2>&1
ping 127.0.0.1 -n 3 >nul
start explorer.exe

echo Done. Open your .ytd folder in Large icons or Tiles view.
pause
endlocal
