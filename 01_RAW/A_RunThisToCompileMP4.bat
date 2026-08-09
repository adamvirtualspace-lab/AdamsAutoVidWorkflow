@echo off
setlocal

cd /d "%~dp0"
python compile_mp4s.py

echo.


if not defined NONINTERACTIVE pause
endlocal
