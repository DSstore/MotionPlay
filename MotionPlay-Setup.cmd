@echo off
rem Double-click to set up MotionPlay on Windows. Options are passed on, for example: MotionPlay-Setup.cmd -Recreate
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
echo.
pause
