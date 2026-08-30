#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transformed Desktop Launcher
双击本文件 auto-install 依赖并启动程序
"""
import os, sys, subprocess, importlib
from urllib.parse import urlparse


_PROXY_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


def _pip_env():
    """Drop only stale loopback proxies; preserve valid remote proxies."""
    env = os.environ.copy()
    # Ignore stale pip.ini while retaining valid remote proxy settings.
    env["PIP_CONFIG_FILE"] = os.devnull
    for name in _PROXY_VARS:
        value = env.get(name, "")
        try:
            hostname = (urlparse(value).hostname or "").lower()
        except ValueError:
            hostname = ""
        if hostname in ("127.0.0.1", "localhost", "::1"):
            env.pop(name, None)
    return env


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def ensure_deps():
    needs = {
        "PIL": "pillow",
        "yt_dlp": "yt-dlp",
        "ebooklib": "ebooklib",
    }
    missing = [pkg for mod, pkg in needs.items() if not _import_ok(mod)]
    if missing:
        print("Installing: " + ", ".join(missing))
        for pkg in missing:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "-q", pkg],
                    env=_pip_env(),
                )
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
