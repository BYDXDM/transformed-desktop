@echo off
chcp 65001 >nul
title 正在打包 transformed 桌面版...

echo ========================================
echo   transformed 桌面版 - 打包工具
echo ========================================
echo.

echo [1/3] 检查 Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)
echo ✓ Python 已安装

echo [2/3] 安装依赖...
pip install pyinstaller ttkbootstrap pillow yt-dlp mutagen ebooklib
if %errorlevel% neq 0 (
    echo ⚠ 部分依赖安装失败，请手动安装
)

echo [3/3] 打包中...
cd /d "%~dp0"
pyinstaller --onefile --windowed --name "transformed" ^
    --hidden-import ttkbootstrap ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import ebooklib ^
    --hidden-import yt_dlp ^
    --hidden-import mutagen ^
    --collect-all ttkbootstrap ^
    main.py

if %errorlevel% equ 0 (
    echo.
    echo ✅ 打包成功！
    echo 文件位置: dist\transformed.exe
    echo.
    echo 注意：MP4→MP3 功能需要安装 ffmpeg
    echo 下载地址: https://ffmpeg.org/download.html
) else (
    echo ❌ 打包失败，请检查错误信息
)

pause
