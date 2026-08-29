"""GitHub 上传脚本共用的请求防护：仅允许 https 公网地址。

校验协议、主机名与解析后的 IP（拒绝环回/私有/保留地址），
并对重定向目标重复同样的校验，防止请求被导向内网。
"""
import ipaddress
import socket
import urllib.parse
import urllib.request


def _assert_public_https(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"仅允许 https 协议: {url}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL 缺少主机名: {url}")
    port = parsed.port or 443
    for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(f"拒绝访问非公网地址: {host} -> {ip}")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_GuardedRedirectHandler())


def guarded_urlopen(req, timeout=60):
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    _assert_public_https(url)
    return _OPENER.open(req, timeout=timeout)
