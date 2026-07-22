@echo off
setlocal
cd /d "%~dp0\..\app"

where west >nul 2>nul
if errorlevel 1 (
    echo west was not found. Open a Zephyr or ZMK development command prompt first.
    echo Then initialize/update this checkout according to the normal ZMK development setup.
    pause
    exit /b 1
)

set BOARD=%~1
if "%BOARD%"=="" set BOARD=nice_nano_v2

echo Building MegKnob for %BOARD%...
west build -p always -d build-megknob -b %BOARD% -- -DSHIELD=megknob
if errorlevel 1 goto :error

echo.
echo Build complete: app\build-megknob\zephyr\zmk.uf2
exit /b 0

:error
echo MegKnob firmware build failed.
exit /b 1
