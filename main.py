#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transformed 桌面版 - 现代化 UI
格式转换 + 网络视频下载
"""

import sys
# 强制使用 UTF-8，解决 Windows 控制台乱码
if sys.stdout and hasattr(sys.stdout, 'encoding'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import threading
import time
import os
import json
import re
import shutil
import subprocess
import urllib.request as _urlreq
import urllib.parse
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageTk
from download_options import build_download_options, prepare_url
from ui_helpers import (
    UiProgressEventQueue,
    selected_history_ids,
    compute_queue_move,
    is_newer_version,
)
from net_guard import guarded_urlopen

APP_VERSION = "v1.5.0"
UI_FONT = "Microsoft YaHei UI"

# 深浅色主题对应的自绘控件颜色（ttk 部件由主题自动适配）。
# btn = 切换按钮的文字（描述点击后将切到的目标主题）
THEMES = {
    "superhero": {
        "btn": "🌙 深色",
        "bg": "#1a1a2e", "fg": "#e0e0e0", "ph": "#667788",
        "zebra_odd": "#223140", "zebra_even": "#2b3e50",
        "q_tags": {"waiting": "#8899aa", "downloading": "#00ccff",
                   "done": "#44cc44", "failed": "#ff5555", "retrying": "#ffaa00"},
    },
    "flatly": {
        "btn": "☀ 浅色",
        "bg": "#ffffff", "fg": "#212529", "ph": "#95a5a6",
        "zebra_odd": "#eef2f5", "zebra_even": "#ffffff",
        "q_tags": {"waiting": "#6c7a89", "downloading": "#0b76b8",
                   "done": "#1e9e33", "failed": "#d32f2f", "retrying": "#d48806"},
    },
}

# ===== 尝试导入功能库 =====
try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

try:
    from ebooklib import epub
    HAS_EBOOKLIB = True
except ImportError:
    HAS_EBOOKLIB = False

# ===== 配置 =====
HISTORY_FILE = Path.home() / ".transformed_history.json"
LOG_FILE = Path.home() / ".transformed_log.txt"
SETTINGS_FILE = (Path.home() / ".transformed_settings.json").resolve()


class AppSettings:
    """轻量设置持久化（输出目录/下载格式/主题等），损坏时回退默认值。"""
    DEFAULTS = {
        "output_dir": "",
        "dl_type": "mp4",
        "theme": "superhero",
        "update_last_check": 0.0,
    }
    _lock = threading.Lock()

    def __init__(self, path=SETTINGS_FILE):
        self.path = Path(path)
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update({k: raw[k] for k in self.DEFAULTS if k in raw})
        except Exception:
            pass

    def save(self):
        with self._lock:
            try:
                target = _validated_output_file(self.path, Path.home())
                Path(target).write_text(
                    json.dumps(self.data, indent=2, ensure_ascii=False),
                    encoding="utf-8")
            except Exception:
                pass

    def get(self, key):
        return self.data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()


def _validated_output_file(path, base):
    """规范化目标路径并确保其位于 base 目录内，防止路径穿越。"""
    base = Path(base).resolve()
    target = Path(path).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"拒绝写入 {base} 之外的路径: {target}")
    return target

# ===== ffmpeg 管理 =====
import ipaddress
import socket


def _assert_public_http_url(url):
    """仅允许 http/https，且主机必须解析到公网地址。

    阻断环回、私有、链路本地、保留、组播地址，防止请求被导向内网或本机服务。
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不支持的协议: {parsed.scheme}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL 缺少主机名")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"拒绝访问非公网地址: {host} -> {ip}")


class _GuardedRedirectHandler(_urlreq.HTTPRedirectHandler):
    """重定向目标同样经过公网校验，防止 30x 跳转到内网。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_GUARDED_OPENER = None
_GUARDED_OPENER_LOCK = threading.Lock()


def guarded_urlopen(req, timeout):
    """带 SSRF 防护的 urlopen：校验协议/主机/解析后的 IP，并拦截危险重定向。"""
    global _GUARDED_OPENER
    url = req.full_url if isinstance(req, _urlreq.Request) else req
    _assert_public_http_url(url)
    with _GUARDED_OPENER_LOCK:
        if _GUARDED_OPENER is None:
            _GUARDED_OPENER = _urlreq.build_opener(_GuardedRedirectHandler())
    return _GUARDED_OPENER.open(req, timeout=timeout)


def safe_extractall(zf, dest):
    """防 Zip Slip：拒绝绝对路径或包含 .. 的压缩条目再解压。"""
    dest = Path(dest).resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            raise ValueError(f"压缩包内含非法路径，已拒绝解压: {member.filename}")
    zf.extractall(dest)


def get_ffmpeg_dir():
    """ffmpeg 安装目录：优先 exe 同目录，其次用户目录"""
    # exe 打包后 __file__ 是临时解压目录，用 sys.executable 的目录
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    return exe_dir / "ffmpeg"

def get_ffmpeg_path():
    """查找可用的 ffmpeg"""
    # 1. 系统 PATH
    found = shutil.which("ffmpeg")
    if found:
        return found
    # 2. 随 exe 分发
    candidates = [
        get_ffmpeg_dir() / "bin" / "ffmpeg.exe",
        get_ffmpeg_dir() / "bin" / "ffmpeg",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None

def download_ffmpeg(progress_cb=None):
    """自动下载 ffmpeg for Windows"""
    if os.name != "nt":
        return False, "ffmpeg 自动下载仅支持 Windows，请手动安装"

    url = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/"
           "latest/ffmpeg-master-latest-win64-gpl-shared.zip")

    dest = get_ffmpeg_dir()
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = _validated_output_file(dest / "ffmpeg.zip", dest)
    extract_dir = dest / "_extract"

    try:
        progress_cb and progress_cb("正在下载 ffmpeg (约30MB)...")
        # 带超时+进度+公网校验的流式下载，替代无超时、易永久卡死的 urlretrieve
        req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        buf = bytearray()
        with guarded_urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                if total:
                    progress_cb and progress_cb(
                        f"正在下载 ffmpeg... {len(buf) / 1048576:.1f}/{total / 1048576:.1f} MB")
        zip_path = _validated_output_file(dest / "ffmpeg.zip", dest)
        Path(zip_path).write_bytes(bytes(buf))

        progress_cb and progress_cb("正在解压...")
        import zipfile
        with zipfile.ZipFile(zip_path) as z:
            # 解压到临时目录（防 Zip Slip），再移动 bin/ 内容
            extract_dir.mkdir(exist_ok=True)
            safe_extractall(z, extract_dir)

        # 找到 bin 目录（解压出来可能是 ffmpeg-master-latest-win64-gpl-shared/）
        bin_dir = None
        for d in extract_dir.iterdir():
            b = d / "bin"
            if b.exists():
                bin_dir = b
                break

        if not bin_dir:
            return False, "ffmpeg 压缩包结构异常，未找到 bin 目录"

        # 移动 ffmpeg.exe 到我们的 ffmpeg/bin/
        target = dest / "bin"
        target.mkdir(exist_ok=True)
        for f in bin_dir.iterdir():
            shutil.copy2(f, target / f.name)

        if not get_ffmpeg_path():
            return False, "ffmpeg 解压完成但未找到可执行文件"

        return True, str(get_ffmpeg_path())
    except Exception as e:
        return False, f"ffmpeg 下载失败: {e}"
    finally:
        # 无论成败都清理临时文件（半截 zip / 解压目录）
        shutil.rmtree(extract_dir, ignore_errors=True)
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass

# ===== 工具类 =====
import urllib.request as _urlreq
import urllib.parse

_FOREIGN_CACHE = {"ts": 0.0, "ok": False, "reason": ""}
_FOREIGN_CACHE_TTL = 600  # 检测结果缓存 10 分钟，避免每个外网任务都等 5 秒探测


def check_foreign_access():
    """检测当前网络能否访问外网(YouTube等)。返回 (bool, 信息)
    - 能访问外网: (True, 描述)
    - 不能(需代理): (False, 原因描述)
    """
    import time
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

# 日志线程锁：防止多线程并发写/裁剪造成竞态
_LOG_LOCK = threading.Lock()
_LOG_MAX = 500   # 日志行数上限

class Logger:
    @staticmethod
    def log(msg):
        ts = datetime.now().strftime("%m-%d %H:%M:%S")
        entry = f"[{ts}] {msg}"
        try:
            with _LOG_LOCK:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
                Logger._trim()
        except:
            pass
        return entry

    @staticmethod
    def _trim():
        """日志超 _LOG_MAX 行时裁剪到 _LOG_MAX-100 行，避免无限增长。
        加锁保护，避免多线程并发裁剪互相覆盖。"""
        try:
            log_file = _validated_output_file(LOG_FILE, Path.home())
            lines = Path(log_file).read_text(encoding="utf-8").splitlines(keepends=True)
            if len(lines) > _LOG_MAX:
                Path(log_file).write_text(
                    "".join(lines[-(_LOG_MAX - 100):]), encoding="utf-8")
        except:
            pass
    
    @staticmethod
    def read():
        if LOG_FILE.exists():
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    return f.read().splitlines()
            except:
                return []
        return []

class History:
    # 工作线程(add)与 UI 线程(删除/清空)都会写入，用 RLock 防止并发写坏 JSON。
    # 所有写入统一经由 add/delete/clear 持锁后调用 save()（RLock 可重入）。
    _lock = threading.RLock()

    def __init__(self):
        self.items = []
        self.load()
    
    def load(self):
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.items = json.load(f)
            except:
                self.items = []
    
    def save(self):
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        target = _validated_output_file(HISTORY_FILE, Path.home())
        Path(target).write_text(
            json.dumps(self.items[-500:], indent=2, ensure_ascii=False),
            encoding="utf-8")
    
    def add(self, name, typ, ok, out=""):
        with self._lock:
            self.items.append({
                "time": datetime.now().strftime("%m-%d %H:%M"),
                "name": name, "type": typ,
                "ok": ok, "out": out
            })
            self.save()

    def delete(self, indexes):
        """按原始索引批量删除记录（倒序删除避免索引位移），返回实际删除数"""
        removed = 0
        with self._lock:
            for idx in sorted(indexes, reverse=True):
                if 0 <= idx < len(self.items):
                    del self.items[idx]
                    removed += 1
            self.save()
        return removed

    def clear(self):
        with self._lock:
            self.items = []
            self.save()


# ===== 主应用 =====
def get_asset(name):
    """获取资源文件路径（兼容 PyInstaller 打包后的临时解压目录）"""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    p = base / "assets" / name
    return str(p) if p.exists() else None


class App(ttk.Window):
    def __init__(self):
        self.settings = AppSettings()
        theme = self.settings.get("theme")
        self._theme = theme if theme in THEMES else "superhero"
        super().__init__(title=f"transformed 桌面版 {APP_VERSION}",
                         themename=self._theme)

        self.geometry("1280x800")
        self.minsize(1050, 650)

        self.history = History()
        self.task_running = False
        self.convert_cards = {}
        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        self.output_dir = str(exe_dir / "transformed_output")
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        # 上次设置的输出目录仍然存在时优先使用
        saved_dir = self.settings.get("output_dir")
        if saved_dir and Path(saved_dir).is_dir():
            self.output_dir = saved_dir

        # ===== 下载队列 =====
        self.dl_queue = []           # [{url, is_mp3, status, name, error}, ...]
        self.dl_queue_lock = threading.Lock()
        self.dl_queue_worker_running = False
        self._ui_thread_id = threading.get_ident()
        self._ui_closing = False
        self.dl_current_item = None  # 当前正在下载的队列项引用
        self._url_placeholder_active = True
        self._dl_pct = 0.0
        self._progress_events = UiProgressEventQueue()

        # 两侧看板娘立绘（深海女仆工坊 · 鲸鱼娘 CC BY-NC-SA 4.0）
        # 目标高度 = 窗口高(800) - header(55) - status(35) - padding(30) ≈ 680
        self._whale_h = 680
        self.img_left = self._load_whale("whale_left.webp", 235, self._whale_h)
        self.img_right = self._load_whale("whale_right.webp", 235, self._whale_h)
        self._set_window_icon()

        self._build_ui()
        self._apply_theme_colors()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._ui_drain_after_id = self.after(50, self._drain_progress_events)
        self._check_deps()
        # 延迟几秒再静默检查更新，不影响启动速度
        self.after(2500, self._check_update_async)

    def _set_window_icon(self):
        """用看板娘立绘生成窗口图标"""
        try:
            p = get_asset("whale_left.webp")
            if p:
                img = Image.open(p).convert("RGBA")
                img.thumbnail((64, 64), Image.LANCZOS)
                self._icon_img = ImageTk.PhotoImage(img)
                self.iconphoto(True, self._icon_img)
        except Exception as e:
            Logger.log(f"设置窗口图标失败: {e}")
    
    def _load_whale(self, fname, max_w, target_h=640):
        """加载并缩放鲸鱼娘立绘（高度填满 target_h，宽度不超过 max_w）"""
        try:
            p = get_asset(fname)
            if not p:
                return None
            img = Image.open(p)
            w, h = img.size
            # 按高度缩放，宽度不超过 max_w
            scale_h = target_h / h
            scale_w = max_w / w
            scale = min(scale_h, scale_w)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception as e:
            Logger.log(f"加载看板娘图片失败: {fname} {e}")
            return None
    
    def _check_deps(self):
        # 关键库缺失才提示（ffmpeg 可选，但提供自动下载）
        missing = []
        if not HAS_YTDLP:
            missing.append("yt-dlp")
        if not HAS_EBOOKLIB:
            missing.append("ebooklib")
        
        if missing:
            self.show_toast("缺少依赖", "以下功能库未找到:\n" +
                          "\n".join(f"• {m}" for m in missing) +
                          "\n\n请重新打包 exe 或 pip install",
                          "warning")
        
        # ffmpeg 缺失 → 询问是否自动下载
        if not get_ffmpeg_path():
            if messagebox.askyesno(
                "ffmpeg 未找到",
                "MP4转MP3和部分视频下载需要 ffmpeg。\n\n"
                "是否现在自动下载并安装？\n"
                "(约30MB，下载后即可使用)"):
                self._setup_ffmpeg()
            else:
                self.status.config(
                    text="提示: 未安装 ffmpeg，MP4转MP3功能不可用（其他功能正常）")
    
    def _setup_ffmpeg(self):
        """启动 ffmpeg 自动下载"""
        if self.task_running:
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        self.task_running = True
        self.status.config(text="正在下载并安装 ffmpeg...")
        threading.Thread(target=self._download_ffmpeg_thread, daemon=True).start()
    
    def _download_ffmpeg_thread(self):
        def set_status(msg):
            self._run_on_ui("ffmpeg-status", lambda m=msg: self.status.config(text=m))
        try:
            def cb(msg):
                set_status(msg)
            
            ok, result = download_ffmpeg(cb)
            if ok:
                set_status("✅ ffmpeg 安装完成，MP4转MP3现可用")
                self.show_toast("成功", "ffmpeg 已自动安装完成！", "success", _from_thread=True)
            else:
                set_status("ffmpeg 安装失败")
                self.show_toast("失败", result, "error", _from_thread=True)
        except Exception as e:
            set_status("ffmpeg 安装失败")
            self.show_toast("失败", str(e), "error", _from_thread=True)
        finally:
            self.task_running = False
    
    def show_toast(self, title, msg, level="info", _from_thread=False):
        """可靠的消息弹窗；后台线程通过有界 UI mailbox 调度。"""
        if _from_thread:
            self._run_on_ui("toast", lambda: self._show_toast_ui(title, msg, level))
            return
        self._show_toast_ui(title, msg, level)
    
    def _show_toast_ui(self, title, msg, level="info"):
        # 用 tkinter 原生 messagebox，中文渲染绝对可靠，避免"空弹窗"
        msg = str(msg)
        if level == "error":
            messagebox.showerror(title, msg, parent=self)
        elif level == "warning":
            messagebox.showwarning(title, msg, parent=self)
        else:
            messagebox.showinfo(title, msg, parent=self)
    
    def _build_ui(self):
        # ===== 顶部标题栏 =====
        header = ttk.Frame(self, padding=(18, 12, 14, 8))
        header.pack(fill=X)

        ttk.Label(header, text="🐳 transformed", font=(UI_FONT, 20, "bold"),
                 bootstyle="primary").pack(side=LEFT)
        ttk.Label(header, text=f"格式转换 · 视频下载 · 深海女仆工坊   {APP_VERSION}",
                 font=(UI_FONT, 10), bootstyle="secondary").pack(side=LEFT, padx=10, pady=(8, 0))

        # 设置按钮
        ttk.Button(header, text="⚙ 输出目录",
                  command=self._set_output, bootstyle="outline").pack(side=RIGHT, padx=2)
        ttk.Button(header, text="⟳", width=3,
                  command=lambda: self.history_tree_refresh(),
                  bootstyle="outline").pack(side=RIGHT, padx=2)
        self.theme_btn = ttk.Button(header, text=THEMES["flatly" if self._theme == "superhero" else "superhero"]["btn"],
                                    command=self._toggle_theme,
                                    bootstyle="outline")
        self.theme_btn.pack(side=RIGHT, padx=2)

        ttk.Separator(self).pack(fill=X, padx=14)

        # ===== 主区域（两侧看板娘 + 中间内容） =====
        mid = ttk.Frame(self)
        mid.pack(fill=BOTH, expand=True, padx=6, pady=2)
        
        # 左侧鲸鱼娘立绘（底部对齐，显示全身）
        if self.img_left:
            ttk.Label(mid, image=self.img_left).pack(side=LEFT, fill=Y, anchor="s")
        
        # 右侧鲸鱼娘立绘（底部对齐，显示全身）
        if self.img_right:
            ttk.Label(mid, image=self.img_right).pack(side=RIGHT, fill=Y, anchor="s")
        
        # 中间内容区
        main = ttk.Panedwindow(mid, orient=HORIZONTAL)
        main.pack(fill=BOTH, expand=True, padx=8, pady=4)
        
        # 左侧功能面板
        left = ttk.Frame(main)
        main.add(left, weight=3)
        
        # 右侧历史面板
        right = ttk.Frame(main)
        main.add(right, weight=2)
        
        self._build_left(left)
        self._build_right(right)
        
        # ===== 底部状态栏 =====
        status = ttk.Frame(self, padding=(15, 4))
        status.pack(fill=X, side=BOTTOM)
        ttk.Separator(self).pack(fill=X, side=BOTTOM)
        self.status = ttk.Label(status, text="🐳 就绪", bootstyle="secondary")
        self.status.pack(side=LEFT)
        ttk.Label(status, text=f"transformed Desktop {APP_VERSION} · 深海女仆工坊",
                 bootstyle="secondary").pack(side=RIGHT)
    
    def _build_left(self, parent):
        """左侧功能面板"""
        nb = ttk.Notebook(parent)
        nb.pack(fill=BOTH, expand=True)
        
        # --- Tab 1: 格式转换 ---
        tab1 = ttk.Frame(nb, padding=15)
        nb.add(tab1, text="📁 格式转换")
        
        # EPUB
        self._make_converter_card(tab1, "EPUB → TXT", "epub",
            "选择 EPUB 电子书，批量转换为纯文本",
            lambda: self._pick("epub", [("EPUB", "*.epub")]),
            lambda: self._convert("epub"))
        
        # MP4
        self._make_converter_card(tab1, "MP4 → MP3", "mp4",
            "提取视频中的音频轨道，保存为 MP3（支持 mp4/mkv/avi/mov/webm/flv/ts）",
            lambda: self._pick("mp4", [("视频文件", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.ts")]),
            lambda: self._convert("mp4"))
        
        # WebP
        self._make_converter_card(tab1, "WebP → JPG", "webp",
            "将 WebP 图片批量转换为 JPEG 格式（也支持 png/jpg/gif/bmp/tiff 输入）",
            lambda: self._pick("webp", [("图片", "*.webp *.png *.jpg *.jpeg *.gif *.bmp *.tiff")]),
            lambda: self._convert("webp"))
        
        # --- Tab 2: 网络下载 ---
        tab2 = ttk.Frame(nb, padding=15)
        nb.add(tab2, text="🌐 网络下载")

        # ---- 歌曲搜索下载 ----
        song_box = ttk.Labelframe(tab2, text="🎵 歌曲搜索下载（MP3）", padding=12)
        song_box.pack(fill=X, pady=(0, 10))

        ttk.Label(song_box, text="输入歌手 / 歌名，自动搜索下载 MP3",
                 font=(UI_FONT, 10), bootstyle="secondary").pack(anchor=W)

        song_frame = ttk.Frame(song_box)
        song_frame.pack(fill=X, pady=5)

        self.song_var = tk.StringVar()
        song_entry = ttk.Entry(song_frame, textvariable=self.song_var,
                             font=(UI_FONT, 11))
        song_entry.pack(fill=X, side=LEFT, expand=True)
        song_entry.bind("<Return>", lambda e: self._start_song_search())

        ttk.Button(song_frame, text="🔍 搜索下载",
                  bootstyle="warning", command=self._start_song_search).pack(side=RIGHT, padx=5)

        ttk.Label(song_box, text="搜索来源: B站优先（国内直连），暂无则手机外站兜底。",
                 font=(UI_FONT, 9), bootstyle="secondary").pack(anchor=W)

        # ---- 视频链接批量下载 ----
        url_box = ttk.Labelframe(tab2, text="🎬 视频链接下载（支持批量）", padding=12)
        url_box.pack(fill=X, pady=(0, 8))

        ttk.Label(url_box, text="每行一个链接，支持 B站/BV号/AV号/b23短链/YouTube/X/直链",
                 font=(UI_FONT, 9), bootstyle="secondary").pack(anchor=W, pady=(0, 4))

        # 多行文本输入框
        self.url_text = tk.Text(url_box, height=4, font=(UI_FONT, 10),
                                bg="#1a1a2e", fg="#e0e0e0", insertbackground="#e0e0e0",
                                wrap=tk.WORD, relief=tk.FLAT, padx=8, pady=6)
        self.url_text.pack(fill=X, pady=(0, 6))
        # 占位符
        self._url_placeholder = "粘贴链接到此处，每行一个...\n例如:\nhttps://www.bilibili.com/video/BV...\nyoutube.com/watch?v=..."
        self._set_url_placeholder(True)
        self.url_text.bind("<FocusIn>", self._on_url_text_focus_in)
        self.url_text.bind("<FocusOut>", self._on_url_text_focus_out)

        # 格式选择 + 按钮行
        btn_row = ttk.Frame(url_box)
        btn_row.pack(fill=X, pady=(0, 2))

        saved_type = self.settings.get("dl_type")
        self.dl_type = tk.StringVar(value=saved_type if saved_type in ("mp4", "mp3") else "mp4")
        # 任何方式改变格式都持久化（点击/键盘/程序赋值）
        self.dl_type.trace_add("write", lambda *_: self.settings.set("dl_type", self.dl_type.get()))
        ttk.Radiobutton(btn_row, text="🎬 MP4", variable=self.dl_type,
                       value="mp4", bootstyle="success").pack(side=LEFT, padx=2)
        ttk.Radiobutton(btn_row, text="🎵 MP3", variable=self.dl_type,
                       value="mp3", bootstyle="warning").pack(side=LEFT, padx=2)
        ttk.Button(btn_row, text="📋 粘贴", bootstyle="outline",
                  command=self._paste_from_clipboard).pack(side=LEFT, padx=(0, 8))

        ttk.Button(btn_row, text="➕ 添加到队列", bootstyle="info",
                  command=self._start_dl).pack(side=RIGHT, padx=3)
        ttk.Button(btn_row, text="▶ 开始下载", bootstyle="success",
                  command=self._start_queue).pack(side=RIGHT, padx=3)
        ttk.Button(btn_row, text="📂 打开文件夹", bootstyle="outline",
                  command=self._open_output_folder).pack(side=RIGHT, padx=3)

        # ---- 队列区 ----
        queue_box = ttk.Labelframe(tab2, text="📋 下载队列", padding=8)
        queue_box.pack(fill=BOTH, expand=True, pady=(0, 8))

        # Treeview
        q_cols = ("idx", "status", "name", "progress")
        self.queue_tree = ttk.Treeview(queue_box, columns=q_cols, show="headings",
                                       height=8, bootstyle="info", selectmode="extended")
        self.queue_tree.heading("idx", text="#")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.heading("name", text="文件名 / URL")
        self.queue_tree.heading("progress", text="进度")
        self.queue_tree.column("idx", width=40, anchor=CENTER, stretch=False)
        self.queue_tree.column("status", width=90, anchor=CENTER, stretch=False)
        self.queue_tree.column("name", width=320)
        self.queue_tree.column("progress", width=90, anchor=CENTER, stretch=False)
        self.queue_tree.tag_configure("waiting", foreground="#8899aa")
        self.queue_tree.tag_configure("downloading", foreground="#00ccff")
        self.queue_tree.tag_configure("done", foreground="#44cc44")
        self.queue_tree.tag_configure("failed", foreground="#ff5555")
        self.queue_tree.tag_configure("retrying", foreground="#ffaa00")
        q_scroll = ttk.Scrollbar(queue_box, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=q_scroll.set)
        self.queue_tree.pack(side=LEFT, fill=BOTH, expand=True)
        q_scroll.pack(side=RIGHT, fill=Y)
        # 键盘 Delete 删除；双击失败行看错误详情，双击完成行直接打开文件
        self.queue_tree.bind("<Delete>", lambda e: self._queue_delete_selected())
        self.queue_tree.bind("<Double-1>", self._on_queue_double_click)
        # 右键菜单
        self._queue_menu = tk.Menu(self, tearoff=0)
        self._queue_menu.add_command(label="▶ 开始下载", command=self._start_queue)
        self._queue_menu.add_separator()
        self._queue_menu.add_command(label="↻ 重试选中", command=self._queue_retry_selected)
        self._queue_menu.add_command(label="⬆ 上移", command=lambda: self._queue_move(-1))
        self._queue_menu.add_command(label="⬇ 下移", command=lambda: self._queue_move(1))
        self._queue_menu.add_separator()
        self._queue_menu.add_command(label="🗑 删除选中", command=self._queue_delete_selected)
        self.queue_tree.bind("<Button-3>", self._show_queue_menu)  # 右键

        # 队列操作按钮行
        q_btns = ttk.Frame(queue_box)
        q_btns.pack(fill=X, pady=(6, 0))
        ttk.Button(q_btns, text="⬆ 上移", bootstyle="outline",
                  command=lambda: self._queue_move(-1)).pack(side=LEFT, padx=2)
        ttk.Button(q_btns, text="⬇ 下移", bootstyle="outline",
                  command=lambda: self._queue_move(1)).pack(side=LEFT, padx=2)
        ttk.Button(q_btns, text="↻ 重试选中", bootstyle="warning-outline",
                  command=self._queue_retry_selected).pack(side=LEFT, padx=2)
        ttk.Button(q_btns, text="🗑 删除选中", bootstyle="danger-outline",
                  command=self._queue_delete_selected).pack(side=LEFT, padx=2)
        ttk.Button(q_btns, text="清空队列", bootstyle="danger",
                  command=self._queue_clear).pack(side=RIGHT, padx=2)

        # ---- 进度区 ----
        prog_box = ttk.Labelframe(tab2, text="📊 下载进度", padding=8)
        prog_box.pack(fill=X)

        self.dl_total_label = ttk.Label(prog_box, text="总进度: 0/0",
                                        font=(UI_FONT, 9))
        self.dl_total_label.pack(anchor=W)
        self.dl_total_prog = ttk.Progressbar(prog_box, mode="determinate",
                                             bootstyle="success-striped")
        self.dl_total_prog.pack(fill=X, pady=2)

        ttk.Label(prog_box, text="当前:", font=(UI_FONT, 9)).pack(anchor=W, pady=(4, 0))
        self.dl_prog = ttk.Progressbar(prog_box, mode="determinate",
                                       bootstyle="info-striped")
        self.dl_prog.pack(fill=X, pady=2)
        self.dl_stat = ttk.Label(prog_box, text="", font=(UI_FONT, 9))
        self.dl_stat.pack(anchor=W)

        # 支持列表
        info = ttk.Frame(tab2, padding=(6, 6, 6, 0))
        info.pack(fill=X, pady=(4, 0))
        ttk.Label(info, text="✅ 支持的平台",
                 font=(UI_FONT, 11, "bold")).pack(anchor=W)
        for line in ["• Bilibili — BV/AV号或完整链接",
                     "• YouTube — youtube.com / youtu.be",
                     "• Twitter/X — twitter.com / x.com",
                     "• 通用直链 — 任意媒体文件直链"]:
            ttk.Label(info, text=line).pack(anchor=W)
        
        # --- Tab 3: 日志 ---
        tab3 = ttk.Frame(nb, padding=10)
        nb.add(tab3, text="📋 运行日志")
        
        log_btn = ttk.Frame(tab3)
        log_btn.pack(fill=X)
        ttk.Button(log_btn, text="刷新", bootstyle="info-outline",
                  command=self._log_refresh).pack(side=LEFT, padx=2)
        ttk.Button(log_btn, text="清空", bootstyle="danger-outline",
                  command=self._log_clear).pack(side=LEFT, padx=2)
        
        self.log_text = scrolledtext.ScrolledText(tab3, height=15,
            font=("Consolas", 9), bg="#1a1a2e", fg="#e0e0e0")
        self.log_text.pack(fill=BOTH, expand=True, pady=5)
    
    def _make_converter_card(self, parent, title, key, desc, pick_fn, conv_fn):
        """创建转换卡片（带标题的分组框）"""
        icons = {"epub": "📖", "mp4": "🎬", "webp": "🖼️"}

        card = ttk.Labelframe(parent, text=f" {icons.get(key, '📁')} {title} ",
                              padding=(12, 8), bootstyle="primary")
        card.pack(fill=X, pady=7)

        ttk.Label(card, text=desc, font=(UI_FONT, 9),
                 bootstyle="secondary").pack(anchor=W)

        self.convert_cards[key] = {
            "files": [],
            "label": ttk.Label(card, text="未选择文件", bootstyle="secondary"),
            "progress": ttk.Progressbar(card, mode="determinate",
                                        bootstyle="success-striped"),
            "status": ttk.Label(card, text="", font=(UI_FONT, 9)),
            "pick_fn": pick_fn,
            "conv_fn": conv_fn,
        }

        btn_frame = ttk.Frame(card)
        btn_frame.pack(fill=X, pady=6)

        ttk.Button(btn_frame, text="📂 选择文件",
                  command=pick_fn, bootstyle="outline").pack(side=LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="▶ 开始转换",
                  command=conv_fn, bootstyle="success").pack(side=LEFT)
        self.convert_cards[key]["label"].pack(side=RIGHT, padx=2)

        self.convert_cards[key]["progress"].pack(fill=X, pady=(2, 3))
        self.convert_cards[key]["status"].pack(anchor=W)
    
    # ---- 右侧历史 ----
    def _build_right(self, parent):
        ttk.Label(parent, text="📜 转换记录", font=(UI_FONT, 14, "bold"),
                 bootstyle="inverse-secondary").pack(fill=X, pady=(2, 5))
        
        # 筛选
        filt = ttk.Frame(parent)
        filt.pack(fill=X, pady=(0, 4))
        self.filter_var = tk.StringVar(value="全部")
        for tag in ["全部", "EPUB", "MP4", "WebP", "下载"]:
            ttk.Radiobutton(filt, text=tag, variable=self.filter_var,
                          value=tag, command=self.history_tree_refresh,
                          bootstyle="secondary").pack(side=LEFT, padx=2)
        
        # 树状表格（支持 Ctrl/Shift 多选）
        cols = ("time", "file", "type", "status")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings",
                                 height=18, bootstyle="info",
                                 selectmode="extended")
        self.tree.heading("time", text="时间")
        self.tree.heading("file", text="文件")
        self.tree.heading("type", text="类型")
        self.tree.heading("status", text="状态")
        self.tree.column("time", width=90, anchor=CENTER)
        self.tree.column("file", width=160)
        self.tree.column("type", width=70, anchor=CENTER)
        self.tree.column("status", width=40, anchor=CENTER)
        
        # 斑马纹：隔行背景色
        self.tree.tag_configure("odd", background="#223140")
        self.tree.tag_configure("even", background="#2b3e50")
        
        scroll = ttk.Scrollbar(parent, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)
        self.tree.bind("<Control-a>", self._history_select_all_visible)
        self.tree.bind("<Control-A>", self._history_select_all_visible)
        self.tree.bind("<Delete>", lambda event: self._history_delete_selected())
        self.tree.bind("<Double-1>", self._on_history_double_click)
        
        # 底部按钮
        btm = ttk.Frame(parent)
        btm.pack(fill=X, pady=5)
        ttk.Button(btm, text="全选当前", bootstyle="secondary-outline",
                   command=self._history_select_all_visible).pack(side=LEFT, padx=2)
        ttk.Button(btm, text="🗑 删除选中", bootstyle="warning-outline",
                  command=self._history_delete_selected).pack(side=RIGHT, padx=2)
        ttk.Button(btm, text="清空全部", bootstyle="danger-outline",
                  command=self._history_clear).pack(side=RIGHT, padx=2)
        
        self.history_tree_refresh()
    
    # ---- 功能方法 ----
    def _set_output(self):
        d = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir)
        if d:
            self.output_dir = d
            Path(d).mkdir(parents=True, exist_ok=True)
            self.settings.set("output_dir", d)
            self.status.config(text=f"输出目录: {d}（已记住）")

    # ---- 主题 ----
    def _theme_colors(self):
        return THEMES.get(self._theme, THEMES["superhero"])

    def _apply_theme_colors(self):
        """主题切换后同步自绘控件（文本框/斑马纹/队列状态色/按钮文字）的颜色"""
        c = self._theme_colors()
        for widget in (self.url_text, self.log_text):
            widget.config(bg=c["bg"], fg=c["fg"], insertbackground=c["fg"])
        self.tree.tag_configure("odd", background=c["zebra_odd"])
        self.tree.tag_configure("even", background=c["zebra_even"])
        for tag, color in c["q_tags"].items():
            self.queue_tree.tag_configure(tag, foreground=color)
        if getattr(self, "_url_placeholder_active", False):
            self.url_text.config(fg=c["ph"])
        other = "flatly" if self._theme == "superhero" else "superhero"
        self.theme_btn.config(text=THEMES[other]["btn"])

    def _toggle_theme(self):
        new = "flatly" if self._theme == "superhero" else "superhero"
        try:
            self.style.theme_use(new)
        except Exception as e:
            Logger.log(f"切换主题失败: {e}")
            return
        self._theme = new
        self.settings.set("theme", new)
        self._apply_theme_colors()
        self.status.config(text=f"主题已切换: {new}")

    # ---- 剪贴板 ----
    def _paste_from_clipboard(self):
        """把剪贴板内容追加到链接输入框"""
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if not text:
            self.show_toast("提示", "剪贴板是空的", "warning")
            return
        if self._url_placeholder_active:
            self._on_url_text_focus_in()
        self.url_text.insert(tk.END, text + "\n")
        self.url_text.see(tk.END)
        self.status.config(text="已从剪贴板粘贴链接")

    # ---- 更新检查 ----
    def _check_update_async(self):
        """每 24 小时静默检查一次 GitHub 最新 Release，有新版时在状态栏提示"""
        try:
            last = float(self.settings.get("update_last_check") or 0)
        except (TypeError, ValueError):
            last = 0.0
        if time.time() - last < 24 * 3600:
            return

        def run():
            try:
                req = _urlreq.Request(
                    "https://api.github.com/repos/BYDXDM/transformed-desktop/releases/latest",
                    headers={"User-Agent": f"transformed/{APP_VERSION}"})
                with guarded_urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8"))
                tag = str(data.get("tag_name") or "")
                if is_newer_version(tag, APP_VERSION):
                    self._run_on_ui("update-hint", lambda t=tag: self.status.config(
                        text=f"🆕 发现新版本 {t}，可到 GitHub Releases 页面下载"))
            except Exception:
                pass
            finally:
                self.settings.set("update_last_check", time.time())

        threading.Thread(target=run, daemon=True).start()
    
    def _pick(self, key, filetypes):
        ct = self.convert_cards[key]
        files = filedialog.askopenfilenames(title="选择文件", filetypes=filetypes)
        if files:
            ct["files"] = list(files)
            ct["label"].config(text=f"已选 {len(files)} 个文件")
            self.status.config(text=f"已选择 {len(files)} 个文件")
    
    def _convert(self, key):
        if self.task_running:
            self.show_toast("提示", "正在执行任务，请等待", "warning")
            return
        ct = self.convert_cards[key]
        if not ct["files"]:
            self.show_toast("提示", "请先选择文件", "warning")
            return
        self.task_running = True
        threading.Thread(target=self._do_convert, args=(key,), daemon=True).start()
    
    def _should_skip(self, conv_type, file):
        """判断文件是否应跳过：已是目标格式 或 与本类无关"""
        ext = Path(file).suffix.lower()
        # 每种转换接受的源格式
        source_exts = {
            "epub": [".epub"],
            "mp4": [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts"],
            "webp": [".webp", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"],
        }
        # 已是目标格式 → 跳过
        target_exts = {"epub": [".txt"], "mp4": [".mp3"], "webp": [".jpg", ".jpeg"]}
        if ext in target_exts.get(conv_type, []):
            return "target"
        # 与本类无关的文件（源格式都不匹配）→ 跳过
        if ext not in source_exts.get(conv_type, []):
            return "unrelated"
        return None

    def _do_convert(self, key):
        ct = self.convert_cards[key]
        files = ct["files"]
        total = len(files)
        
        conv_map = {
            "epub": ("EPUB→TXT", self._conv_epub),
            "mp4": ("MP4→MP3", self._conv_mp4),
            "webp": ("WebP→JPG", self._conv_webp),
        }
        
        typ_name, conv_fn = conv_map[key]
        
        skipped_count = 0
        try:
            for i, f in enumerate(files):
                # 跳过：已是目标格式 或 与本类无关的文件
                skip_reason = self._should_skip(key, f)
                if skip_reason:
                    skipped_count += 1
                    reason_text = "已是目标格式" if skip_reason == "target" else "非本类型文件"
                    Logger.log(f"⏭️ 跳过({reason_text}): {Path(f).name}")
                    self._run_on_ui("conversion-status", lambda n=Path(f).name, i=i, rt=reason_text: (
                        ct["status"].config(text=f"[{i+1}/{total}] {n}: {rt}，跳过")))
                    self.history.add(Path(f).name, typ_name, True, "skipped:" + skip_reason)
                    continue
                
                def mk_cb(i, f):
                    def cb(pct, msg):
                        overall = (i / total) + (pct / total)
                        # 转换进度只写自己的卡片，不再串扰底部下载进度区
                        # （下载与转换可能并行进行，各自更新各自的进度）
                        self._schedule_progress_ui(
                            "conversion",
                            lambda p=overall, n=i, fn=Path(f).name, m=msg: (
                                ct["progress"].config(value=min(p * 100, 100)),
                                ct["status"].config(text=f"[{n+1}/{total}] {fn}: {m}"),
                            ),
                        )
                    return cb
                
                cb = mk_cb(i, f)
                cb(0, "开始...")
                try:
                    ok, result = conv_fn(f, self.output_dir, cb)
                except Exception as e:
                    ok, result = False, str(e)
                    Logger.log(f"❌ 转换异常: {Path(f).name}: {e}")
                self.history.add(Path(f).name, typ_name, ok, result if ok else "")
                Logger.log(f"{'✅' if ok else '❌'} {typ_name}: {Path(f).name}")
                self._run_on_ui("conversion-status", lambda u=ok, n=Path(f).name: self.status.config(
                    text=f"{'完成' if u else '失败'}: {n}"))
        finally:
            # 确保无论成功/异常都重置状态，防止卡死（UI 操作调度回主线程）
            self.task_running = False
            self._run_on_ui("conversion-finished", lambda k=ct: (
                k["label"].config(text="完成 ✓"),
                k["progress"].config(value=0),
                self.history_tree_refresh(),
                self._log_refresh()))
            skip_note = f"（跳过 {skipped_count} 个已是目标格式的文件）" if skipped_count else ""
            self.show_toast("完成", f"批量 {typ_name} 转换完成{skip_note}!\n保存至: {self.output_dir}", "success", _from_thread=True)
    
    def _conv_epub(self, path, out_dir, cb):
        if not HAS_EBOOKLIB:
            return False, "请安装: pip install ebooklib"
        try:
            cb(0.1, "读取 EPUB...")
            book = epub.read_epub(path)
            name = Path(path).stem
            out = Path(out_dir) / f"{name}.txt"
            texts = []
            items = list(book.get_items_of_type(epub.ITEM_DOCUMENT))
            for i, item in enumerate(items):
                html = item.get_body_content().decode("utf-8", errors="replace")
                text = re.sub(r'<[^>]+>', ' ', html)
                import html as html_mod
                text = html_mod.unescape(text)
                text = re.sub(r'\s+', ' ', text).strip()
                if text: texts.append(text)
                cb(0.1 + (i/len(items))*0.8, f"解析 {i+1}/{len(items)}")
            cb(0.9, "写入文件...")
            out = _validated_output_file(out, out_dir)
            Path(out).write_text("\n\n".join(texts), encoding="utf-8")
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def _media_duration(ffmpeg, path, no_window):
        """用 ffprobe 读取媒体时长（秒），失败返回 None"""
        ffprobe = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if not ffprobe.exists():
            return None
        try:
            proc = subprocess.run(
                [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, shell=False, timeout=30,
                creationflags=no_window)
            return float(proc.stdout.decode("ascii", "replace").strip())
        except Exception:
            return None

    def _conv_mp4(self, path, out_dir, cb):
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            return False, "未找到 ffmpeg，请重新启动程序并选择自动下载"
        # GUI(pythonw) 模式下防止 ffmpeg 弹出黑色控制台窗口
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            cb(0.05, "读取时长...")
            duration = self._media_duration(ffmpeg, path, no_window)
            name = Path(path).stem
            out = _validated_output_file(Path(out_dir) / f"{name}.mp3", out_dir)
            cmd = [ffmpeg, "-nostdin", "-loglevel", "error",
                   "-i", str(path), "-vn",
                   "-acodec", "libmp3lame", "-ab", "192k",
                   "-y", str(out)]
            if duration:
                cmd += ["-progress", "pipe:1"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, shell=False,
                                    creationflags=no_window)
            try:
                for line in proc.stdout:
                    text = line.decode("ascii", "replace").strip()
                    # out_time_ms 单位是微秒；按已转换时长映射到 5%~95%
                    if duration and text.startswith("out_time_ms="):
                        try:
                            ratio = max(0.0, min(float(text.split("=", 1)[1]) / 1e6 / duration, 1.0))
                            cb(0.05 + ratio * 0.9, f"转换中 {ratio * 100:.0f}%")
                        except ValueError:
                            pass
                proc.wait()
            finally:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
            if proc.returncode != 0:
                err = (proc.stderr.read() or b"").decode("utf-8", errors="replace")[-300:]
                return False, f"ffmpeg 转换失败(code={proc.returncode}): {err}"
            if not Path(out).exists() or Path(out).stat().st_size == 0:
                return False, "ffmpeg 未生成输出文件"
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)
    
    def _conv_webp(self, path, out_dir, cb):
        try:
            cb(0.3, "解码...")
            img = Image.open(path)
            name = Path(path).stem
            out = Path(out_dir) / f"{name}.jpg"
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            cb(0.6, "编码...")
            img.save(out, "JPEG", quality=92)
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)
    
    def _prepare_url(self, url):
        """智能处理输入：支持裸 BV/AV 号、b23短链、完整链接、混合文本。"""
        return prepare_url(url)

    def _schedule_progress_ui(self, source, callback):
        """Queue worker progress; callbacks run only in Tk's owning thread."""
        if not self._ui_closing:
            self._progress_events.put(source, callback)

    def _run_on_ui(self, source, callback):
        """Dispatch all worker-originated Tk work through the bounded UI mailbox."""
        if threading.get_ident() == self._ui_thread_id:
            callback()
        else:
            self._schedule_progress_ui(source, callback)

    def _drain_progress_events(self):
        """Apply each source's latest pending update once per 50 ms UI tick."""
        if self._ui_closing:
            return
        for callback in self._progress_events.take_all().values():
            try:
                callback()
            except tk.TclError:
                if self._ui_closing:
                    return
                raise
        try:
            self._ui_drain_after_id = self.after(50, self._drain_progress_events)
        except tk.TclError:
            # 窗口恰好在排空回调中销毁，安静退出即可
            pass

    def _on_close(self):
        """Stop accepting worker UI work before destroying the Tk root."""
        self._ui_closing = True
        if getattr(self, "_ui_drain_after_id", None):
            self.after_cancel(self._ui_drain_after_id)
        self.destroy()

    def _history_select_all_visible(self, event=None):
        """Select every row currently visible after the active history filter."""
        ids = selected_history_ids(self.tree.get_children())
        if ids:
            self.tree.selection_set(ids)
            self.tree.focus(ids[0])
        return "break"

    # ========== 下载队列相关 ==========
    _STATUS_ICONS = {
        "waiting": "○ 等待中", "downloading": "▶ 下载中", "done": "✓ 完成",
        "failed": "✗ 失败", "retrying": "↻ 重试中",
    }

    def _on_url_text_focus_in(self, event=None):
        """文本框获得焦点时，若为占位符则清空"""
        if self._url_placeholder_active:
            self.url_text.delete("1.0", tk.END)
            self.url_text.config(fg=self._theme_colors()["fg"])
            self._url_placeholder_active = False

    def _on_url_text_focus_out(self, event=None):
        """文本框失去焦点时，若为空则恢复占位符"""
        self._set_url_placeholder(True)

    def _set_url_placeholder(self, show):
        if show:
            content = self.url_text.get("1.0", tk.END).strip()
            # 空框或占位符已在显示 → 统一恢复为占位符状态（幂等，
            # 防止窗口切换等重复 FocusOut 把"显示占位符"误标为真实内容）
            if not content or content == self._url_placeholder.strip():
                self.url_text.delete("1.0", tk.END)
                self.url_text.insert("1.0", self._url_placeholder)
                self.url_text.config(fg=self._theme_colors()["ph"])
                self._url_placeholder_active = True
            else:
                self._url_placeholder_active = False
        else:
            self._url_placeholder_active = False

    def _get_urls_from_text(self):
        """从多行文本框提取 URL 列表（自动跳过占位符文字）"""
        # 如果当前显示的是占位符，直接返回空
        if self._url_placeholder_active:
            return []
        self._set_url_placeholder(False)
        raw = self.url_text.get("1.0", tk.END).strip()
        # 双保险：内容就是占位符文字时绝不当成链接
        if not raw or raw == self._url_placeholder.strip():
            return []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        # 去重保序
        seen = set()
        urls = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                urls.append(line)
        return urls

    def _start_dl(self):
        """将文本框中的链接添加到下载队列（自动跳过队列中已有的待处理链接）"""
        urls = self._get_urls_from_text()
        if not urls:
            self.show_toast("提示", "请输入至少一个视频链接", "warning")
            return
        is_mp3 = self.dl_type.get() == "mp3"
        added = skipped = 0
        with self.dl_queue_lock:
            existing = {it["url"] for it in self.dl_queue
                        if it["status"] in ("waiting", "retrying", "downloading")}
            for url in urls:
                if url in existing:
                    skipped += 1
                    continue
                existing.add(url)
                self.dl_queue.append({
                    "url": url, "is_mp3": is_mp3,
                    "status": "waiting", "name": url[:80], "error": "",
                    "progress": "",
                })
                added += 1
        if added == 0:
            self.show_toast("提示", "所选链接已在队列中等待下载，未重复添加", "warning")
            return
        note = f"（跳过 {skipped} 个重复链接）" if skipped else ""
        self._run_on_ui("queue-refresh", self._queue_refresh_tree)
        self.status.config(text=f"已添加 {added} 个链接到队列{note}")
        self.show_toast("已添加", f"已将 {added} 个链接加入下载队列{note}", "info")
        # 清空输入框
        self.url_text.delete("1.0", tk.END)
        self._set_url_placeholder(True)

    def _start_queue(self):
        """手动点击开始下载"""
        with self.dl_queue_lock:
            has_work = any(it["status"] in ("waiting", "retrying") for it in self.dl_queue)
        if not has_work:
            self.show_toast("提示", "队列中没有待下载的任务，请先添加链接", "warning")
            return
        self._start_queue_worker()

    def _start_queue_worker(self):
        """启动队列消费线程（如果尚未运行）"""
        with self.dl_queue_lock:
            if self.dl_queue_worker_running:
                return
            self.dl_queue_worker_running = True
        threading.Thread(target=self._queue_worker, daemon=True).start()

    def _queue_worker(self):
        """后台线程：逐个消费队列中的 waiting 项"""
        while True:
            item = None
            with self.dl_queue_lock:
                for it in self.dl_queue:
                    if it["status"] in ("waiting", "retrying"):
                        item = it
                        break
            if item is None:
                # 队列空，退出 worker
                with self.dl_queue_lock:
                    self.dl_queue_worker_running = False
                self._run_on_ui("queue-status", lambda: self.status.config(text="队列下载完成"))
                return
            with self.dl_queue_lock:
                item["status"] = "downloading"
                self.dl_current_item = item
            self._run_on_ui("queue-refresh", self._queue_refresh_tree)
            self._run_on_ui("queue-status", lambda n=item["name"][:40]:
                       self.status.config(text=f"正在下载: {n}"))
            try:
                self._do_dl_item(item)
            except Exception as e:
                Logger.log(f"❌ 队列项异常: {e}")
                item["status"] = "failed"
                item["error"] = str(e)
            with self.dl_queue_lock:
                self.dl_current_item = None
            self._run_on_ui("queue-refresh", self._queue_refresh_tree)

    def _do_dl_item(self, item):
        """下载单个队列项（在后台线程中执行）"""
        url = item["url"]
        is_mp3 = item["is_mp3"]
        # 单调递增的显示进度(0~1)
        self._dl_pct = 0.0

        if not HAS_YTDLP:
            item["status"] = "failed"
            item["error"] = "请安装 yt-dlp"
            self.show_toast("缺少依赖", "请安装 yt-dlp:\npip install yt-dlp", "error", _from_thread=True)
            return

        def cb(pct, msg):
            pct = max(pct, 0.05)
            self._dl_pct = max(self._dl_pct, pct)
            item["progress"] = f"{self._dl_pct*100:.1f}%"
            self._schedule_progress_ui(
                "download",
                lambda p=self._dl_pct, m=msg: (
                    self.dl_prog.stop(),
                    self.dl_prog.config(value=p * 100, mode="determinate"),
                    self.dl_stat.config(text=m),
                    self._queue_refresh_tree(),
                ),
            )

        ready_url = self._prepare_url(url)
        cb(0.05, "解析链接...")
        Logger.log(f"下载: {url} -> {ready_url}")

        # B. 外网平台(YouTube/X/歌曲搜索)预检测代理
        is_foreign = ("youtu" in ready_url or "ytsearch" in ready_url
                     or "x.com" in ready_url or "twitter" in ready_url)
        if is_foreign:
            cb(0.03, "检测网络环境...")
            can_access, reason = check_foreign_access()
            if not can_access:
                item["status"] = "failed"
                item["error"] = reason
                Logger.log(f"⚠ 外网受限: {reason}")
                self._run_on_ui("download-error", lambda r=reason: (
                    self.dl_prog.config(value=0),
                    self._show_toast_ui("需要代理",
                        f"该视频在 YouTube/X，当前网络无法直接访问。\n\n{r}\n\n"
                        f"建议: 开启代理/VPN 后重试。\nB站等国内视频不受影响，可正常下载。",
                        "warning")))
                return
            Logger.log(f"✅ 外网可访问: {reason}")

        def progress_hook(d):
            """yt-dlp 下载进度回调（工作线程）"""
            status = d.get('status')
            if status == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                speed = d.get('speed') or 0
                eta = d.get('eta') or 0
                if total:
                    mapped = 0.05 + (downloaded / total) * 0.90
                    self._dl_pct = max(self._dl_pct, mapped)
                    pct_show = self._dl_pct * 100
                    item["progress"] = f"{pct_show:.1f}%"
                    self._schedule_progress_ui(
                        "download",
                        lambda p=pct_show, s=speed, e=eta: (
                            self.dl_prog.stop(),
                            self.dl_prog.config(value=min(p, 100), mode="determinate"),
                            self.dl_stat.config(
                                text=f"下载中 {p:.1f}%  {self._fmt_speed(s)}  ETA {e}s" if s else
                                     f"下载中... {p:.1f}%"),
                            self._queue_refresh_tree(),
                        )
                    )
                else:
                    self._schedule_progress_ui(
                        "download",
                        lambda s=speed: (
                            self.dl_prog.config(mode="indeterminate"),
                            self.dl_prog.start(12),
                            self.dl_stat.config(text=f"下载中... {self._fmt_speed(s)}"),
                        )
                    )
            elif status == 'finished':
                self._schedule_progress_ui(
                    "download",
                    lambda: (
                        self.dl_prog.stop(),
                        self.dl_prog.config(mode="determinate", value=95),
                        self.dl_stat.config(text="95% 合并/转码中..."),
                    ),
                )

        try:
            opts = build_download_options(
                ready_url,
                is_mp3=is_mp3,
                output_dir=self.output_dir,
                ffmpeg_path=get_ffmpeg_path(),
                progress_hook=progress_hook,
            )

            cb(0.2, "下载中...")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(ready_url, download=True)
                # ytsearch 等来源返回 playlist 包装；不拆包的话
                # prepare_filename 会按播放列表名拼出错误文件路径
                if isinstance(info, dict) and info.get("_type") in ("playlist", "multi_video"):
                    entries = [e for e in (info.get("entries") or []) if e]
                    if not entries:
                        raise RuntimeError("未找到可下载的视频条目")
                    info = entries[0]
                fn = ydl.prepare_filename(info)

            if is_mp3:
                fn = str(Path(fn).with_suffix(".mp3"))

            cb(1.0, "完成!")
            name = Path(fn).name
            item["name"] = name
            item["status"] = "done"
            item["progress"] = "100%"
            self.history.add(name, "下载", True, fn)
            Logger.log(f"✅ 下载成功: {name}")
            self._run_on_ui("download-status", lambda n=name: self.status.config(text=f"下载成功: {n}"))
        except Exception as e:
            Logger.log(f"❌ 下载失败: {e}")
            err = str(e)
            item["status"] = "failed"
            item["error"] = err[:200]
            hint = ""
            if is_foreign and ("timed out" in err or "timeout" in err or "unable" in err or "403" in err):
                hint = ("\n\n该视频在 YouTube/X，国内网络通常无法直接访问。\n"
                        "建议: 开启代理/VPN后重试，或用浏览器打开该链接。\n"
                        "B站等国内视频可正常下载。")
            elif "timed out" in err or "timeout" in err:
                hint = "\n\n提示: 网络超时，请检查网络或稍后重试"
            elif "not a valid URL" in err or "404" in err:
                hint = "\n\n提示: 链接无效或已失效，请检查"
            elif "ffmpeg" in err.lower() or "ffprobe" in err.lower():
                hint = "\n\n提示: 需要 ffmpeg，MP3下载或部分视频需要"
            self._run_on_ui("download-error", lambda: (
                self.status.config(text=f"下载失败: {item['name'][:30]}"),
                self._show_toast_ui("下载失败", err[:300] + hint, "error"),
                self.dl_prog.stop(),
                self.dl_prog.config(value=0, mode="determinate")))
        finally:
            self._run_on_ui("download-finished", lambda: (
                self.dl_prog.stop(),
                self.dl_prog.config(mode="determinate"),
                self._queue_refresh_tree(),
                self.history_tree_refresh(),
                self._log_refresh()))
    
    def _fmt_speed(self, speed):
        """格式化下载速度"""
        if not speed:
            return ""
        if speed > 1024*1024:
            return f"{speed/1024/1024:.1f} MB/s"
        if speed > 1024:
            return f"{speed/1024:.0f} KB/s"
        return f"{speed} B/s"

    def _start_song_search(self):
        """歌曲搜索下载：展示搜索结果列表让用户选择"""
        q = self.song_var.get().strip()
        if not q:
            self.show_toast("提示", "请输入歌曲名或歌手", "warning")
            return
        self.status.config(text=f"正在搜索: {q} ...")

        def run():
            results = []
            # 1. 先查 B 站（国内直连）
            try:
                results = search_bilibili_songs(q, limit=8)
            except Exception as e:
                Logger.log(f"B站搜索失败: {e}")
            # 2. B 站有结果 → 弹窗让用户选择
            if results:
                self._run_on_ui("song-results", lambda r=results: self._show_song_results(q, r))
                return
            # 3. B 站无结果 → ytsearch 兜底（直接加入队列）
            url = f"ytsearch:{q}"
            with self.dl_queue_lock:
                self.dl_queue.append({
                    "url": url, "is_mp3": True,
                    "status": "waiting", "name": f"🎵 {q}", "error": "",
                    "progress": "",
                })
            self._run_on_ui("song-fallback", lambda: (
                self._queue_refresh_tree(),
                self.status.config(text=f"B站无结果，已加入 YouTube 搜索: {q}")))
            self._start_queue_worker()

        threading.Thread(target=run, daemon=True).start()

    def _show_song_results(self, query, results):
        """弹窗展示 B 站搜索结果，让用户选择"""
        dlg = tk.Toplevel(self)
        dlg.title(f"选择歌曲 - {query}")
        dlg.geometry("520x420")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        ttk.Label(dlg, text=f"🔍 搜索: {query}  （共 {len(results)} 条结果）",
                  font=(UI_FONT, 11, "bold"), bootstyle="info").pack(padx=12, pady=(12, 6), anchor=W)
        ttk.Label(dlg, text="点击选中后自动开始下载 MP3",
                  font=(UI_FONT, 9), bootstyle="secondary").pack(padx=12, anchor=W)

        # 结果列表
        tree = ttk.Treeview(dlg, columns=("idx", "title", "author", "duration"),
                            show="headings", height=12, selectmode="browse")
        tree.heading("idx", text="#")
        tree.heading("title", text="标题")
        tree.heading("author", text="UP主")
        tree.heading("duration", text="时长")
        tree.column("idx", width=35, anchor=CENTER, stretch=False)
        tree.column("title", width=260)
        tree.column("author", width=120)
        tree.column("duration", width=60, anchor=CENTER, stretch=False)

        for i, r in enumerate(results):
            tree.insert("", END, iid=str(i),
                        values=(i + 1, r["title"][:40], r["author"][:12], r["duration"]))

        tree.pack(fill=BOTH, expand=True, padx=12, pady=6)

        def on_select(event=None):
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            r = results[idx]
            url = r["url"]
            title = r["title"]
            # 加入队列
            with self.dl_queue_lock:
                self.dl_queue.append({
                    "url": url, "is_mp3": True,
                    "status": "waiting", "name": f"🎵 {title}", "error": "",
                    "progress": "",
                })
            self._run_on_ui("queue-refresh", lambda: (
                self._queue_refresh_tree(),
                self.status.config(text=f"已加入队列: {title}")))
            self._start_queue_worker()
            dlg.destroy()
            self.show_toast("已添加", f"已将 [{title}] 加入下载队列", "info")

        tree.bind("<Double-1>", on_select)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill=X, padx=12, pady=8)
        ttk.Button(btn_frame, text="▶ 下载选中", bootstyle="success",
                   command=on_select).pack(side=LEFT, padx=4)
        ttk.Button(btn_frame, text="取消", bootstyle="secondary",
                   command=dlg.destroy).pack(side=RIGHT, padx=4)

    # ========== 队列管理方法 ==========

    def _open_output_folder(self):
        """打开输出目录（Windows 专用）"""
        try:
            os.startfile(self.output_dir)
        except Exception:
            import subprocess as _sp
            _sp.Popen(["xdg-open", self.output_dir] if os.name != "nt" else ["explorer", self.output_dir])

    def _queue_refresh_tree(self):
        """刷新队列 Treeview + 总进度。

        原地更新每行的值而不是整表重建，避免下载过程中高频刷新
        不断清空用户的多选与滚动位置。
        """
        rows = []
        with self.dl_queue_lock:
            total = len(self.dl_queue)
            done_count = sum(1 for it in self.dl_queue if it["status"] == "done")
            failed_count = sum(1 for it in self.dl_queue if it["status"] == "failed")
            for i, it in enumerate(self.dl_queue):
                status_text = self._STATUS_ICONS.get(it["status"], f"? {it['status']}")
                name_text = it["name"][:50] if it["name"] else it["url"][:50]
                progress_text = it.get("progress", "")
                if it["status"] == "done":
                    progress_text = "✓"
                elif it["status"] == "failed":
                    progress_text = "✗"
                rows.append((str(i), (it["status"],),
                             (str(i + 1), status_text, name_text, progress_text)))
        wanted = set()
        for iid, tags, values in rows:
            wanted.add(iid)
            if self.queue_tree.exists(iid):
                if tuple(self.queue_tree.item(iid, "tags")) != tags:
                    self.queue_tree.item(iid, tags=tags)
                if tuple(self.queue_tree.item(iid, "values")) != values:
                    self.queue_tree.item(iid, values=values)
            else:
                self.queue_tree.insert("", END, iid=iid, tags=tags, values=values)
        for iid in set(self.queue_tree.get_children()) - wanted:
            self.queue_tree.delete(iid)
        self.dl_total_label.config(text=f"总进度: {done_count}/{total}  ✗ {failed_count}")
        self.dl_total_prog.config(value=(done_count / max(total, 1)) * 100)

    def _on_queue_double_click(self, event):
        """双击队列行：失败项查看错误详情，完成项直接打开文件"""
        iid = self.queue_tree.identify_row(event.y)
        if not iid:
            return
        idx = int(iid)
        with self.dl_queue_lock:
            if not (0 <= idx < len(self.dl_queue)):
                return
            it = dict(self.dl_queue[idx])
        if it["status"] == "failed":
            self._show_toast_ui("下载失败详情",
                                f"{it.get('name', '') or it.get('url', '')}\n\n{it.get('error') or '未知错误'}",
                                "error")
        elif it["status"] == "done":
            path = Path(self.output_dir) / it.get("name", "")
            if path.exists():
                try:
                    os.startfile(path)
                except Exception:
                    pass

    def _show_queue_menu(self, event):
        iid = self.queue_tree.identify_row(event.y)
        if iid and iid not in self.queue_tree.selection():
            self.queue_tree.selection_set(iid)
        try:
            self._queue_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._queue_menu.grab_release()

    def _queue_move(self, direction):
        sel = self.queue_tree.selection()
        if not sel:
            return
        with self.dl_queue_lock:
            n = len(self.dl_queue)
            blocked = [i for i, it in enumerate(self.dl_queue)
                       if it["status"] == "downloading"]
            order = compute_queue_move(n, [int(i) for i in sel], direction, blocked)
            self.dl_queue = [self.dl_queue[i] for i in order]
        self._queue_refresh_tree()

    def _queue_retry_selected(self):
        sel = self.queue_tree.selection()
        if not sel:
            return
        with self.dl_queue_lock:
            for iid in sel:
                idx = int(iid)
                if 0 <= idx < len(self.dl_queue):
                    it = self.dl_queue[idx]
                    if it["status"] in ("failed", "done"):
                        it["status"] = "retrying"
                        it["error"] = ""
                        it["progress"] = ""
        self._queue_refresh_tree()
        self._start_queue_worker()

    def _queue_delete_selected(self):
        sel = self.queue_tree.selection()
        if not sel:
            return
        with self.dl_queue_lock:
            for iid in sorted(sel, key=int, reverse=True):
                idx = int(iid)
                if 0 <= idx < len(self.dl_queue):
                    it = self.dl_queue[idx]
                    if it["status"] == "downloading":
                        continue
                    del self.dl_queue[idx]
        self._queue_refresh_tree()

    def _queue_clear(self):
        if not messagebox.askyesno("确认", "清空队列中所有等待/失败的项？\n正在下载的项不会被删除。"):
            return
        with self.dl_queue_lock:
            self.dl_queue = [it for it in self.dl_queue if it["status"] == "downloading"]
        self._queue_refresh_tree()


    def history_tree_refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        tag = self.filter_var.get()
        items = self.history.items
        # 从新到旧插入；iid 绑定原始索引，供"删除选中"精准定位
        row = 0
        for idx in range(len(items) - 1, -1, -1):
            h = items[idx]
            if not isinstance(h, dict):
                continue
            typ = str(h.get("type", ""))
            if tag != "全部" and tag not in typ:
                continue
            s = "✓" if h.get("ok") else "✗"
            self.tree.insert("", END, iid=str(idx),
                             tags=("even" if row % 2 == 0 else "odd",),
                             values=(h.get("time", ""), str(h.get("name", ""))[:25], typ, s))
            row += 1
    
    def _on_history_double_click(self, event):
        """双击历史记录：打开对应的输出文件"""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        try:
            idx = int(iid)
        except ValueError:
            return
        with History._lock:
            if not (0 <= idx < len(self.history.items)):
                return
            item = dict(self.history.items[idx])
        out = str(item.get("out") or "")
        if not out or out.startswith("skipped:"):
            self.show_toast("提示", "该记录没有关联的输出文件", "info")
            return
        p = Path(out)
        if p.exists():
            try:
                os.startfile(p)
            except Exception:
                pass
        else:
            self.show_toast("提示", f"文件不存在（可能已被移动或删除）:\n{p.name}", "warning")

    def _history_delete_selected(self):
        """删除勾选的记录（支持多选）"""
        sel = self.tree.selection()
        if not sel:
            self.show_toast("提示", "请先勾选要删除的记录", "warning")
            return
        if not messagebox.askyesno("确认", f"确定删除选中的 {len(sel)} 条记录？"):
            return
        # iid 即 history.items 的原始索引，交给 History.delete 持锁倒序删除
        removed = self.history.delete(int(iid) for iid in sel)
        self.history_tree_refresh()
        self.status.config(text=f"已删除 {removed} 条记录")
        Logger.log(f"🗑 删除历史记录 {removed} 条")
    
    def _history_clear(self):
        if messagebox.askyesno("确认", "清空所有记录?"):
            self.history.clear()
            self.history_tree_refresh()
    
    def _log_refresh(self):
        self.log_text.delete(1.0, END)
        for line in Logger.read()[-200:]:
            self.log_text.insert(END, line + "\n")
        self.log_text.see(END)
    
    def _log_clear(self):
        self.log_text.delete(1.0, END)
        try:
            with _LOG_LOCK:
                Path(_validated_output_file(LOG_FILE, Path.home())).write_text(
                    "", encoding="utf-8")
        except:
            pass


if __name__ == "__main__":
    import traceback as _tb
    
    # 全局异常兜底：未捕获异常记录到日志并提示，不崩溃
    def _global_excepthook(exc_type, exc_value, exc_tb):
        err = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        Logger.log(f"❌ 未捕获异常:\n{err}")
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            root = _tk.Tk()
            root.withdraw()
            _mb.showerror("程序错误", f"发生未处理的错误:\n{exc_value}\n\n详细已记录到日志")
            root.destroy()
        except Exception:
            pass
    
    sys.excepthook = _global_excepthook
    app = App()
    app.mainloop()
