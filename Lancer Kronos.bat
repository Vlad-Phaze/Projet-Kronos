@echo off
cd /d "%~dp0"
py -3 launch_kronos.py
if errorlevel 1 (
  echo.
  echo Kronos s'est arrete. Appuie sur une touche pour fermer.
  pause >nul
)
