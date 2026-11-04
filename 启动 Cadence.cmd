@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Cadence Studio

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. Review the messages above.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src"
set "PYTHONIOENCODING=utf-8"
".venv\Scripts\python.exe" -m cadence_studio %*
if errorlevel 1 (
  echo.
  echo Cadence Studio exited with an error. Review the messages above.
  echo You can also run: .\.venv\Scripts\python.exe -m cadence_studio
  pause
)
endlocal
