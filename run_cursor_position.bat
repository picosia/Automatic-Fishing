@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%sensei_click.py"
set "BUNDLED_PY=C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" "%SCRIPT%" --print-cursor-on-f12
  exit /b %errorlevel%
)

py -3 "%SCRIPT%" --print-cursor-on-f12
if %errorlevel% equ 0 exit /b 0

python "%SCRIPT%" --print-cursor-on-f12
exit /b %errorlevel%
