@echo off
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul
if errorlevel 1 (
    echo Python Launcher was not found. Install Python 3.11 from python.org.
    pause
    exit /b 1
)

if not exist ".venv-megknob\Scripts\python.exe" (
    echo Creating MegKnob viewer environment...
    py -3.11 -m venv .venv-megknob || goto :error
)

echo Installing or updating viewer dependencies...
".venv-megknob\Scripts\python.exe" -m pip install -r tools\requirements-hall-viewer.txt || goto :error
".venv-megknob\Scripts\python.exe" tools\megknob_hall_viewer.py
exit /b %errorlevel%

:error
echo Failed to prepare the MegKnob viewer.
pause
exit /b 1
