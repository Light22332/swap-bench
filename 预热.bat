@echo off
chcp 936 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo    找不到 python。装一个，或者把 python 加进 PATH 再双击这个文件。
  echo.
  pause
  exit /b 1
)

echo.
echo    预热中，第一次大概一两分钟，别关这个窗口。
echo.

python tools\warmup.py
if errorlevel 1 (
  echo.
  echo    没成功，看上面的提示。
)

echo.
echo    按任意键关掉这个窗口。ComfyUI 会继续在后面跑，不用管它。
pause >nul
