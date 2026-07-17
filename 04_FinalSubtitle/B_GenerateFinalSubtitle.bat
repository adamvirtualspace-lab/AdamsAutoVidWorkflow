@echo off

cd /d "%~dp0.."
python /02_RawSubtitles/.scripts/transcribe_raw.py

echo.


pause
endlocal
