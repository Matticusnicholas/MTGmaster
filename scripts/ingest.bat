@echo off
setlocal
cd /d "%~dp0.."

if not exist .venv\Scripts\activate.bat (
  echo [ERROR] .venv not found. Run scripts\setup.bat first.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

echo ============================================================
echo  MTGMaster ingest
echo ============================================================
echo.

if "%~1"=="" (
  echo No flags given - running --all (rules + every unique card + strategy)
  echo This downloads ~100MB and embeds ~30k cards. It will take a while.
  echo.
  python -m backend.ingest --all
) else (
  python -m backend.ingest %*
)

echo.
echo Ingest finished with exit code %errorlevel%.
echo.
pause
endlocal
