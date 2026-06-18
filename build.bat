@echo off
echo === GTalk Build Script ===
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Install dependencies
echo Installing dependencies...
pip install PyQt6 cryptography pyinstaller --quiet

:: Build
echo Building GTalk.exe...
pyinstaller --onefile --windowed --name GTalk --clean gtalk.py

echo.
echo === Build complete: dist\GTalk.exe ===
pause
