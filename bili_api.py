# -*- coding: utf-8 -*-
"""B站相关网络功能：外网连通性检测、歌曲搜索、扫码登录与 Cookie 管理。"""
import json
import re
import threading
import time
import urllib.parse
import urllib.request as _urlreq
from pathlib import Path

from app_common import Logger, _validated_output_file
from net_guard import guarded_urlopen

# B站登录凭据（仅保存在本机）：json 为主存储，netscape 供 yt-dlp 使用
BILI_COOKIES_FILE = (Path.home() / ".transformed_cookies.json").resolve()
BILI_COOKIEFILE = (Path.home() / ".transformed_cookies.txt").resolve()

_FOREIGN_CACHE = {"ts": 0.0, "ok": False, "reason": ""}
_FOREIGN_CACHE_TTL = 600  # 检测结果缓存 10 分钟，避免每个外网任务都等 5 秒探测


def check_foreign_access():
    """检测当前网络能否访问外网(YouTube等)。返回 (bool, 信息)
    - 能访问外网: (True, 描述)
    - 不能(需代理): (False, 原因描述)
    """
    now = time.time()
    if now - _FOREIGN_CACHE["ts"] < _FOREIGN_CACHE_TTL:
        return _FOREIGN_CACHE["ok"], _FOREIGN_CACHE["reason"]

    result = None
    # 通过 ipinfo 获取出口 IP 归属地
    try:
        req = _urlreq.Request("https://ipinfo.io/json",
                             headers={"User-Agent": "Mozilla/5.0"})
        with guarded_urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
            country = data.get("country", "")
            ip = data.get("ip", "?")
            if country == "CN":
                result = (False, f"当前 IP({ip})归属中国，直连外网受限，下载 YouTube/X 需代理")
            else:
                result = (True, f"当前 IP({ip}) 非中国归属，可访问外网")
    except Exception:
        # ipinfo 都连不上，尝试直接测 youtube 连通性
        try:
            req = _urlreq.Request("https://www.youtube.com",
                                 headers={"User-Agent": "Mozilla/5.0"})
            with guarded_urlopen(req, timeout=5) as r:
                result = (True, "可访问外网(YouTube可达)")
        except Exception:
            result = (False, "无法访问外网(YouTube不可达)，可能需要代理")

    _FOREIGN_CACHE.update({"ts": now, "ok": result[0], "reason": result[1]})
    return result


def _get_buvid3():
    """从 B 站指纹接口获取真实 buvid3（硬编码假值会被 412 风控拦截）"""
    try:
        req = _urlreq.Request(
            "https://api.bilibili.com/x/frontend/finger/spi",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })
        with guarded_urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        b_3 = (data.get("data") or {}).get("b_3", "")
        if b_3:
            return b_3
    except Exception as e:
        Logger.log(f"获取 buvid3 失败: {e}")
    return None


def search_bilibili_song(query):
    """从 B 站搜索视频（歌曲），返回第一个结果的视频链接；无结果返回 None。
    用 B 站官方搜索接口（免签）。先获取真实 buvid3 再请求，绕过 412 风控。"""
    results = search_bilibili_songs(query, limit=1)
    return results[0]["url"] if results else None


def search_bilibili_songs(query, limit=6):
    """从 B 站搜索视频（歌曲），返回结果列表 [{bvid, title, author, duration, url}]。
    自动过滤翻唱、伴奏、纯音乐等非原唱结果。"""
    results = []
    try:
        enc = urllib.parse.quote(query)
        buvid3 = _get_buvid3()
        cookie = f"buvid3={buvid3}" if buvid3 else "buvid3=infoc"
        req = _urlreq.Request(
            f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={enc}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/",
                "Cookie": cookie,
            })
        with guarded_urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("code") != 0:
            Logger.log(f"B站搜索被拒 code={data.get('code')}: {data.get('message','')}")
            return results
        raw = data.get("data", {}).get("result", [])
        # 过滤关键词
        skip_kw = ("翻唱", "cover", "伴奏", "纯音乐", "inst", "karaoke", "MV", "现场", "live")
        for item in raw:
            if not isinstance(item, dict) or item.get("type") != "video":
                continue
            bvid = item.get("bvid", "")
            if not bvid:
                continue
            title = re.sub(r"</?em[^>]*>", "", item.get("title", "")).strip()
            author = item.get("author", "")
            duration = item.get("duration", "")
            # 过滤非原唱
            tl = title.lower()
            if any(kw in tl for kw in skip_kw):
                continue
            results.append({
                "bvid": bvid,
                "title": title,
                "author": author,
                "duration": duration,
                "url": f"https://www.bilibili.com/video/{bvid}",
            })
            if len(results) >= limit:
                break
        Logger.log(f"B站搜索 '{query}' → {len(results)} 条结果")
    except Exception as e:
        Logger.log(f"B站搜索异常: {e}")
    return results


# ===== 扫码登录 =====

def generate_login_qr():
    """生成 B 站登录二维码。返回 (qrcode_key, qr_url)；失败返回 (None, None)"""
    try:
        req = _urlreq.Request(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Referer": "https://passport.bilibili.com/"})
        with guarded_urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("code") != 0:
            return None, None
        d = data.get("data") or {}
        return d.get("qrcode_key"), d.get("url")
    except Exception as e:
        Logger.log(f"生成登录二维码失败: {e}")
        return None, None


def parse_cookie_params(url):
    """从跨域登录 URL 的查询参数中解析 Cookie 键值对"""
    try:
        query = urllib.parse.urlsplit(str(url)).query
        return {k: v[0] for k, v in urllib.parse.parse_qs(query).items() if v}
    except Exception:
        return {}


def poll_login_qr(qrcode_key):
    """轮询二维码登录状态。
    返回 (code, cookies_dict_or_None, message)；
    code=0 表示成功，cookies 已解析；86038 已过期；86090 已扫码未确认；86101 等待扫码。"""
    try:
        enc = urllib.parse.quote(str(qrcode_key))
        req = _urlreq.Request(
            f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={enc}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Referer": "https://passport.bilibili.com/"})
        with guarded_urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        d = data.get("data") or {}
        code = int(d.get("code", data.get("code", -1)))
        if code == 0:
            cookies = parse_cookie_params(d.get("url") or "")
            if not cookies.get("SESSDATA"):
                return -1, None, "登录响应中缺少 SESSDATA"
            return 0, cookies, "登录成功"
        return code, None, str(d.get("message") or data.get("message") or "")
    except Exception as e:
        Logger.log(f"轮询二维码状态失败: {e}")
        return -1, None, str(e)


def write_netscape_cookies(path, cookies, domain=".bilibili.com"):
    """把 Cookie 字典写成 Netscape 格式（yt-dlp cookiefile 要求）"""
    lines = ["# Netscape HTTP Cookie File",
             "# 由 transformed 生成，请勿外传（等同登录凭据）"]
    for name, value in cookies.items():
        lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_bili_cookies(cookies):
    """保存登录凭据：json 主存储 + netscape（yt-dlp cookiefile），均在主目录内"""
    target = _validated_output_file(BILI_COOKIES_FILE, Path.home())
    Path(target).write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
    cookiefile = _validated_output_file(BILI_COOKIEFILE, Path.home())
    write_netscape_cookies(cookiefile, cookies)


def bili_cookies_exist():
    return BILI_COOKIES_FILE.exists() and BILI_COOKIEFILE.exists()


def bili_logout():
    for p in (BILI_COOKIES_FILE, BILI_COOKIEFILE):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def bili_user_id():
    """读取已登录的 DedeUserID（未登录返回空串）"""
    try:
        data = json.loads(BILI_COOKIES_FILE.read_text(encoding="utf-8"))
        return str(data.get("DedeUserID") or "")
    except Exception:
        return ""


_POLL_INTERVAL = 2.0
_POLL_TIMEOUT = 180.0


def wait_login_qr(qrcode_key, status_cb=None, stop_event=None):
    """阻塞轮询直到登录成功/过期/超时。返回 (ok, cookies, message)。
    status_cb(message) 用于透出中间状态；stop_event 置位时中止。"""
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return False, None, "已取消"
        code, cookies, msg = poll_login_qr(qrcode_key)
        if code == 0:
            return True, cookies, "登录成功"
        if code == 86038:
            return False, None, "二维码已过期，请重新获取"
        if code == 86090:
            status_cb and status_cb("已扫码，请在手机上确认…")
        elif code == 86101:
            status_cb and status_cb("等待扫码…")
        time.sleep(_POLL_INTERVAL)
    return False, None, "二维码超时，请重试"
