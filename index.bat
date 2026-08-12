@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer and try again.
  pause
  exit /b 1
)

python -c "import eel, fitz, pdf2image, PIL, pytesseract" >nul 2>&1
if errorlevel 1 (
  echo Required Python packages are missing.
  echo Install requirements.txt from an approved internal package source.
  pause
  exit /b 1
)

python src\app.py
if errorlevel 1 pause
