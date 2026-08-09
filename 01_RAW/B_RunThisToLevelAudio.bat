@echo off
setlocal
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   leveling COMPILED_VIDEO.mp4's audio (compressor + loudness normalize)
echo   writes a standalone audio file - COMPILED_VIDEO.mp4 is NOT touched yet
echo.

python level_audio.py

echo.
echo   not happy with it? edit AUDIO_FILTER in level_audio.py and run this
echo   again - it always re-levels from the original, never stacks
echo.
echo   when you're happy with it, run C_RunThisToReplaceAudio.bat to put it
echo   into COMPILED_VIDEO.mp4
echo.
if not defined NONINTERACTIVE pause
endlocal
