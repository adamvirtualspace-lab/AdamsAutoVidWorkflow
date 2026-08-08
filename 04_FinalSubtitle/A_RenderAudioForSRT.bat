@echo off
setlocal
cd /d "%~dp0"

echo reading editplan.otio, converting into edl, and into concat
echo then using ffmpeg to make the cuts and render the audio for srt
python .scripts\otio_to_ffmpeg.py

echo.
if not defined NONINTERACTIVE pause
endlocal
