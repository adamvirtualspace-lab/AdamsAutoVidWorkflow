@echo off
setlocal
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   combining :
echo     03_EditPlanToOtio\editplan.otio
echo     04_FinalSubtitle\FinalSubtitle.otio
echo     05_Memes\memeeditplan.otio
echo   into FinalTimelineNoCap.otio and FinalTimelineWithCap.otio
echo.

python .scripts\CombineFinalTimeline.py

echo.
if not defined NONINTERACTIVE pause
endlocal
