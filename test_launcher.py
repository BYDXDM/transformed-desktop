#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the Win7 launcher dependency bootstrap."""
import importlib.util
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("launcher", ROOT / "run.pyw")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_dependency_install_isolated_from_broken_proxy():
    proxy_values = {
        "HTTP_PROXY": "http://127.0.0.1:7890",
        "HTTPS_PROXY": "http://localhost:8080",
        "ALL_PROXY": "http://proxy.example:8080",
    }
    with mock.patch.dict(launcher.os.environ, proxy_values, clear=False), \
            mock.patch.object(launcher, "_import_ok", return_value=False), \
            mock.patch.object(launcher.subprocess, "check_call", side_effect=OSError(10061, "connection refused")) as call:
        assert launcher.ensure_deps() is True

    command = call.call_args.args[0]
    assert command[:4] == [launcher.sys.executable, "-m", "pip", "install"]
    pip_env = call.call_args.kwargs["env"]
    assert pip_env["PIP_CONFIG_FILE"] == launcher.os.devnull
    assert "HTTP_PROXY" not in pip_env
    assert "HTTPS_PROXY" not in pip_env
    assert pip_env["ALL_PROXY"] == "http://proxy.example:8080"

    with mock.patch.dict(launcher.os.environ, {
        "HTTPS_PROXY": "http://localhost.example:8080",
        "ALL_PROXY": "http://user:localhost@proxy.example:8080",
    }, clear=False):
        preserved = launcher._pip_env()
        assert preserved["HTTPS_PROXY"] == "http://localhost.example:8080"
        assert preserved["ALL_PROXY"] == "http://user:localhost@proxy.example:8080"


def test_launcher_continues_when_optional_dependency_install_fails():
    with mock.patch.object(launcher, "_import_ok", return_value=False), \
            mock.patch.object(launcher.subprocess, "check_call", side_effect=RuntimeError("offline")):
        assert launcher.ensure_deps() is True


if __name__ == "__main__":
    test_dependency_install_isolated_from_broken_proxy()
    test_launcher_continues_when_optional_dependency_install_fails()
    print("launcher tests passed")
