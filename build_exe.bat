@echo off
title transformed - Build EXE
echo ============================================
echo   transformed Desktop - Build EXE Package
echo ============================================
echo.
cd /d "%~dp0"

echo [1/3] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.8+ first.
    pause
    exit /b 1
)
echo OK - Python found
echo.

echo [2/3] Installing build tools...
pip install pyinstaller ttkbootstrap pillow yt-dlp mutagen ebooklib
if errorlevel 1 (
    echo WARNING: Some packages failed to install.
)
echo.

echo [3/3] Building EXE...
pyinstaller --onefile --windowed --name "transformed" ^
    --hidden-import ttkbootstrap ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import ebooklib ^
    --hidden-import yt_dlp ^
    --hidden-import mutagen ^
    --collect-all ttkbootstrap ^
    main.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED. Check the error message above.
) else (
    echo.
    echo ============================================
    echo   BUILD SUCCESS!
    echo   File: dist\transformed.exe
    echo ============================================
    echo.
    echo NOTE: FFmpeg is required for MP4 to MP3 feature.
    echo Download: https://ffmpeg.org/download.html
)

echo.
pause
