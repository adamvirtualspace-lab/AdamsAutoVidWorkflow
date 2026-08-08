@echo off


cd /d "%~dp0"
echo   cd is on  : %CD%
python .scripts\srt_to_otio.py 04_FinalSubtitle.srt FinalSubtitle.otio --start-tc 00:00:00:00

echo.


pause
endlocal