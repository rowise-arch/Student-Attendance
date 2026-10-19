@echo off
cd /d "%~dp0"
echo Installing requirements (first run only)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Python was not found or pip failed. Install Python 3.10+ from python.org
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)
rem Optional: needed only for the ACR122U reader
python -m pip install -q pyscard || echo Note: pyscard could not be installed - the ACR122U reader will not work.
python app.py
pause
