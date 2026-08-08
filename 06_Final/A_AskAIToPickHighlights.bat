@echo off
setlocal
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo   asking the AI to pick 3 highlights from 04_FinalSubtitle.srt
echo   for the cold open that plays before the intro
echo.

python .scripts\AskAiToPickHighlights_deepseek.py

echo.
echo   highlights.md written - open it and tweak the timestamps if you want,
echo   then run B_CombineFinalTimelines.bat
echo.
echo   (skip this step entirely and there is simply no cold open)
echo.
if not defined NONINTERACTIVE pause
endlocal
