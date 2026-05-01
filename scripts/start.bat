@echo off
setlocal
cd /d "%~dp0.."

if not exist .venv\Scripts\activate.bat (
  echo [ERROR] .venv not found. Run scripts\setup.bat first.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

set MTGMASTER_HOST=%MTGMASTER_HOST%
if "%MTGMASTER_HOST%"=="" set MTGMASTER_HOST=127.0.0.1
set MTGMASTER_PORT=%MTGMASTER_PORT%
if "%MTGMASTER_PORT%"=="" set MTGMASTER_PORT=8765

echo ============================================================
echo  Starting MTGMaster
echo  Open http://%MTGMASTER_HOST%:%MTGMASTER_PORT% in your browser.
echo  Press Ctrl+C to stop the server.
echo ============================================================
echo.

python -m uvicorn backend.main:app --host %MTGMASTER_HOST% --port %MTGMASTER_PORT%

echo.
echo Server stopped (exit code %errorlevel%).
echo.
pause
endlocal
