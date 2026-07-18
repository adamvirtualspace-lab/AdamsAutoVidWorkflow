@echo off

cd /d "%~dp0"
echo   cd is on  : %CD%
python .scripts\AskAiToAddMemes_deepseek.py

echo.


pause
endlocal
