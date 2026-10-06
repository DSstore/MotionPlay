@echo off
rem Runs all automated checks. Options are passed on, for example: MotionPlay-Test.cmd -Coverage
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\test.ps1" %*
echo.
pause
