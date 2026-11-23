@echo off
rem One-time setup: creates software\.venv with Python 3.11 and installs requirements.txt.
cd /d "%~dp0"
echo Creating software\.venv and installing packages (this takes a while). Output: setup_log.txt
echo Setup log > setup_log.txt
if not exist .venv\Scripts\python.exe py -3.11 -m venv .venv >> setup_log.txt 2>&1
".venv\Scripts\python.exe" -m pip install --upgrade pip >> setup_log.txt 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt >> setup_log.txt 2>&1
".venv\Scripts\python.exe" -c "import fastapi, watchfiles, faster_whisper, kokoro, en_core_web_sm, nvidia.cudnn; print('SETUP OK')" >> setup_log.txt 2>&1
type setup_log.txt | findstr /C:"SETUP OK" >nul && echo SETUP OK || echo SETUP FAILED, see software\setup_log.txt
pause
