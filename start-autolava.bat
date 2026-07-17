@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [AutoLava] Startup failed or services stopped. Exit code: %EXIT_CODE%
    echo [AutoLava] Read the Chinese guidance above, fix the issue, and run this file again.
    pause
)

exit /b %EXIT_CODE%
