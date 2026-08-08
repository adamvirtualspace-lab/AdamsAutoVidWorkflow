@echo off
setlocal

cd /d "%~dp0"
python .scripts/transcribe_raw.py


echo ".mp3" <- detection is case sensitive
echo.


if not defined NONINTERACTIVE pause
endlocal
