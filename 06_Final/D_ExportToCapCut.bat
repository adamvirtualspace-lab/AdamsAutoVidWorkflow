@echo off
setlocal
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   exporting FinalTimelineNoCap.otio into a CapCut draft project
echo   (captions are left out on purpose - CapCut has its own caption tools)
echo.

python .scripts\ExportToCapCut.py

echo.
if not defined NONINTERACTIVE pause
endlocal
