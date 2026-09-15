@echo off
REM ============================================================
REM  Dirty Work Cleaner - one-click launcher
REM  (ASCII-only output on purpose, safe under any console codepage)
REM ============================================================
cd /d "%~dp0"

set PYEXE=.venv\Scripts\python.exe

if not exist "%PYEXE%" (
    echo [1/3] First run - creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 goto nopython
    echo [2/3] Installing dependencies from requirements.txt ...
    "%PYEXE%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    "%PYEXE%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 goto pipfail
) else (
    echo [1/3] Virtual environment found - skipping install.
)

echo [3/3] Starting server on http://127.0.0.1:8080/
echo.
echo   Press Ctrl+C to stop.
echo.
start "" http://127.0.0.1:8080/
"%PYEXE%" app.py
goto end

:nopython
echo.
echo ERROR: "python" was not found in PATH.
echo Install Python 3.10+ and tick "Add python.exe to PATH".
echo Download: https://www.python.org/downloads/
pause
goto end

:pipfail
echo.
echo ERROR: dependency installation failed.
echo Check your network or proxy, then run this script again.
pause
goto end

:end
