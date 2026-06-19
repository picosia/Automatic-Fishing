@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"

cd /d "%SCRIPT_DIR%"

if defined SENSEI_PYTHON (
  "%SENSEI_PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements-dev.txt"
  if errorlevel 1 exit /b %errorlevel%
  "%SENSEI_PYTHON%" -m PyInstaller --clean --noconfirm "%SCRIPT_DIR%sensei_gui.spec"
  exit /b %errorlevel%
) else if exist "%VENV_PY%" (
  "%VENV_PY%" -m pip install -r "%SCRIPT_DIR%requirements-dev.txt"
  if errorlevel 1 exit /b %errorlevel%
  "%VENV_PY%" -m PyInstaller --clean --noconfirm "%SCRIPT_DIR%sensei_gui.spec"
  exit /b %errorlevel%
) else (
  py -3 -m pip install -r "%SCRIPT_DIR%requirements-dev.txt"
  if errorlevel 1 exit /b %errorlevel%
  py -3 -m PyInstaller --clean --noconfirm "%SCRIPT_DIR%sensei_gui.spec"
  exit /b %errorlevel%
)
