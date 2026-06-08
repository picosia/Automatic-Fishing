@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%sensei_click.py"
set "DEBUG_DIR=%SCRIPT_DIR%debug_last"
set "BUNDLED_PY=C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" "%SCRIPT%" --start-delay 4 --debug-dir "%DEBUG_DIR%"
  exit /b %errorlevel%
)

py -3 "%SCRIPT%" --start-delay 4 --debug-dir "%DEBUG_DIR%"
if %errorlevel% equ 0 exit /b 0

python "%SCRIPT%" --start-delay 4 --debug-dir "%DEBUG_DIR%"
exit /b %errorlevel%
