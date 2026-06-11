@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%sensei_click.py"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"

if defined SENSEI_PYTHON (
  "%SENSEI_PYTHON%" "%SCRIPT%" --print-cursor-on-f12
  exit /b %errorlevel%
)

if exist "%VENV_PY%" (
  "%VENV_PY%" "%SCRIPT%" --print-cursor-on-f12
  exit /b %errorlevel%
)

py -3 "%SCRIPT%" --print-cursor-on-f12
if %errorlevel% equ 0 exit /b 0

python "%SCRIPT%" --print-cursor-on-f12
exit /b %errorlevel%
