@echo off
rem Browser mode: http://localhost:5000. Python edits restart the backend, UI edits reload the page.
rem Run SETUP.cmd once first. Logs go to dev_log.txt in the repo root.
cd /d "%~dp0.."
title Hullabaloo dev server (close this window to stop)
echo %date% %time% DEV.cmd started >> dev_log.txt
if not exist "software\.venv\Scripts\python.exe" (
  echo software\.venv is missing: run software\SETUP.cmd first. >> dev_log.txt
  echo software\.venv is missing: run software\SETUP.cmd first.
  pause
  exit /b 1
)
"software\.venv\Scripts\python.exe" software\dev.py %*
if exist dev_stopped.flag (
  del dev_stopped.flag
  echo %date% %time% stopped with the Shut down button >> dev_log.txt
  exit
)
echo %date% %time% dev.py exited with code %errorlevel% >> dev_log.txt
echo.
echo The dev server stopped (code %errorlevel%). See dev_log.txt.
pause
