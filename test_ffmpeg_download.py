#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the packaged FFmpeg bootstrap download."""
import importlib.util
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("win7_main", ROOT / "main.py")
main = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(main)


def _fake_ffmpeg_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("ffmpeg-master/bin/ffmpeg.exe", "fake-ffmpeg")
        z.writestr("ffmpeg-master/bin/ffprobe.exe", "fake-ffprobe")
    return buffer.getvalue()


def test_download_ffmpeg_uses_guarded_connection_and_installs():
    with tempfile.TemporaryDirectory() as tmp:
        opener = mock.MagicMock()
        opener.__enter__.return_value.read.side_effect = [_fake_ffmpeg_zip(), b""]
        with mock.patch.object(main, "APP_DIR", Path(tmp)), \
                mock.patch.object(main.shutil, "which", return_value=None), \
                mock.patch.object(main._urlreq, "urlretrieve",
                                  side_effect=AssertionError("must not use urlretrieve")), \
                mock.patch.object(main, "guarded_urlopen", return_value=opener) as guarded:
            ok, result = main.download_ffmpeg()

        assert ok is True, result
        installed = Path(tmp) / "ffmpeg" / "bin" / "ffmpeg.exe"
        assert installed.exists()
        assert guarded.call_args.args[0].startswith("https://github.com/BtbN/FFmpeg-Builds")


if __name__ == "__main__":
    test_download_ffmpeg_uses_guarded_connection_and_installs()
    print("ffmpeg download tests passed")
