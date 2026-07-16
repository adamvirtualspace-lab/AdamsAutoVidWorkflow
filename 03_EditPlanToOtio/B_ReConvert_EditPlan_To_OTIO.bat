@echo off
cd /d "%~dp0"

echo re-converting the editplan to otio format
echo deleting existing editplan.otio and writing new
python .scripts_and_examples\EditPlanToOTIO.py editplan.md -o editplan.otio
echo.
echo.
echo   editplan.otio should be available for you to load in your video editor
echo.
echo   on your video editor, go check or edit yourself and export back right here
echo   just replacing the editplan.otio
echo.
echo   then continue in 04 Folder

echo.
pause
endlocal
