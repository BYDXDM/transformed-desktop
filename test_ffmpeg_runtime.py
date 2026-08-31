#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for Win7 FFmpeg error handling."""
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


class _Stream:
    def __init__(self, data):
        self.data = data
        self.closed_by_test = False

    def read(self):
        if self.closed_by_test:
            raise AssertionError("stream was closed before stderr was read")
        return self.data

    def close(self):
        self.closed_by_test = True


class _FailedProcess:
    returncode = 1

    def __init__(self):
        self.stdout = _Stream(b"")
        self.stderr = _Stream(b"real ffmpeg error")
        self.communicated = False

    def communicate(self):
        self.communicated = True
        return b"", b"real ffmpeg error"


def test_ffmpeg_failure_uses_communicate():
    process = _FailedProcess()
    with mock.patch.object(main.subprocess, "Popen", return_value=process):
        try:
            main.App._run_ffmpeg_cmd(["ffmpeg", "-version"])
        except RuntimeError as exc:
            assert "real ffmpeg error" in str(exc)
        else:
            raise AssertionError("ffmpeg failure should raise RuntimeError")
    assert process.communicated is True


def test_ffmpeg_failure_preserves_real_stderr():
    with mock.patch.object(main.subprocess, "Popen", return_value=_FailedProcess()):
        try:
            main.App._run_ffmpeg_cmd(["ffmpeg", "-version"])
        except RuntimeError as exc:
            assert "real ffmpeg error" in str(exc)
        else:
            raise AssertionError("ffmpeg failure should raise RuntimeError")


def test_ui_after_skips_callbacks_when_closing():
    app = object.__new__(main.App)
    app._closing = True
    with mock.patch.object(app, "after") as after:
        app._ui_after(lambda: None)
    after.assert_not_called()


def test_ffmpeg_download_fails_when_archive_has_no_bin_directory():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("unexpected/readme.txt", "not an ffmpeg build")

    response = mock.MagicMock()
    response.__enter__.return_value.read.side_effect = [payload.getvalue(), b""]
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(main, "APP_DIR", Path(tmp)), \
            mock.patch.object(main, "guarded_urlopen", return_value=response), \
            mock.patch.object(main.shutil, "which", return_value=None):
        ok, result = main.download_ffmpeg()

    assert ok is False
    assert "bin" in result


if __name__ == "__main__":
    test_ffmpeg_failure_uses_communicate()
    test_ffmpeg_failure_preserves_real_stderr()
    test_ui_after_skips_callbacks_when_closing()
    test_ffmpeg_download_fails_when_archive_has_no_bin_directory()
    print("ffmpeg runtime tests passed")
