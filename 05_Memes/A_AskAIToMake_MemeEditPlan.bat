@echo off
setlocal

cd /d "%~dp0"
echo   cd is on  : %CD%
python .scripts\AskAiToAddMemes_deepseek.py

echo.


if not defined NONINTERACTIVE pause
endlocal
