@echo off
cd /d "%~dp0"
echo   cd is on : %CD%

python .scripts\MEMEEDITPLANtoOTIO.py memeeditplan.md

echo.
pause