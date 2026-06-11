@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "REQ=%SCRIPT_DIR%requirements.txt"

if not exist "%VENV_PY%" (
  py -3 -m venv "%VENV_DIR%"
  if errorlevel 1 (
    python -m venv "%VENV_DIR%"
  )
)

if not exist "%VENV_PY%" (
  echo ERROR: could not create .venv. Install Python 3 and try again.
  exit /b 1
)

"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 exit /b %errorlevel%

"%VENV_PY%" -m pip install -r "%REQ%"
exit /b %errorlevel%
