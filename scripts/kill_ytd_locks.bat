@echo off
setlocal EnableExtensions
echo Закрываю процессы, блокирующие установку...
taskkill /f /im YTDPreviewer.exe >nul 2>&1
taskkill /f /im explorer.exe >nul 2>&1
timeout /t 2 /nobreak >nul
start "" "%WINDIR%\explorer.exe"
echo Готово. Запустите dist\setup\setup.exe и нажмите Установить.
pause
