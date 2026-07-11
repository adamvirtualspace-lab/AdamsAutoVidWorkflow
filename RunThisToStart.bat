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

git clone https://github.com/adamvirtualspace-lab/AdamsAutoVidWorkflow.git

:: %PYTHON_CMD% -c "import os; import shutil; cwd = os.getcwd(); dst=os.path.join(cwd, 'AdamsAutoVidWorkflow'); shutil.move(dst, cwd)"
%PYTHON_CMD% -c "import os, shutil; cwd=os.getcwd(); src=os.path.join(cwd,'AdamsAutoVidWorkflow'); [shutil.move(os.path.join(src,f), cwd) for f in os.listdir(src)]"


pause
endlocal
