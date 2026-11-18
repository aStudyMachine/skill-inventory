@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python\python.exe" (
    echo Extract the entire demo ZIP before starting.
    pause
    exit /b 1
)
chcp 65001 >nul
"runtime\python\python.exe" -X utf8 "source\demo\demo.py" %*
if errorlevel 1 (
    pause
    exit /b 1
)
