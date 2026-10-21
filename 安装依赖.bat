@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Multi-Agent Ticket System - Install Dependencies

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%BACKEND%\.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "REQ=%BACKEND%\requirements.txt"
set "VERIFY_ONLY="
set "NO_PAUSE="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--no-pause" set "NO_PAUSE=1"
if /i "%~1"=="--verify" (
    set "VERIFY_ONLY=1"
    set "NO_PAUSE=1"
)
shift
goto :parse_args
:args_done

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "AGENT_LLM_ENABLED=0"

echo.
echo ============================================================
echo   Multi-Agent Ticket System - Install / Verify
echo ============================================================
echo.

if not exist "%BACKEND%\serve.py" (
    echo [ERROR] Missing %BACKEND%\serve.py
    goto :fail
)
if not exist "%REQ%" (
    echo [ERROR] Missing %BACKEND%\requirements.txt
    goto :fail
)
if not exist "%ROOT%frontend\index.html" (
    echo [ERROR] Missing %ROOT%frontend\index.html
    echo Copy the complete project folder, including the frontend directory.
    goto :fail
)
if not exist "%ROOT%frontend\api.js" (
    echo [ERROR] Missing %ROOT%frontend\api.js
    goto :fail
)
if not exist "%ROOT%frontend\tailwind.css" (
    echo [ERROR] Missing %ROOT%frontend\tailwind.css
    echo Copy the complete project folder, including the frontend directory.
    goto :fail
)
if not exist "%ROOT%frontend\copilot-widget.js" (
    echo [ERROR] Missing %ROOT%frontend\copilot-widget.js
    echo Copy the prebuilt Copilot widget file before using this project on another computer.
    goto :fail
)
if not exist "%ROOT%frontend\copilot-widget.css" (
    echo [ERROR] Missing %ROOT%frontend\copilot-widget.css
    echo Copy the prebuilt Copilot widget stylesheet before using this project on another computer.
    goto :fail
)

if defined VERIFY_ONLY goto :verify

echo [1/4] Finding Python 3.10+ ...
set "PY_CMD="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python3"
)
if not defined PY_CMD (
    echo [ERROR] Python 3.10+ was not found.
    echo Install Python and enable "Add Python to PATH":
    echo https://www.python.org/downloads/windows/
    goto :fail
)
echo Using: %PY_CMD%
%PY_CMD% --version

echo.
echo [2/4] Checking virtual environment ...
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo Existing environment is invalid. Rebuilding...
        rmdir /s /q "%VENV%" >nul 2>&1
    )
)
if not exist "%VENV_PY%" (
    echo Creating %VENV% ...
    %PY_CMD% -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        goto :fail
    )
)
"%VENV_PY%" --version
if errorlevel 1 (
    echo [ERROR] The virtual environment Python cannot run.
    goto :fail
)

echo.
echo [3/4] Installing dependencies ...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 echo [WARN] pip upgrade failed; continuing.
"%VENV_PY%" -m pip install -r "%REQ%"
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check network or proxy settings.
    goto :fail
)
"%VENV_PY%" -m pip check
if errorlevel 1 (
    echo [ERROR] Dependency conflicts were detected.
    goto :fail
)

:verify
if not exist "%VENV_PY%" (
    echo [ERROR] Virtual environment missing. Run this script without --verify first.
    goto :fail
)

"%VENV_PY%" -m pip check
if errorlevel 1 (
    echo [ERROR] Dependency conflicts were detected.
    goto :fail
)

echo.
echo [4/4] Verifying application modules ...
pushd "%BACKEND%"
"%VENV_PY%" -c "import sys, fastapi, uvicorn, pydantic, httpx, jwt, multipart, sse_starlette, langgraph, llama_index.core, bm25s, copilotkit, ag_ui_langgraph; from app.main import app; print(f'Python {sys.version.split()[0]} | FastAPI {fastapi.__version__} | application modules OK')"
set "VERIFY_RESULT=%errorlevel%"
popd
if not "%VERIFY_RESULT%"=="0" (
    echo [ERROR] Application module import failed.
    goto :fail
)

echo.
echo ============================================================
echo   Environment is ready. Run the start BAT file.
echo ============================================================
echo.
echo The prebuilt Copilot widget is included. Node.js and Visual C++ Build Tools are not required.
echo.
if not defined NO_PAUSE pause
exit /b 0

:fail
echo.
echo Installation or verification did not complete.
echo.
if not defined NO_PAUSE pause
exit /b 1
