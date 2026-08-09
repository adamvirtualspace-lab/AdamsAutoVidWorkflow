@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ============================================================
:: StartEverythingUsingDeepseek.bat
::
:: Runs the whole pipeline end to end, unattended, using the DeepSeek
:: "AskAI" .bat at every step that needs one (edit plan, meme plan,
:: highlights). If you'd rather do those three steps yourself with an
:: AI assistant sitting in the chat, see ReadThisIfYouAreClaude.md and
:: run the individual step .bats by hand instead of this one.
::
:: Every step .bat still runs standalone with its normal "press any key"
:: pause; this script sets NONINTERACTIVE=1 so those pauses are skipped
:: while it drives them, and clears it again when it's done.
:: ============================================================

set NONINTERACTIVE=1
set STEP=0
set FAILED=

echo ============================================================
echo   AdamsAutoVidWorkflow - full pipeline (DeepSeek)
echo ============================================================
echo.

if not exist "deepseekapikey.txt" (
    echo [ERROR] deepseekapikey.txt not found.
    echo         Run RunThisToStart.bat first - it creates the file for you.
    goto :bail
)
for %%A in ("deepseekapikey.txt") do set KEYSIZE=%%~zA
if "!KEYSIZE!"=="0" (
    echo [ERROR] deepseekapikey.txt is empty.
    echo         Paste your DeepSeek key into it, then run this again.
    echo         Get one at: https://platform.deepseek.com/api_keys
    goto :bail
)

:: ── Step 1 : compile raw footage ───────────────────────────────────────
call :run_step "1A - Compile raw video" "01_RAW\A_RunThisToCompileMP4.bat"
if defined FAILED goto :bail
call :run_step "1B - Isolate and level the voice" "01_RAW\B_RunThisToIsolateAndLevelVoice.bat"
if defined FAILED goto :bail
call :run_step "1C - Combine voice and background" "01_RAW\C_RunThisToCombineAudio.bat"
if defined FAILED goto :bail
call :run_step "1D - Replace the audio in the video" "01_RAW\D_RunThisToReplaceAudio.bat"
if defined FAILED goto :bail

:: ── Step 2 : raw subtitle ───────────────────────────────────────────────
call :run_step "2 - Generate raw subtitle" "02_RawSubtitles\RunThisToGenerateSubtitle.bat"
if defined FAILED goto :bail

:: ── Step 3 : edit plan (AskAI) + convert ────────────────────────────────
call :run_step "3A - Ask DeepSeek for the edit plan" "03_EditPlanToOtio\A_RunThisToMakeEditPlan_WithDeepSeek.bat"
if defined FAILED goto :bail
call :run_step "3B - Convert edit plan to otio" "03_EditPlanToOtio\B_ReConvert_EditPlan_To_OTIO.bat"
if defined FAILED goto :bail

:: ── Step 4 : final subtitle from the cut ────────────────────────────────
call :run_step "4A - Render cut audio" "04_FinalSubtitle\A_RenderAudioForSRT.bat"
if defined FAILED goto :bail
call :run_step "4B - Transcribe final subtitle" "04_FinalSubtitle\B_GenerateFinalSubtitle.bat"
if defined FAILED goto :bail
call :run_step "4C - Convert final subtitle to otio" "04_FinalSubtitle\C_FinalSubtitleToOtio.bat"
if defined FAILED goto :bail

:: ── Step 5 : memes (AskAI) + download + convert ─────────────────────────
call :run_step "5A - Ask DeepSeek for the meme plan" "05_Memes\A_AskAIToMake_MemeEditPlan.bat"
if defined FAILED goto :bail
call :run_step "5B - Download the planned memes" "05_Memes\B_DownloadThePlannedMemes.bat"
if defined FAILED goto :bail
call :run_step "5C - Convert meme plan to otio" "05_Memes\C_ConvertMemeEditPlanToOTIO.bat"
if defined FAILED goto :bail

:: ── Step 6 : cold open (AskAI, optional) + combine + export ─────────────
call :run_step "6A - Ask DeepSeek to pick highlights" "06_Final\A_AskAIToPickHighlights.bat"
if defined FAILED goto :bail
call :run_step "6B - Combine final timelines" "06_Final\B_CombineFinalTimelines.bat"
if defined FAILED goto :bail
call :run_step "6C - Convert to fcpxml" "06_Final\C_ConvertFinalTimelinesToFCPXML.bat"
if defined FAILED goto :bail
call :run_step "6D - Export to CapCut" "06_Final\D_ExportToCapCut.bat"
if defined FAILED goto :bail

echo.
echo ============================================================
echo   All done.
echo ============================================================
echo.
echo   06_Final\FinalTimelineNoCap.otio    /.fcpxml
echo   06_Final\FinalTimelineWithCap.otio  /.fcpxml
echo   + a CapCut draft project named after this folder
echo.
echo   Worth a quick look before you call it done:
echo     - 03_EditPlanToOtio\editplan.md   - the cuts DeepSeek chose
echo     - 05_Memes\memeeditplan.md        - which memes, and whether the
echo                                         downloaded images actually match
echo     - 06_Final\highlights.md          - the cold open, if one was made
echo.
goto :end

:run_step
set /a STEP+=1
echo ------------------------------------------------------------
echo   Step !STEP! : %~1
echo ------------------------------------------------------------
call "%~2"
if errorlevel 1 (
    echo.
    echo [ERROR] %~2 exited with an error.
    set FAILED=1
)
echo.
exit /b

:bail
echo.
echo ============================================================
echo   Stopped - see the error above.
echo   Fix it and re-run this script; earlier steps that already
echo   wrote their output files won't need to redo any work you
echo   don't want redone, but each step does overwrite its own
echo   output, so check before re-running past something you
echo   hand-edited (e.g. editplan.md, memeeditplan.md, highlights.md).
echo ============================================================
echo.

:end
set NONINTERACTIVE=
pause
endlocal
