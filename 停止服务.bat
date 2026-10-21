@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Multi-Agent Ticket System - Stop

if not defined PORT set "PORT=8000"
if /i "%~1"=="--port" (
    if not "%~2"=="" set "PORT=%~2"
) else if not "%~1"=="" (
    set "PORT=%~1"
)
powershell -NoProfile -Command "if ('%PORT%' -notmatch '^[0-9]+$') { exit 1 }"
if errorlevel 1 (
    echo [ERROR] Invalid port: %PORT%
    exit /b 1
)

echo.
echo ============================================================
echo   Multi-Agent Ticket System - Stop
echo ============================================================
echo.
echo Looking for a service listening on port %PORT% ...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$pids = @(Get-NetTCPConnection -State Listen -LocalPort %PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); if ($pids.Count -eq 0) { Write-Host 'No listener was found.' } else { foreach ($p in $pids) { Write-Host ('Stopping PID ' + $p + ' ...'); Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 500 }"

powershell -NoProfile -Command "Start-Sleep -Milliseconds 500"
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort %PORT% -ErrorAction SilentlyContinue) { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Port %PORT% is still in use. Another program may own it.
) else (
    echo Service stopped successfully.
)

:done
echo.
powershell -NoProfile -Command "Start-Sleep -Milliseconds 500"
exit /b 0
