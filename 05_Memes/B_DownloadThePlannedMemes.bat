@echo off
cd /d "%~dp0"
echo   cd is on : %CD%
echo.

echo Installing dependencies...
python -m pip install ddgs pillow requests
echo.

echo.
echo   Downloading memes...
python .scripts\DownloadMemes.py

echo.
pause