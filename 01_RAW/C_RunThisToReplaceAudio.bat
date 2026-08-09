@echo off
setlocal
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   putting the leveled audio into COMPILED_VIDEO.mp4
echo   video stream is copied untouched - just swapping the audio track
echo.

python replace_audio.py

echo.
echo   to undo entirely:  python replace_audio.py --revert
echo.
if not defined NONINTERACTIVE pause
endlocal
