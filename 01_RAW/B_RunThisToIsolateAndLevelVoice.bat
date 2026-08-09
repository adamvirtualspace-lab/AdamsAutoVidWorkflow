@echo off
setlocal
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   isolating voice from background (demucs), then leveling the voice
echo   (compressor + loudness normalize) - this is what actually made
echo   transcription better: a clean, evenly-leveled voice with no music
echo   or sfx fighting for whisper's attention
echo.
echo   writes COMPILED_AUDIO.mp3   (voice - transcribed in step 2)
echo   writes COMPILED_BGAUDIO.mp3 (everything else - music, ambience, sfx)
echo   COMPILED_VIDEO.mp4 is NOT touched yet
echo.
echo   this is the slow step - runs a neural separation model over the
echo   whole recording. Faster with a CUDA GPU.
echo.

python isolate_voice.py

echo.
echo   not happy with the level? edit VOICE_FILTER in isolate_voice.py and
echo   run this again - it always re-isolates from the original, never stacks
echo.
echo   then: C_RunThisToCombineAudio.bat
echo.
if not defined NONINTERACTIVE pause
endlocal
