#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for packaged Win7 network proxy handling."""
import importlib.util
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("win7_main", ROOT / "main.py")
main = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(main)


def test_guarded_opener_ignores_loopback_proxy_and_keeps_remote_proxy():
    main._GUARDED_OPENER = None
    proxies = {
        "http": "http://127.0.0.1:7890",
        "https": "http://proxy.example:8080",
        "no": "localhost,127.0.0.1",
    }
    opener = mock.Mock()
    with mock.patch.object(main._urlreq, "getproxies", return_value=proxies), \
            mock.patch.object(main, "_assert_public_http_url"), \
            mock.patch.object(main._urlreq, "build_opener", return_value=opener) as build:
        main.guarded_urlopen(main._urlreq.Request("https://example.com"), timeout=1)

    handlers = build.call_args.args
    proxy_handler = next(
        handler for handler in handlers
        if isinstance(handler, main._urlreq.ProxyHandler)
    )
    assert "http" not in proxy_handler.proxies
    assert proxy_handler.proxies["https"] == "http://proxy.example:8080"


if __name__ == "__main__":
    test_guarded_opener_ignores_loopback_proxy_and_keeps_remote_proxy()
    print("network proxy tests passed")
