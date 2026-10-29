@echo off
chcp 936 >nul
cd /d "%~dp0"

if exist "node_modules\electron\dist\electron.exe" goto run

echo.
echo    还没装依赖。先在这个文件夹里打开命令行，跑一次：
echo.
echo       npm install
echo.
pause
exit /b 1

:run
start "" "node_modules\electron\dist\electron.exe" .