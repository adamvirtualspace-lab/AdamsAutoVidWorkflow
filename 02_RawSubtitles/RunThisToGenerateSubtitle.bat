@echo off

cd /d "%~dp0"
python .scripts/transcribe_raw.py

echo.


pause
endlocal
