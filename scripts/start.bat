@echo off
chcp 65001 >nul 2>&1
REM ---------------------------------------------------------
REM reese-ag Quick Start Script (Windows)
REM Usage:
REM   start.bat          Auto-setup on first run
REM   start.bat --cli    Start in CLI mode (not Web)
REM ---------------------------------------------------------

setlocal

cd /d "%~dp0\.."

set VENV_DIR=.venv
set PORT=8000
set HOST=0.0.0.0

REM -- 1. Check Python --
set PYTHON=
setlocal enabledelayedexpansion
for %%C in (python py) do (
    where %%C >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%V in ('%%C -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set PY_VER=%%V
        for /f "tokens=*" %%M in ('%%C -c "import sys; print(sys.version_info.major)" 2^>nul') do set PY_MAJOR=%%M
        for /f "tokens=*" %%N in ('%%C -c "import sys; print(sys.version_info.minor)" 2^>nul') do set PY_MINOR=%%N
        if !PY_MAJOR! geq 3 if !PY_MINOR! geq 11 (
            set PYTHON=%%C
            goto :found_python
        )
    )
)

echo [x] Python 3.11+ required. Install: https://www.python.org/downloads/
echo     Check "Add Python to PATH" during install
pause
exit /b 1

:found_python
endlocal & set "PYTHON=%PYTHON%" & set "PY_VER=%PY_VER%"
echo [v] Python %PY_VER% (%PYTHON%)

REM -- 2. Create venv --
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [*] First run, creating virtual environment...
    %PYTHON% -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [x] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [v] Virtual environment created
)

REM Activate venv
call %VENV_DIR%\Scripts\activate.bat
echo [v] Virtual environment activated

REM -- 3. Install dependencies --
set MARKER=%VENV_DIR%\.deps_installed
if not exist "%MARKER%" (
    goto :install_deps
)
REM Check if requirements.txt is newer than marker
for %%A in (requirements.txt) do set REQ_DATE=%%~tA
for %%B in (%MARKER%) do set MARKER_DATE=%%~tB
if "%REQ_DATE%" gtr "%MARKER_DATE%" goto :install_deps
echo [v] Dependencies up to date
goto :deps_done

:install_deps
echo [*] Installing dependencies...
%PYTHON% -m pip install -q --upgrade pip
%PYTHON% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [x] Failed to install dependencies
    pause
    exit /b 1
)
echo. > %MARKER%
echo [v] Dependencies installed

:deps_done

REM -- 4. Configure .env --
if not exist ".env" (
    if exist "resources\.env.example" (
        copy resources\.env.example .env >nul
        call :prompt_env
    ) else (
        echo [x] Missing .env.example file
        pause
        exit /b 1
    )
)

REM -- 5. Create required directories --
if not exist "data" mkdir data
if not exist "output" mkdir output
if not exist "checkpoints" mkdir checkpoints

REM -- 6. Launch --
echo.
if "%~1"=="--cli" (
    echo [v] Starting in CLI mode
    echo -----------------------------------------
    echo Usage: python generate.py new --genre Fantasy --core-pleasure ...
    echo -----------------------------------------
    cmd /k
) else (
    echo [v] Starting Web service: http://localhost:%PORT%
    echo -----------------------------------------
    echo   Open browser: http://localhost:%PORT%
    echo   Press Ctrl+C to stop
    echo -----------------------------------------
    uvicorn main:app --host %HOST% --port %PORT%
)

endlocal
goto :eof

:prompt_env
echo [*] Created .env from .env.example, please fill in API Key
echo.
echo     Set at least one of:
echo       ANTHROPIC_API_KEY=sk-ant-xxx    (Anthropic Claude)
echo       LLM_API_KEY=sk-xxx              (DeepSeek etc.)
echo.
set /p EDIT_NOW="Open .env in notepad now? [Y/n] "
if /i "%EDIT_NOW%"=="n" (
    echo [*] Skipped. Please edit .env manually later.
) else (
    notepad .env
)
goto :eof
