@echo off
echo ============================================
echo  YoutubeTranslator - Installation
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from https://python.org
    pause & exit /b 1
)

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo WARNING: ffmpeg not found in PATH.
    echo Download from https://ffmpeg.org/download.html and add to PATH.
    echo.
)

:: Create venv if it doesn't exist
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate and install
echo Activating venv and installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ============================================
echo  Done! To start the app:
echo.
echo  venv\Scripts\activate
echo  python run.py
echo.
echo  Then open: http://localhost:8000/app
echo ============================================
pause
