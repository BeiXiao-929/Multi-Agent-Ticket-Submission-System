@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Multi-Agent Ticket System - Start

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV_PY=%BACKEND%\.venv\Scripts\python.exe"
set "INSTALL_BAT=%ROOT%安装依赖.bat"
set "OPEN_BROWSER=1"

if not defined PORT set "PORT=8000"
if /i "%~1"=="--no-browser" set "OPEN_BROWSER=0"

echo.
echo ============================================================
echo   Multi-Agent Ticket System - Start
echo ============================================================
echo.

if not exist "%BACKEND%\serve.py" (
    echo [ERROR] Missing %BACKEND%\serve.py
    echo Extract or copy the complete project folder and try again.
    goto :pause_fail
)
if not exist "%ROOT%frontend\index.html" (
    echo [ERROR] Missing %ROOT%frontend\index.html
    echo Extract or copy the complete project folder and try again.
    goto :pause_fail
)
if not exist "%ROOT%frontend\api.js" (
    echo [ERROR] Missing %ROOT%frontend\api.js
    echo Extract or copy the complete project folder and try again.
    goto :pause_fail
)
if not exist "%ROOT%frontend\tailwind.css" (
    echo [ERROR] Missing %ROOT%frontend\tailwind.css
    echo Extract or copy the complete project folder and try again.
    goto :pause_fail
)
if not exist "%ROOT%frontend\copilot-widget.js" (
    echo [ERROR] Missing %ROOT%frontend\copilot-widget.js
    echo Run the dependency installer or copy the complete frontend directory.
    goto :pause_fail
)
if not exist "%ROOT%frontend\copilot-widget.css" (
    echo [ERROR] Missing %ROOT%frontend\copilot-widget.css
    echo Run the dependency installer or copy the complete frontend directory.
    goto :pause_fail
)

set "NEED_INSTALL="
if not exist "%VENV_PY%" (
    set "NEED_INSTALL=1"
) else (
    pushd "%BACKEND%"
    "%VENV_PY%" -c "import fastapi, uvicorn, pydantic, httpx, jwt, multipart, sse_starlette, langgraph, llama_index.core, bm25s, copilotkit, ag_ui_langgraph; from app.main import app" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
    popd
)

if defined NEED_INSTALL (
    echo [1/3] Python environment is missing or invalid. Installing...
    if not exist "%INSTALL_BAT%" (
        echo [ERROR] Missing dependency installer: %INSTALL_BAT%
        goto :pause_fail
    )
    call "%INSTALL_BAT%" --no-pause
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        goto :pause_fail
    )
) else (
    echo [1/3] Python environment is ready.
)

echo.
echo [2/3] Stopping an older service on port %PORT% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pids = @(Get-NetTCPConnection -State Listen -LocalPort %PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); foreach ($p in $pids) { Write-Host ('      Stopping PID ' + $p); Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 500"

set "PORT_READY="
for /l %%I in (1,1,10) do (
    if not defined PORT_READY (
        powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort %PORT% -ErrorAction SilentlyContinue) { exit 1 }" >nul 2>&1
        if not errorlevel 1 set "PORT_READY=1"
        if not defined PORT_READY powershell -NoProfile -Command "Start-Sleep -Milliseconds 500"
    )
)
if not defined PORT_READY (
    echo [ERROR] Port %PORT% is still occupied by another program.
    goto :pause_fail
)

echo.
echo [3/3] Starting the service ...
if exist "%BACKEND%\server.runtime.log" del /q "%BACKEND%\server.runtime.log" >nul 2>&1
set "AGENT_HIDDEN_LOG=1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$arguments = @('serve.py', '--host', '127.0.0.1', '--port', $env:PORT, '--no-browser'); $process = Start-Process -FilePath $env:VENV_PY -ArgumentList $arguments -WorkingDirectory $env:BACKEND -WindowStyle Hidden -PassThru -ErrorAction Stop; if ($null -eq $process) { exit 1 }"
if errorlevel 1 (
    echo [ERROR] Python process could not be started.
    goto :pause_fail
)

set "STARTED="
for /l %%I in (1,1,30) do (
    if not defined STARTED (
        powershell -NoProfile -Command "try { if ((Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
        if not errorlevel 1 set "STARTED=1"
        if not defined STARTED powershell -NoProfile -Command "Start-Sleep -Milliseconds 500"
    )
)
if not defined STARTED (
    echo [ERROR] The service did not respond within 30 seconds.
    if exist "%BACKEND%\server.runtime.log" (
        echo.
        echo ----- server.runtime.log -----
        powershell -NoProfile -Command "Get-Content -LiteralPath '%BACKEND%\server.runtime.log' -Tail 60 -ErrorAction SilentlyContinue"
    )
    goto :pause_fail
)

powershell -NoProfile -Command "try { if ((Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/' -UseBasicParsing -TimeoutSec 5).StatusCode -ne 200) { exit 1 } } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The API is running, but the dashboard page is not reachable.
    echo Check frontend\index.html and then start the service again.
    goto :pause_fail
)

echo.
echo ============================================================
echo   Service is ready.
echo   URL: http://127.0.0.1:%PORT%/?tab=dashboard
echo ============================================================
echo.

if "%OPEN_BROWSER%"=="1" call :open_dashboard

echo Keep this window open only if you need to read the service URL.
powershell -NoProfile -Command "Start-Sleep -Seconds 2"
exit /b 0

:open_dashboard
set "LAUNCH_URL=http://127.0.0.1:%PORT%/?tab=dashboard"
echo Opening browser: %LAUNCH_URL%
powershell -NoProfile -ExecutionPolicy Bypass -Command "$url = '%LAUNCH_URL%'; $opened = $false; try { Start-Process -FilePath $url -ErrorAction Stop; $opened = $true } catch {}; if (-not $opened) { try { Start-Process -FilePath 'rundll32.exe' -ArgumentList @('url.dll,FileProtocolHandler', $url) -ErrorAction Stop; $opened = $true } catch {} }; if (-not $opened) { exit 1 }"
if errorlevel 1 echo [WARN] The browser could not be started automatically.
echo If no tab appeared, open this URL manually:
echo %LAUNCH_URL%
exit /b 0

:pause_fail
echo.
echo Start failed. Keep this window open to read the error.
echo.
pause
exit /b 1
