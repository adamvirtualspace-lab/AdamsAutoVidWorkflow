@echo off
cd /d "%~dp0"

echo asking DeepSeek to make editplan based on raw subtitle
python .scripts_and_examples\askdeepseektoeditplandeepseek.py

echo converting the editplan to otio format
python .scripts_and_examples\EditPlanToOTIO.py editplan.md -o editplan.otio

echo.
pause
endlocal
