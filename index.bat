@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" src\app.py %*
  if errorlevel 1 pause
  exit /b
)

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer and try again.
  pause
  exit /b 1
)

python -c "import eel, pymupdf, PIL, pytesseract" >nul 2>&1
if errorlevel 1 (
  echo Required Python packages are missing.
  echo Install requirements.txt from an approved internal package source.
  pause
  exit /b 1
)

python src\app.py %*
if errorlevel 1 pause

