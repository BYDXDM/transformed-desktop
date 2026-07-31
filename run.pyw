#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transformed Desktop Launcher
双击本文件 auto-install 依赖并启动程序
"""
import os, sys, subprocess, importlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def ensure_deps():
    needs = {
        "ttkbootstrap": "ttkbootstrap",
        "PIL": "pillow",
        "yt_dlp": "yt-dlp",
        "ebooklib": "ebooklib",
        "mutagen": "mutagen",
    }
    missing = [pkg for mod, pkg in needs.items() if not _import_ok(mod)]
    if missing:
        print("Installing: " + ", ".join(missing))
        for pkg in missing:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
            except Exception as e:
                print(f"  - {pkg} failed: {e}")
    return True

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
