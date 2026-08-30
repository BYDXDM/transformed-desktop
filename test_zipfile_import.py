#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression test for the packaged FFmpeg bootstrap import."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("win7_main", ROOT / "main.py")
main = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(main)


def test_zipfile_is_available_to_ffmpeg_downloader():
    assert hasattr(main, "zipfile")
    assert callable(main.zipfile.ZipFile)


if __name__ == "__main__":
    test_zipfile_is_available_to_ffmpeg_downloader()
    print("zipfile import test passed")
