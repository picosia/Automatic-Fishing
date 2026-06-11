@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%sensei_click.py"
set "DEBUG_DIR=%SCRIPT_DIR%debug_last"
set "CONFIG=%SCRIPT_DIR%auto_fishing_start.json"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"

if defined SENSEI_PYTHON (
  "%SENSEI_PYTHON%" "%SCRIPT%" --scheduled-auto-loop --start-delay 4 --schedule-config "%CONFIG%" --start-wait-timeout 90 --start-poll-interval 0.25 --start-confirm-frames 2 --after-start-delay 0.2 --debug-dir "%DEBUG_DIR%" --no-start-button-debug-images --constellation-debug-images minimal-images
  exit /b %errorlevel%
)

if exist "%VENV_PY%" (
  "%VENV_PY%" "%SCRIPT%" --scheduled-auto-loop --start-delay 4 --schedule-config "%CONFIG%" --start-wait-timeout 90 --start-poll-interval 0.25 --start-confirm-frames 2 --after-start-delay 0.2 --debug-dir "%DEBUG_DIR%" --no-start-button-debug-images --constellation-debug-images minimal-images
  exit /b %errorlevel%
)

py -3 "%SCRIPT%" --scheduled-auto-loop --start-delay 4 --schedule-config "%CONFIG%" --start-wait-timeout 90 --start-poll-interval 0.25 --start-confirm-frames 2 --after-start-delay 0.2 --debug-dir "%DEBUG_DIR%" --no-start-button-debug-images --constellation-debug-images minimal-images
if %errorlevel% equ 0 exit /b 0

python "%SCRIPT%" --scheduled-auto-loop --start-delay 4 --schedule-config "%CONFIG%" --start-wait-timeout 90 --start-poll-interval 0.25 --start-confirm-frames 2 --after-start-delay 0.2 --debug-dir "%DEBUG_DIR%" --no-start-button-debug-images --constellation-debug-images minimal-images
exit /b %errorlevel%
