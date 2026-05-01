@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo  MTGMaster setup
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python is not on PATH.
  echo Install Python 3.10+ from https://www.python.org and re-run this script.
  goto :end
)

if not exist .venv (
  echo Creating virtualenv .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create .venv
    goto :end
  )
) else (
  echo Reusing existing .venv
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo [ERROR] Could not activate .venv
  goto :end
)

echo.
echo Upgrading pip ...
python -m pip install --upgrade pip

echo.
echo Installing Python dependencies from requirements.txt ...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed
  goto :end
)

echo.
where ollama >nul 2>&1
if errorlevel 1 (
  echo [WARN] ollama is not on PATH.
  echo Install Ollama from https://ollama.com, then re-run this script
  echo so the chat and embedding models can be pulled.
) else (
  echo Pulling Ollama chat model: llama3.1:8b
  ollama pull llama3.1:8b
  echo Pulling Ollama embedding model: nomic-embed-text
  ollama pull nomic-embed-text
)

echo.
echo ============================================================
echo  Setup complete.
echo.
echo  Next steps:
echo    1. scripts\ingest.bat            (downloads cards + rules and embeds them)
echo    2. scripts\start.bat             (launches the web app)
echo ============================================================

:end
echo.
pause
endlocal
