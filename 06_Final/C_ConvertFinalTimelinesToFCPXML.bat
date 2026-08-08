@echo off
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   converting the final timelines to Resolve fcpxml :
echo     FinalTimelineNoCap.otio   ^-^> FinalTimelineNoCap.fcpxml
echo     FinalTimelineWithCap.otio ^-^> FinalTimelineWithCap.fcpxml
echo.

python .scripts\OTIOtoFCPXML.py

echo.
pause
endlocal
