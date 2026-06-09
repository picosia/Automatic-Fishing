@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%sensei_click.py"
set "DEBUG_DIR=%SCRIPT_DIR%debug_last"
set "BUNDLED_PY=C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" "%SCRIPT%" --auto-loop --start-delay 1 --start-wait-timeout 90 --start-poll-interval 0.25 --start-confirm-frames 2 --after-start-delay 0.2 --debug-dir "%DEBUG_DIR%"
  exit /b %errorlevel%
)

py -3 "%SCRIPT%" --auto-loop --start-delay 1 --start-wait-timeout 90 --start-poll-interval 0.25 --start-confirm-frames 2 --after-start-delay 0.2 --debug-dir "%DEBUG_DIR%"
if %errorlevel% equ 0 exit /b 0

python "%SCRIPT%" --auto-loop --start-delay 1 --start-wait-timeout 90 --start-poll-interval 0.25 --start-confirm-frames 2 --after-start-delay 0.2 --debug-dir "%DEBUG_DIR%"
exit /b %errorlevel%
