@echo off
setlocal
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   combining COMPILED_AUDIO.mp3 (leveled voice) + COMPILED_BGAUDIO.mp3
echo   (background) into COMBINED_AUDIO.mp3
echo.

python combine_audio.py

echo.
echo   then: D_RunThisToReplaceAudio.bat
echo.
if not defined NONINTERACTIVE pause
endlocal
