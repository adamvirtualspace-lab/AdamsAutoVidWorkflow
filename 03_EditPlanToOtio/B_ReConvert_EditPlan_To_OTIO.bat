@echo off
cd /d "%~dp0"

echo re-converting the editplan to otio format
echo deleting existing editplan.otio and writing new
python .scripts_and_examples\EditPlanToOTIO.py editplan.md -o editplan.otio

echo.
pause
endlocal
