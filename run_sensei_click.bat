@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%sensei_click.py"
set "DEBUG_DIR=%SCRIPT_DIR%debug_last"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"

if defined SENSEI_PYTHON (
  "%SENSEI_PYTHON%" "%SCRIPT%" --start-delay 4 --debug-dir "%DEBUG_DIR%"
  exit /b %errorlevel%
)

if exist "%VENV_PY%" (
  "%VENV_PY%" "%SCRIPT%" --start-delay 4 --debug-dir "%DEBUG_DIR%"
  exit /b %errorlevel%
)

py -3 "%SCRIPT%" --start-delay 4 --debug-dir "%DEBUG_DIR%"
if %errorlevel% equ 0 exit /b 0

python "%SCRIPT%" --start-delay 4 --debug-dir "%DEBUG_DIR%"
exit /b %errorlevel%
