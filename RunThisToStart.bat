@echo off
setlocal EnableDelayedExpansion

echo Checking for Python...

:: Check 'python', 'py', 'python3' in order
python --version >nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v found.
    goto :ready
)

py --version >nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=2" %%v in ('py --version 2^>^&1') do echo [OK] Python %%v found via py launcher.
    set PYTHON_CMD=py
    goto :ready
)

python3 --version >nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=2" %%v in ('python3 --version 2^>^&1') do echo [OK] Python %%v found via python3.
    set PYTHON_CMD=python3
    goto :ready
)

:: ============================================================
:: Python not found — fetch latest version number and install
:: ============================================================
echo [!!] Python not found. Fetching latest version...

:: Ask Python's official download page for the latest version number
for /f "usebackq tokens=*" %%v in (`powershell -Command "& { (Invoke-WebRequest -Uri 'https://www.python.org/downloads/' -UseBasicParsing).Content -match 'Download Python (\d+\.\d+\.\d+)' | Out-Null; $Matches[1] }"`) do set LATEST=%%v

if "!LATEST!" == "" (
    echo [ERROR] Could not determine latest Python version. Check your internet connection.
    pause
    exit /b 1
)

echo [..] Latest Python version is !LATEST!. Downloading...

set INSTALLER=%temp%\python_installer.exe
powershell -Command "& { $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/!LATEST!/python-!LATEST!-amd64.exe' -OutFile '%INSTALLER%' }"

if not exist "%INSTALLER%" (
    echo [ERROR] Download failed. Try downloading manually: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [..] Installing Python !LATEST!...
"%INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_test=0 Include_launcher=1

if %errorlevel% neq 0 (
    echo [ERROR] Installation failed. Try running this script as Administrator.
    del "%INSTALLER%" >nul 2>&1
    pause
    exit /b 1
)

del "%INSTALLER%" >nul 2>&1

:: Refresh PATH for this session
for /f "usebackq tokens=*" %%i in (`powershell -Command "[System.Environment]::GetEnvironmentVariable('PATH','Machine')"`) do set "PATH=%%i;%PATH%"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Python installed but PATH not refreshed yet. Please reopen this terminal and run again.
    pause
    exit /b 0
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v installed successfully!

:: ============================================================
:ready
:: Put your Python code here
:: ============================================================
set PYTHON_CMD=python

echo.
echo Running script...
%PYTHON_CMD% -c "print('Hello from Python!')"

echo cloning adam's github workflow...
git clone https://github.com/adamvirtualspace-lab/AdamsAutoVidWorkflow.git

:: ============================================================
:: moving the cloned git into current folder
:: ============================================================

:: %PYTHON_CMD% -c "import os; import shutil; cwd = os.getcwd(); dst=os.path.join(cwd, 'AdamsAutoVidWorkflow'); shutil.move(dst, cwd)"
%PYTHON_CMD% -c "import os, shutil; cwd=os.getcwd(); src=os.path.join(cwd,'AdamsAutoVidWorkflow'); [shutil.move(os.path.join(src,f), cwd) for f in os.listdir(src)]"


:: ============================================================
echo Checking if ffmpeg is installed
:: ============================================================


:: ── 1. Check if ffmpeg is already on PATH ──────────────────────
where ffmpeg >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo [OK] ffmpeg is already installed and on PATH.
    ffmpeg -version 2>&1 | findstr /i "ffmpeg version"
    goto :check_python
)

echo [INFO] ffmpeg not found on PATH. Starting installation...
echo.

:: ── 2. Decide install location ─────────────────────────────────
set "FFMPEG_DIR=%LOCALAPPDATA%\ffmpeg"
set "FFMPEG_BIN=%FFMPEG_DIR%\bin"

if exist "%FFMPEG_BIN%\ffmpeg.exe" (
    echo [INFO] ffmpeg found at %FFMPEG_BIN% but not on PATH. Adding it now...
    goto :add_to_path
)

:: ── 3. Check for winget ────────────────────────────────────────
where winget >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo [INFO] Installing ffmpeg via winget...
    winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    if %ERRORLEVEL% == 0 (
        echo [OK] ffmpeg installed via winget.
        :: winget usually puts it on PATH automatically — re-check
        where ffmpeg >nul 2>&1
        if %ERRORLEVEL% == 0 goto :check_python
    )
    echo [WARN] winget install finished but ffmpeg still not on PATH. Falling back to manual download...
)

:: ── 4. Manual download (PowerShell) ───────────────────────────
echo [INFO] Downloading ffmpeg from GitHub releases via PowerShell...
echo        This may take a minute depending on your connection.
echo.

set "ZIP_URL=https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
set "ZIP_FILE=%TEMP%\ffmpeg_setup.zip"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ^
     $ProgressPreference = 'SilentlyContinue'; ^
     Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%'"

if not exist "%ZIP_FILE%" (
    echo [ERROR] Download failed. Please install ffmpeg manually from https://ffmpeg.org/download.html
    echo         and add it to your PATH.
    pause
    exit /b 1
)

echo [INFO] Extracting to %FFMPEG_DIR% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%TEMP%\ffmpeg_extract' -Force; ^
     $inner = Get-ChildItem '%TEMP%\ffmpeg_extract' -Directory | Select-Object -First 1; ^
     if (Test-Path '%FFMPEG_DIR%') { Remove-Item '%FFMPEG_DIR%' -Recurse -Force }; ^
     Move-Item $inner.FullName '%FFMPEG_DIR%'; ^
     Remove-Item '%TEMP%\ffmpeg_extract' -Recurse -Force -ErrorAction SilentlyContinue"

del /q "%ZIP_FILE%" 2>nul

if not exist "%FFMPEG_BIN%\ffmpeg.exe" (
    echo [ERROR] Extraction failed or folder structure unexpected.
    echo         Expected: %FFMPEG_BIN%\ffmpeg.exe
    pause
    exit /b 1
)

echo [OK] ffmpeg extracted to %FFMPEG_BIN%

:: ── 5. Add bin folder to user PATH permanently ─────────────────
:add_to_path
echo [INFO] Adding %FFMPEG_BIN% to user PATH...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cur = [System.Environment]::GetEnvironmentVariable('PATH','User'); ^
     if ($cur -notlike '*%FFMPEG_BIN%*') { ^
         [System.Environment]::SetEnvironmentVariable('PATH', $cur + ';%FFMPEG_BIN%', 'User'); ^
         Write-Host '[OK] PATH updated.' ^
     } else { Write-Host '[OK] Already in PATH.' }"

:: Also update for this session
set "PATH=%PATH%;%FFMPEG_BIN%"

:: Verify
where ffmpeg >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo [OK] ffmpeg is now available:
    ffmpeg -version 2>&1 | findstr /i "ffmpeg version"
) else (
    echo [WARN] ffmpeg still not detected in this session.
    echo        Please restart your terminal or run: set PATH=%%PATH%%;%FFMPEG_BIN%%
)

:: ── 6. Confirm Python can find it ─────────────────────────────
:check_python
echo.
echo ============================================================
echo  Python ffmpeg check
echo ============================================================

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Python not found on PATH. Skipping Python check.
    goto :done
)

python -c "import subprocess, sys; r=subprocess.run(['ffmpeg','-version'],capture_output=True,text=True); print('[OK] Python can call ffmpeg:',r.stdout.splitlines()[0]) if r.returncode==0 else (print('[FAIL] Python cannot call ffmpeg.'), sys.exit(1))"
if %ERRORLEVEL% NEQ 0 (
    echo [HINT] If Python can't find ffmpeg, restart your terminal so the new PATH takes effect,
    echo        then run this script again or call your Python script directly.
)

:done
echo.
echo ============================================================
echo  Setup complete. You can now use ffmpeg in your Python scripts
echo  via subprocess.run(['ffmpeg', ...]) or install ffmpeg-python:
echo    pip install ffmpeg-python
echo ============================================================
echo.


pause
endlocal
