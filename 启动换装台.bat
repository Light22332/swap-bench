@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "node_modules\electron\dist\electron.exe" goto run

echo.
echo   还没装依赖。先跑一次这个：
echo.
echo       npm install
echo.
pause
exit /b 1

:run
start "" "node_modules\electron\dist\electron.exe" .
