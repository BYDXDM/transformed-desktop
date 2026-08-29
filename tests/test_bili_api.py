import tempfile
import unittest
from pathlib import Path

from bili_api import parse_cookie_params, write_netscape_cookies


class ParseCookieParamsTests(unittest.TestCase):
    def test_parses_qr_login_url(self):
        url = ("https://passport.bilibili.com/h5-app/passport/login/crossDomain"
               "?DedeUserID=12345&Expires=42"
               "&SESSDATA=abc%2Cdef&bili_jct=token123&gourl=%2F")
        cookies = parse_cookie_params(url)
        self.assertEqual(cookies["DedeUserID"], "12345")
        self.assertEqual(cookies["SESSDATA"], "abc,def")  # URL 解码后
        self.assertEqual(cookies["bili_jct"], "token123")

    def test_invalid_url_returns_empty(self):
        self.assertEqual(parse_cookie_params(""), {})
        self.assertEqual(parse_cookie_params(None), {})


class WriteNetscapeCookiesTests(unittest.TestCase):
    def test_writes_netscape_format(self):
        p = Path(tempfile.mkdtemp()) / "cookies.txt"
        write_netscape_cookies(p, {"SESSDATA": "abc,def", "bili_jct": "t"})
        lines = p.read_text(encoding="utf-8").splitlines()
        cookie_lines = [l for l in lines if not l.startswith("#")]
        self.assertEqual(len(cookie_lines), 2)
        mapping = {}
        for line in cookie_lines:
            parts = line.split("\t")
            self.assertEqual(len(parts), 7)
            self.assertEqual(parts[0], ".bilibili.com")
            self.assertEqual(parts[2], "/")
            mapping[parts[5]] = parts[6]
        self.assertEqual(mapping, {"SESSDATA": "abc,def", "bili_jct": "t"})


if __name__ == "__main__":
    unittest.main()
