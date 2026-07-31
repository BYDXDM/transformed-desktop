@echo off
title transformed - Install Dependencies
echo ============================================
echo   transformed Desktop - Dependency Install
echo ============================================
echo.
echo [1/3] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.8+ first.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo OK - Python found
echo.
echo [2/3] Installing packages...
pip install ttkbootstrap pillow yt-dlp mutagen ebooklib
if errorlevel 1 (
    echo WARNING: Some packages failed to install.
)
echo.
echo [3/3] Starting app...
echo.
echo Installing FFmpeg is recommended for MP4 to MP3:
echo   1. Download from https://ffmpeg.org/download.html
echo   2. Add ffmpeg.exe to your system PATH
echo.
echo ============================================
echo   Done! Now run:
echo   python main.py
echo ============================================
echo.
pause
