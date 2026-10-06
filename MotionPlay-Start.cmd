@echo off
rem Double-click to start the MotionPlay receiver and CV engine. Options are passed on, for example: MotionPlay-Start.cmd -User steve
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 pause
