#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transformed Desktop Launcher
双击本文件 auto-install 依赖并启动程序
"""
import os, sys, subprocess, importlib, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# yt-dlp 升级检查标记：每 24 小时最多联网检查一次，避免每次启动都等 pip
CHECK_MARKER = os.path.join(os.path.expanduser("~"), ".transformed_ytdlp_check")
CHECK_INTERVAL = 24 * 3600

def ensure_deps():
    needs = {
        "ttkbootstrap": "ttkbootstrap",
        "PIL": "pillow",
        "yt_dlp": "yt-dlp",
        "ebooklib": "ebooklib",
        "mutagen": "mutagen",
        "tkinterdnd2": "tkinterdnd2",
        "qrcode": "qrcode",
    }
    missing = [pkg for mod, pkg in needs.items() if not _import_ok(mod)]
    if missing:
        print("Installing: " + ", ".join(missing))
        for pkg in missing:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
            except Exception as e:
                print(f"  - {pkg} failed: {e}")
    # yt-dlp 必须保持较新版本：B站/YouTube 反爬频繁变动，旧版无法下载。
    # 但每次启动都联网升级太慢，改为每天最多检查一次。
    if _should_check_ytdlp():
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-U",
                                   "--disable-pip-version-check", "yt-dlp"])
            _mark_checked()
            print("yt-dlp checked (latest)")
        except Exception as e:
            print(f"  - yt-dlp upgrade failed: {e}")
    return True

def _should_check_ytdlp():
    try:
        return (time.time() - os.path.getmtime(CHECK_MARKER)) >= CHECK_INTERVAL
    except OSError:
        return True

def _mark_checked():
    try:
        with open(CHECK_MARKER, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass

def _import_ok(mod):
    try:
        importlib.import_module(mod)
        return True
    except ImportError:
        return False

def main():
    try:
        ensure_deps()
    except Exception as e:
        print(f"Dep install error: {e}")
        input("Press Enter to exit...")
        return

    try:
        import main  # 直接从此脚本目录 import
    except Exception as e:
        print(f"Failed to load main.py: {e}")
        input("Press Enter to exit...")
        return

    app = main.App()
    app.mainloop()

if __name__ == "__main__":
    main()
