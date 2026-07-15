@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo === Step 1: Generate EDL.xml + .concat from editplan.otio ===
python "%SCRIPT_DIR%\.scripts_and_examples\otio_to_ffmpeg.py" "%SCRIPT_DIR%\editplan.otio" --output-dir "%SCRIPT_DIR%" --no-bat

if %ERRORLEVEL% neq 0 (
    echo === Python script failed! Aborting. ===
    pause
    exit /b 1
)

echo.
echo === Step 2: Rendering with FFmpeg concat demuxer ===

ffmpeg -y -safe 0 -f concat -i "%SCRIPT_DIR%\editplan.concat" ^
       -c:v libx264 -preset medium -crf 18 ^
       -c:a aac -b:a 192k ^
       -pix_fmt yuv420p ^
       "%SCRIPT_DIR%\SnowRunner_Part_02.mp4"

if %ERRORLEVEL% equ 0 (
    echo.
    echo === Done: %SCRIPT_DIR%\COMPILED_VIDEO.mp4 ===
) else (
    echo === FFmpeg error! ===
    pause
)

endlocal
