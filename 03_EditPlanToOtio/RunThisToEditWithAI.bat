@echo off

cd /d "%~dp0"
echo asking ai to make editplan based on raw subtitle on "02_RawSubtitles"
python askaitoeditplan.py

echo converting the editplan to otio format
python EditPlanToOtio.py

echo.


pause
endlocal
