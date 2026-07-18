@echo off

cd /d "%~dp0.."
echo   cd is on  : %CD%
python 04_FinalSubtitle\.scripts\transcribe_mp3tosrt.py 04_FinalSubtitle\04_FinalAudio.MP3 04_FinalSubtitle\04_FinalSubtitle.srt

echo.


pause
endlocal
