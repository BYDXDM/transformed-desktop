#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transformed - Win7 版 (纯 tkinter，无 ttkbootstrap)
格式转换 + 视频下载
移植自主版本全部修复：B站搜索、下载队列、线程安全、ffmpeg校验、日志锁、历史多选删除
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading, os, sys, json, re, shutil, subprocess
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image
except ImportError:
    Image = None
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

import urllib.request as _urlreq
import urllib.parse
import ipaddress
import socket


def _assert_public_http_url(url):
    """仅允许 http/https，且主机必须解析到公网地址（防内网/本机请求）。"""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("不支持的协议: %s" % parsed.scheme)
    host = parsed.hostname
    if not host:
        raise ValueError("URL 缺少主机名")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError("拒绝访问非公网地址: %s -> %s" % (host, ip))


class _GuardedRedirectHandler(_urlreq.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_GUARDED_OPENER = None
_GUARDED_OPENER_LOCK = threading.Lock()


def guarded_urlopen(req, timeout):
    """带公网校验的 urlopen，拦截重定向到内网。"""
    global _GUARDED_OPENER
    url = req.full_url if isinstance(req, _urlreq.Request) else req
    _assert_public_http_url(url)
    with _GUARDED_OPENER_LOCK:
        if _GUARDED_OPENER is None:
            _GUARDED_OPENER = _urlreq.build_opener(_GuardedRedirectHandler())
    return _GUARDED_OPENER.open(req, timeout=timeout)

HISTORY_FILE = Path.home() / ".transformed_history.json"
LOG_FILE = Path.home() / ".transformed_log.txt"


def _validated_output_file(path, base):
    """规范化目标路径并确保其位于 base 目录内，防止路径穿越。"""
    base = Path(base).resolve()
    target = Path(path).resolve()
    if target != base and base not in target.parents:
        raise ValueError("拒绝写入 %s 之外的路径: %s" % (base, target))
    return target

# 颜色方案（深色简洁）
BG = "#1e1e2e"
FG = "#e0e0e0"
ACCENT = "#7aa2f7"
CARD_BG = "#2a2a3e"
BTN_BG = "#565f89"

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

# =====================================================================
# 日志：线程安全 + 自动裁剪
# =====================================================================
_LOG_LOCK = threading.Lock()
_LOG_MAX = 500  # 日志行数上限


def log_msg(msg):
    """线程安全写日志"""
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    entry = f"[{ts}] {msg}"
    try:
        with _LOG_LOCK:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
            _log_trim()
    except Exception:
        pass
    return entry


def _log_trim():
    """日志超 _LOG_MAX 行时裁剪"""
    try:
        log_file = _validated_output_file(LOG_FILE, Path.home())
        lines = Path(log_file).read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > _LOG_MAX:
            Path(log_file).write_text(
                "".join(lines[-(_LOG_MAX - 100):]), encoding="utf-8")
    except Exception:
        pass


def log_read():
    """读取日志"""
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        except Exception:
            return []
    return []


# =====================================================================
# B站搜索（防 412 风控）
# =====================================================================
_BUVID_CACHE = {"buvid3": None}


def _get_buvid3():
    """从 B 站指纹接口获取真实 buvid3（会话级缓存，搜索/下载共用）"""
    if _BUVID_CACHE["buvid3"]:
        return _BUVID_CACHE["buvid3"]
    try:
        req = _urlreq.Request(
            "https://api.bilibili.com/x/frontend/finger/spi",
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36"),
            })
        with guarded_urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        b_3 = (data.get("data") or {}).get("b_3", "")
        if b_3:
            _BUVID_CACHE["buvid3"] = b_3
            return b_3
    except Exception as e:
        log_msg("获取 buvid3 失败: %s" % e)
    return None


def search_bilibili_song(query):
    """从 B 站搜索视频（歌曲），返回第一个结果的视频链接；无结果返回 None"""
    results = search_bilibili_songs(query, limit=1)
    return results[0]["url"] if results else None


def search_bilibili_songs(query, limit=6):
    """从 B 站搜索视频（歌曲），返回结果列表。
    自动过滤翻唱、伴奏、纯音乐等非原唱结果。"""
    results = []
    try:
        enc = urllib.parse.quote(query)
        buvid3 = _get_buvid3()
        cookie = "buvid3=%s" % buvid3 if buvid3 else "buvid3=infoc"
        req = _urlreq.Request(
            "https://api.bilibili.com/x/web-interface/search/type"
            "?search_type=video&keyword=%s" % enc,
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36"),
                "Referer": "https://www.bilibili.com/",
                "Cookie": cookie,
            })
        with guarded_urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("code") != 0:
            log_msg("B站搜索被拒 code=%s: %s" % (data.get("code"), data.get("message", "")))
            return results
        raw = data.get("data", {}).get("result", [])
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
            tl = title.lower()
            if any(kw in tl for kw in skip_kw):
                continue
            results.append({
                "bvid": bvid, "title": title, "author": author,
                "duration": duration,
                "url": "https://www.bilibili.com/video/%s" % bvid,
            })
            if len(results) >= limit:
                break
        log_msg("B站搜索 '%s' -> %d 条结果" % (query, len(results)))
    except Exception as e:
        log_msg("B站搜索异常: %s" % e)
    return results


# =====================================================================
# ffmpeg 管理
# =====================================================================
def get_ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for c in [APP_DIR / "ffmpeg" / "bin" / "ffmpeg.exe",
              APP_DIR / "ffmpeg" / "bin" / "ffmpeg"]:
        if c.exists():
            return str(c)
    return None


def download_ffmpeg(progress_cb=None):
    if os.name != "nt":
        return False, "仅 Windows 支持自动下载"
    url = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/"
           "latest/ffmpeg-master-latest-win64-gpl-shared.zip")
    dest = APP_DIR / "ffmpeg"
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "ffmpeg.zip"
    try:
        progress_cb and progress_cb("下载 ffmpeg (~30MB)...")
        urllib.request.urlretrieve(url, zip_path)
        progress_cb and progress_cb("解压...")
        ext = dest / "_extract"
        ext.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(ext)
        bin_dir = None
        for d in ext.iterdir():
            if (d / "bin").exists():
                bin_dir = d / "bin"
                break
        if bin_dir:
            target = dest / "bin"
            target.mkdir(exist_ok=True)
            for f in bin_dir.iterdir():
                shutil.copy2(f, target / f.name)
        shutil.rmtree(ext, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        return True, str(get_ffmpeg_path())
    except Exception as e:
        return False, str(e)


# =====================================================================
# History
# =====================================================================
class History:
    def __init__(self):
        self.items = []
        self.load()

    def load(self):
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.items = json.load(f)
            except Exception:
                self.items = []

    def save(self):
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        target = _validated_output_file(HISTORY_FILE, Path.home())
        Path(target).write_text(
            json.dumps(self.items[-500:], indent=2, ensure_ascii=False),
            encoding="utf-8")

    def add(self, name, typ, ok, out=""):
        self.items.append({"time": datetime.now().strftime("%m-%d %H:%M"),
                           "name": name, "type": typ, "ok": ok, "out": out})
        self.save()

    def clear(self):
        self.items = []
        self.save()


# =====================================================================
# App
# =====================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("transformed")
        self.geometry("980x650")
        self.minsize(820, 560)
        self.configure(bg=BG)
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._style_config()
        self.history = History()
        self.task_running = False
        self.output_dir = str(Path.home() / "Downloads" / "transformed_output")
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # 下载队列
        self.dl_queue = []           # [{url, is_mp3, status, name, error, progress}, ...]
        self.dl_queue_lock = threading.Lock()
        self.dl_queue_worker_running = False
        self.dl_current_item = None
        self._url_placeholder_active = True
        self._dl_pct = 0.0

        self._build_ui()
        self._check_deps()

    def _style_config(self):
        self.style.configure("TFrame", background=BG)
        self.style.configure("TLabel", background=BG, foreground=FG)
        self.style.configure("TLabelframe", background=BG, foreground=FG)
        self.style.configure("TLabelframe.Label", background=BG, foreground=FG)
        self.style.configure("TButton", background=BTN_BG, foreground=FG, padding=6)
        self.style.map("TButton", background=[("active", ACCENT)])
        self.style.configure("TNotebook", background=BG)
        self.style.configure("TNotebook.Tab", background=CARD_BG, foreground=FG, padding=(12, 5))
        self.style.configure("Treeview", background=CARD_BG, foreground=FG,
                             fieldbackground=CARD_BG, rowheight=22)
        self.style.configure("Treeview.Heading", background=BTN_BG, foreground=FG)

    def _check_deps(self):
        missing = []
        if not HAS_YTDLP:
            missing.append("yt-dlp")
        if not HAS_EBOOKLIB:
            missing.append("ebooklib")
        if Image is None:
            missing.append("pillow")
        if missing:
            messagebox.showwarning("缺依赖", "缺少: " + ", ".join(missing) +
                                   "\n请重新打包或 pip install")
        if not get_ffmpeg_path():
            if messagebox.askyesno("ffmpeg 未找到",
                                   "MP4转MP3需要 ffmpeg，现在自动下载安装？\n(约30MB)"):
                self._setup_ffmpeg()

    def _setup_ffmpeg(self):
        self.task_running = True
        self._set_status("下载并安装 ffmpeg...")
        threading.Thread(target=self._dl_ffmpeg_thread, daemon=True).start()

    def _dl_ffmpeg_thread(self):
        ok, result = download_ffmpeg(
            lambda msg: self.after(0, lambda m=msg: self._set_status(m)))
        self.task_running = False
        if ok:
            self.after(0, lambda: (
                self._set_status("ffmpeg 安装完成"),
                messagebox.showinfo("成功", "ffmpeg 已安装!")))
        else:
            self.after(0, lambda r=result: (
                self._set_status("ffmpeg 安装失败"),
                messagebox.showerror("失败", r)))

    def _set_status(self, msg):
        self.status_cfg["text"] = msg

    def _fmt_speed(self, speed):
        if not speed:
            return ""
        if speed > 1024 * 1024:
            return "%.1f MB/s" % (speed / 1024 / 1024)
        if speed > 1024:
            return "%d KB/s" % (speed / 1024)
        return "%d B/s" % speed

    def _build_ui(self):
        # 标题
        tk.Label(self, text="transformed", font=("", 20, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(self, text="格式转换 · 视频下载", bg=BG, fg=FG).pack(anchor="w", padx=12)

        # 主区域 PanedWindow
        self.paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 左：Notebook
        left = ttk.Frame(self.paned)
        self.paned.add(left, weight=3)
        nb = ttk.Notebook(left)
        nb.pack(fill=tk.BOTH, expand=True)
        self._build_convert_tab(nb)
        self._build_download_tab(nb)
        self._build_log_tab(nb)

        # 右：历史
        right = ttk.Frame(self.paned)
        self.paned.add(right, weight=2)
        self._build_history(right)

        # 状态栏
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_cfg = ttk.Label(status_frame, text="就绪")
        self.status_cfg.pack(side=tk.LEFT, padx=8)

    # ---- 转换卡片 ----
    def _build_convert_tab(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  格式转换  ")
        self.convert_cards = {}
        self._make_card(tab, "EPUB → TXT", "epub",
                        "选择 EPUB 电子书，批量转换为纯文本")
        self._make_card(tab, "MP4 → MP3", "mp4",
                        "提取 MP4 视频中的音频，保存为 MP3 (需 ffmpeg)")
        self._make_card(tab, "WebP → JPG", "webp",
                        "将 WebP 图片批量转换为 JPEG")

    def _make_card(self, parent, title, key, desc):
        lf = ttk.Labelframe(parent, text=title, padding=10)
        lf.pack(fill=tk.X, pady=4)
        ttk.Label(lf, text=desc).pack(anchor="w")
        btn_row = ttk.Frame(lf)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="选择文件",
                   command=lambda: self._pick(key, self._filetypes(key))).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="开始转换",
                   command=lambda: self._convert(key)).pack(side=tk.LEFT, padx=2)
        label = ttk.Label(btn_row, text="未选择文件")
        label.pack(side=tk.LEFT, padx=8)
        prog = ttk.Progressbar(lf, mode="determinate")
        prog.pack(fill=tk.X, pady=3)
        status = ttk.Label(lf, text="")
        status.pack(anchor="w")
        self.convert_cards[key] = {"files": [], "label": label,
                                   "prog": prog, "status": status}

    def _filetypes(self, key):
        return {"epub": [("EPUB", "*.epub")],
                "mp4": [("MP4", "*.mp4")],
                "webp": [("WebP", "*.webp")]}[key]

    def _pick(self, key, ft):
        files = filedialog.askopenfilenames(filetypes=ft)
        if files:
            self.convert_cards[key]["files"] = list(files)
            self.convert_cards[key]["label"].config(text="已选 %d 个" % len(files))

    def _build_download_tab(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  网络下载  ")

        # ---- 歌曲搜索下载 ----
        song_lf = ttk.Labelframe(tab, text="歌曲搜索下载（MP3）", padding=8)
        song_lf.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(song_lf, text="输入歌手/歌名，自动搜索下载 MP3").pack(anchor="w")
        song_frame = ttk.Frame(song_lf)
        song_frame.pack(fill=tk.X, pady=4)
        self.song_var = tk.StringVar()
        song_entry = tk.Entry(song_frame, textvariable=self.song_var, width=40,
                              bg=CARD_BG, fg=FG, insertbackground=FG)
        song_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        song_entry.bind("<Return>", lambda e: self._start_song_search())
        ttk.Button(song_frame, text="搜索下载", command=self._start_song_search).pack(side=tk.RIGHT)
        ttk.Label(song_lf, text="搜索来源: B站优先(国内直连)，暂无则 ytsearch 兜底",
                  foreground="#8899aa").pack(anchor="w")

        # ---- 视频链接批量下载 ----
        url_lf = ttk.Labelframe(tab, text="视频链接下载（支持批量）", padding=8)
        url_lf.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(url_lf, text="每行一个链接，支持 B站/BV号/AV号/YouTube/X/直链",
                  foreground="#8899aa").pack(anchor="w", pady=(0, 4))

        # 多行文本输入
        self.url_text = tk.Text(url_lf, height=4, font=("", 10),
                                bg="#111122", fg=FG, insertbackground=FG,
                                wrap=tk.WORD, relief=tk.FLAT, padx=8, pady=6)
        self.url_text.pack(fill=tk.X, pady=(0, 4))
        self._url_placeholder = ("粘贴链接到此处，每行一个...\n"
                                 "例如:\n"
                                 "https://www.bilibili.com/video/BV...\n"
                                 "youtube.com/watch?v=...")
        self._set_url_placeholder(True)
        self.url_text.bind("<FocusIn>", self._on_url_focus_in)
        self.url_text.bind("<FocusOut>", self._on_url_focus_out)

        # 格式 + 按钮行
        btn_row = ttk.Frame(url_lf)
        btn_row.pack(fill=tk.X, pady=(0, 2))
        self.dl_type = tk.StringVar(value="mp4")
        ttk.Radiobutton(btn_row, text="视频 MP4", variable=self.dl_type,
                        value="mp4").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(btn_row, text="音频 MP3", variable=self.dl_type,
                        value="mp3").pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="添加到队列", command=self._start_dl).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_row, text="开始下载", command=self._start_queue).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_row, text="打开文件夹", command=self._open_output_folder).pack(side=tk.RIGHT, padx=2)

        # ---- 下载队列 ----
        queue_lf = ttk.Labelframe(tab, text="下载队列", padding=8)
        queue_lf.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        q_cols = ("idx", "status", "name", "progress")
        self.queue_tree = ttk.Treeview(queue_lf, columns=q_cols, show="headings",
                                       height=6, selectmode="extended")
        self.queue_tree.heading("idx", text="#")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.heading("name", text="文件名 / URL")
        self.queue_tree.heading("progress", text="进度")
        self.queue_tree.column("idx", width=36, anchor="center", stretch=False)
        self.queue_tree.column("status", width=70, anchor="center", stretch=False)
        self.queue_tree.column("name", width=300)
        self.queue_tree.column("progress", width=64, anchor="center", stretch=False)
        self.queue_tree.tag_configure("waiting", foreground="#8899aa")
        self.queue_tree.tag_configure("downloading", foreground="#00ccff")
        self.queue_tree.tag_configure("done", foreground="#44cc44")
        self.queue_tree.tag_configure("failed", foreground="#ff5555")
        self.queue_tree.tag_configure("retrying", foreground="#ffaa00")
        q_scroll = ttk.Scrollbar(queue_lf, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=q_scroll.set)
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        q_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.queue_tree.bind("<Delete>", lambda e: self._queue_delete_selected())

        q_btns = ttk.Frame(queue_lf)
        q_btns.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(q_btns, text="上移", command=lambda: self._queue_move(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(q_btns, text="下移", command=lambda: self._queue_move(1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(q_btns, text="重试选中", command=self._queue_retry_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(q_btns, text="删除选中", command=self._queue_delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(q_btns, text="清空队列", command=self._queue_clear).pack(side=tk.RIGHT, padx=2)

        # ---- 进度区 ----
        prog_lf = ttk.Labelframe(tab, text="下载进度", padding=6)
        prog_lf.pack(fill=tk.X)
        self.dl_total_label = ttk.Label(prog_lf, text="总进度: 0/0")
        self.dl_total_label.pack(anchor="w")
        self.dl_total_prog = ttk.Progressbar(prog_lf, mode="determinate")
        self.dl_total_prog.pack(fill=tk.X, pady=2)
        ttk.Label(prog_lf, text="当前:").pack(anchor="w", pady=(2, 0))
        self.dl_prog = ttk.Progressbar(prog_lf, mode="determinate")
        self.dl_prog.pack(fill=tk.X, pady=2)
        self.dl_stat = ttk.Label(prog_lf, text="")
        self.dl_stat.pack(anchor="w")

        ttk.Label(tab, text="支持: B站 / YouTube / Twitter / 直链",
                  foreground=ACCENT).pack(anchor="w", pady=(6, 0))

    def _build_log_tab(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  运行日志  ")
        b = ttk.Frame(tab)
        b.pack(fill=tk.X)
        ttk.Button(b, text="刷新", command=self._log_refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="清空", command=self._log_clear).pack(side=tk.LEFT, padx=2)
        self.log_text = scrolledtext.ScrolledText(tab, height=12, bg="#111122", fg="#d0d0e0")
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=4)

    def _build_history(self, parent):
        ttk.Label(parent, text="  转换记录  ").pack(anchor="w", pady=(0, 4))
        filt = ttk.Frame(parent)
        filt.pack(fill=tk.X)
        self.filter_var = tk.StringVar(value="全部")
        for tag in ["全部", "EPUB", "MP4", "WebP", "下载"]:
            ttk.Radiobutton(filt, text=tag, variable=self.filter_var,
                            value=tag, command=self._history_refresh).pack(side=tk.LEFT, padx=2)
        cols = ("time", "file", "type", "status")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings",
                                 selectmode="extended")
        for c, w, t in [("time", 80, "时间"), ("file", 160, "文件"),
                        ("type", 70, "类型"), ("status", 40, "状态")]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=4)
        btm = ttk.Frame(parent)
        btm.pack(fill=tk.X, pady=4)
        ttk.Button(btm, text="删除选中", command=self._history_delete_selected).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btm, text="清空", command=self._history_clear).pack(side=tk.RIGHT, padx=2)
        self._history_refresh()

    # ========== 占位符逻辑 ==========
    def _on_url_focus_in(self, event=None):
        if self._url_placeholder_active:
            self.url_text.delete("1.0", tk.END)
            self.url_text.config(fg=FG)
            self._url_placeholder_active = False

    def _on_url_focus_out(self, event=None):
        self._set_url_placeholder(True)

    def _set_url_placeholder(self, show):
        if show:
            content = self.url_text.get("1.0", tk.END).strip()
            if not content:
                self.url_text.delete("1.0", tk.END)
                self.url_text.insert("1.0", self._url_placeholder)
                self.url_text.config(fg="#667788")
                self._url_placeholder_active = True
            else:
                self._url_placeholder_active = False
        else:
            self._url_placeholder_active = False

    def _get_urls_from_text(self):
        if self._url_placeholder_active:
            return []
        self._set_url_placeholder(False)
        raw = self.url_text.get("1.0", tk.END).strip()
        if not raw:
            return []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        seen = set()
        urls = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                urls.append(line)
        return urls

    # ========== URL 智能处理 ==========
    def _prepare_url(self, url):
        url = url.strip()
        if not url:
            return url
        # 从混合文本中提取 URL
        url_match = re.search(r'(https?://[^\s<>"\'\]]+)', url, re.IGNORECASE)
        if url_match:
            url = url_match.group(1).rstrip('，。！？、,.;!?')
            return url
        # BV号
        m = re.search(r'(BV[0-9A-Za-z]{10})', url)
        if m:
            return "https://www.bilibili.com/video/%s" % m.group(1)
        # AV号
        m = re.search(r'(av\d+)', url, re.IGNORECASE)
        if m:
            return "https://www.bilibili.com/video/%s" % m.group(1)
        # b23.tv 短链
        m = re.match(r'(b23\.tv/[0-9A-Za-z]+)', url, re.IGNORECASE)
        if m:
            return "https://%s" % m.group(1)
        # 无协议完整域名
        if "." in url and re.search(r'\.[a-zA-Z]{2,}(/|$)', url):
            return "https://" + url
        return url

    # ========== 歌曲搜索 ==========
    def _start_song_search(self):
        q = self.song_var.get().strip()
        if not q:
            messagebox.showwarning("提示", "请输入歌曲名或歌手")
            return
        self._set_status("正在搜索: %s ..." % q)

        def run():
            results = []
            try:
                results = search_bilibili_songs(q, limit=8)
            except Exception as e:
                log_msg("B站搜索失败: %s" % e)
            if results:
                self.after(0, lambda r=results: self._show_song_results(q, r))
                return
            # B站无结果 → ytsearch 兜底
            url = "ytsearch:%s" % q
            with self.dl_queue_lock:
                self.dl_queue.append({
                    "url": url, "is_mp3": True,
                    "status": "waiting", "name": "🎵 %s" % q, "error": "",
                    "progress": "",
                })
            self.after(0, lambda: (
                self._queue_refresh_tree(),
                self._set_status("B站无结果，已加入 YouTube 搜索: %s" % q)))
            self._start_queue_worker()

        threading.Thread(target=run, daemon=True).start()

    def _show_song_results(self, query, results):
        """弹窗展示 B 站搜索结果，让用户选择"""
        dlg = tk.Toplevel(self)
        dlg.title("选择歌曲 - %s" % query)
        dlg.geometry("520x420")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="搜索: %s  （共 %d 条结果）" % (query, len(results)),
                 font=("", 11, "bold"), fg="#00aaff").pack(padx=12, pady=(12, 6), anchor=W)
        tk.Label(dlg, text="双击或点击「下载选中」加入队列",
                 font=("", 9), fg="#888").pack(padx=12, anchor=W)

        # 结果列表
        cols = ("idx", "title", "author", "duration")
        tree = tk.ttk.Treeview(dlg, columns=cols, show="headings", height=12)
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
            with self.dl_queue_lock:
                self.dl_queue.append({
                    "url": url, "is_mp3": True,
                    "status": "waiting", "name": "🎵 %s" % title, "error": "",
                    "progress": "",
                })
            self.after(0, lambda: (
                self._queue_refresh_tree(),
                self._set_status("已加入队列: %s" % title)))
            self._start_queue_worker()
            dlg.destroy()

        tree.bind("<Double-1>", on_select)

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(fill=X, padx=12, pady=8)
        tk.Button(btn_frame, text="下载选中", command=on_select,
                  bg="#28a745", fg="white", font=("", 10, "bold")).pack(side=LEFT, padx=4)
        tk.Button(btn_frame, text="取消", command=dlg.destroy,
                  font=("", 10)).pack(side=RIGHT, padx=4)

    # ========== 转换逻辑 ==========
    def _convert(self, key):
        if self.task_running:
            messagebox.showwarning("提示", "任务执行中")
            return
        ct = self.convert_cards[key]
        if not ct["files"]:
            messagebox.showwarning("提示", "请先选择文件")
            return
        self.task_running = True
        threading.Thread(target=self._do_convert, args=(key,), daemon=True).start()

    def _do_convert(self, key):
        ct = self.convert_cards[key]
        fn_map = {"epub": ("EPUB→TXT", self._conv_epub),
                  "mp4": ("MP4→MP3", self._conv_mp4),
                  "webp": ("WebP→JPG", self._conv_webp)}
        typ, fn = fn_map[key]
        total = len(ct["files"])
        for i, f in enumerate(ct["files"]):
            def mk_cb(i, f):
                def cb(pct, msg):
                    overall = (i / total) + (pct / total)
                    self.after(0, lambda p=overall, n=i, fn=Path(f).name, m=msg: (
                        ct["prog"].config(value=min(p * 100, 100)),
                        ct["status"].config(text="[%d/%d] %s: %s" % (n + 1, total, fn, m)),
                        self.dl_prog.config(value=min(p * 100, 100)),
                        self.dl_stat.config(text="%s: [%d/%d]" % (typ, n + 1, total))))
                return cb
            cb = mk_cb(i, f)
            try:
                ok, result = fn(f, self.output_dir, cb)
            except Exception as e:
                ok, result = False, str(e)
                log_msg("转换异常: %s: %s" % (Path(f).name, e))
            self.history.add(Path(f).name, typ, ok, result if ok else "")
            log_msg("%s %s: %s" % ("✓" if ok else "✗", typ, Path(f).name))
        self.task_running = False
        self.after(0, lambda: (
            ct["label"].config(text="完成"),
            ct["prog"].config(value=0),
            self.dl_prog.config(value=0),
            self._history_refresh(),
            self._log_refresh()))
        messagebox.showinfo("完成", "%s 转换完成！\n保存至: %s" % (typ, self.output_dir))

    def _conv_epub(self, path, out_dir, cb):
        if not HAS_EBOOKLIB:
            return False, "缺 ebooklib"
        try:
            cb(0.1, "读取...")
            book = epub.read_epub(path)
            out = Path(out_dir) / "%s.txt" % Path(path).stem
            texts = []
            items = list(book.get_items_of_type(9))
            for i, it in enumerate(items):
                html = it.get_body_content().decode("utf-8", errors="replace")
                import html as hm
                text = re.sub(r"<[^>]+>", " ", html)
                text = hm.unescape(text)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    texts.append(text)
                cb(0.1 + (i / len(items)) * 0.8, "解析 %d/%d" % (i + 1, len(items)))
            out = _validated_output_file(out, out_dir)
            Path(out).write_text("\n\n".join(texts), encoding="utf-8")
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)

    def _conv_mp4(self, path, out_dir, cb):
        ff = get_ffmpeg_path()
        if not ff:
            return False, "未找到 ffmpeg"
        try:
            cb(0.2, "提取音频...")
            out = Path(out_dir) / "%s.mp3" % Path(path).stem
            proc = subprocess.run([ff, "-i", str(path), "-vn", "-acodec",
                                   "libmp3lame", "-ab", "192k", "-y", str(out)],
                                  capture_output=True)
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")[-300:]
                return False, "ffmpeg 转换失败(code=%d): %s" % (proc.returncode, err)
            if not out.exists() or out.stat().st_size == 0:
                return False, "ffmpeg 未生成输出文件"
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)

    def _conv_webp(self, path, out_dir, cb):
        if Image is None:
            return False, "缺 pillow"
        try:
            cb(0.3, "解码...")
            img = Image.open(path)
            out = Path(out_dir) / "%s.jpg" % Path(path).stem
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            img.save(out, "JPEG", quality=92)
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)

    # ========== 下载队列 ==========
    _STATUS_ICONS = {
        "waiting": "○", "downloading": "▶", "done": "✓",
        "failed": "✗", "retrying": "↻",
    }

    def _start_dl(self):
        """将文本框中的链接添加到下载队列"""
        urls = self._get_urls_from_text()
        if not urls:
            messagebox.showwarning("提示", "请输入至少一个视频链接")
            return
        is_mp3 = self.dl_type.get() == "mp3"
        added = 0
        with self.dl_queue_lock:
            for url in urls:
                self.dl_queue.append({
                    "url": url, "is_mp3": is_mp3,
                    "status": "waiting", "name": url[:80], "error": "",
                    "progress": "",
                })
                added += 1
        self.after(0, self._queue_refresh_tree)
        self._set_status("已添加 %d 个链接到队列" % added)
        # 清空输入框
        self.url_text.delete("1.0", tk.END)
        self._set_url_placeholder(True)
        self._start_queue_worker()

    def _start_queue(self):
        self._start_queue_worker()

    def _start_queue_worker(self):
        if self.dl_queue_worker_running:
            return
        self.dl_queue_worker_running = True
        threading.Thread(target=self._queue_worker, daemon=True).start()

    def _queue_worker(self):
        while True:
            item = None
            with self.dl_queue_lock:
                for it in self.dl_queue:
                    if it["status"] in ("waiting", "retrying"):
                        item = it
                        break
            if item is None:
                self.dl_queue_worker_running = False
                self.after(0, lambda: self._set_status("队列下载完成"))
                return
            item["status"] = "downloading"
            self.dl_current_item = item
            self.after(0, self._queue_refresh_tree)
            self.after(0, lambda n=item["name"][:40]:
                       self._set_status("正在下载: %s" % n))
            try:
                self._do_dl_item(item)
            except Exception as e:
                log_msg("队列项异常: %s" % e)
                item["status"] = "failed"
                item["error"] = str(e)
            self.dl_current_item = None
            self.after(0, self._queue_refresh_tree)

    def _do_dl_item(self, item):
        """下载单个队列项（后台线程）"""
        url = item["url"]
        is_mp3 = item["is_mp3"]
        self._dl_pct = 0.0

        if not HAS_YTDLP:
            item["status"] = "failed"
            item["error"] = "请安装 yt-dlp"
            self.after(0, lambda: messagebox.showerror("缺少依赖", "请安装 yt-dlp"))
            return

        def cb(pct, msg):
            pct = max(pct, 0.05)
            self._dl_pct = max(self._dl_pct, pct)
            item["progress"] = "%.1f%%" % (self._dl_pct * 100)
            self.after(0, lambda p=self._dl_pct, m=msg: (
                self.dl_prog.config(value=p * 100),
                self.dl_stat.config(text=m),
                self._queue_refresh_tree(),
                self.update_idletasks()))

        ready_url = self._prepare_url(url)
        cb(0.05, "解析链接...")
        log_msg("下载: %s -> %s" % (url, ready_url))

        def progress_hook(d):
            status = d.get('status')
            if status == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                speed = d.get('speed') or 0
                if total:
                    mapped = 0.05 + (downloaded / total) * 0.90
                    self._dl_pct = max(self._dl_pct, mapped)
                    pct_show = self._dl_pct * 100
                    item["progress"] = "%.1f%%" % pct_show
                    self.after(0, lambda p=pct_show, s=speed: (
                        self.dl_prog.config(value=min(p, 100)),
                        self.dl_stat.config(text="下载中 %.1f%%  %s" % (p, self._fmt_speed(s)) if s else "下载中... %.1f%%" % p),
                        self._queue_refresh_tree(),
                        self.update()))
                else:
                    self.after(0, lambda s=speed: (
                        self.dl_stat.config(text="下载中... %s" % self._fmt_speed(s))))
            elif status == 'finished':
                self.after(0, lambda: (
                    self.dl_prog.config(value=95),
                    self.dl_stat.config(text="95% 合并/转码中..."),
                    self.update()))

        try:
            opts = {
                "outtmpl": str(Path(self.output_dir) / "%(title)s.%(ext)s"),
                "quiet": True, "no_warnings": True,
                "progress_hooks": [progress_hook],
                "retries": 5,
                "fragment_retries": 5,
                "socket_timeout": 30,
                "concurrent_fragment_downloads": 4,
                "continuedl": True,
                "skip_unavailable_fragments": True,
                "windowsfilenames": True,
                "noplaylist": True,
            }
            # B站特殊处理：完整 Chrome UA + Referer + buvid3 Cookie 防 412 风控
            if ("bilibili" in ready_url or ready_url.startswith("BV")
                    or ready_url.startswith("av")):
                headers = {
                    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/120.0.0.0 Safari/537.36"),
                    "Referer": "https://www.bilibili.com/",
                }
                buvid3 = _get_buvid3()
                if buvid3:
                    headers["Cookie"] = "buvid3=%s" % buvid3
                opts.update({
                    "referer": "https://www.bilibili.com/",
                    "http_headers": headers,
                })
            ff = get_ffmpeg_path()
            if ff:
                opts["ffmpeg_location"] = str(Path(ff).parent)

            # 格式选择
            if ("bilibili.com" in ready_url or ready_url.startswith("BV")
                    or ready_url.startswith("av")):
                if is_mp3:
                    opts["format"] = "ba/b"
                    opts["postprocessors"] = [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }]
                else:
                    opts["format"] = "bv*+ba/b"
                    opts["merge_output_format"] = "mp4/mkv"
            else:
                if is_mp3:
                    opts["format"] = "bestaudio/best"
                    opts["postprocessors"] = [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }]
                else:
                    opts["format"] = "best[height<=720]/best"

            cb(0.2, "下载中...")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(ready_url, download=True)
            fn = ydl.prepare_filename(info)
            if is_mp3:
                fn = str(Path(fn).with_suffix(".mp3"))

            cb(1.0, "完成!")
            name = Path(fn).name
            item["name"] = name
            item["status"] = "done"
            item["progress"] = "100%"
            self.history.add(name, "下载", True, fn)
            log_msg("下载成功: %s" % name)
            self.after(0, lambda n=name: self._set_status("下载成功: %s" % n))
        except Exception as e:
            log_msg("下载失败: %s" % e)
            err = str(e)
            item["status"] = "failed"
            item["error"] = err[:200]
            self.after(0, lambda: (
                self._set_status("下载失败: %s" % item["name"][:30]),
                self.dl_prog.config(value=0)))
            self.after(0, lambda: messagebox.showerror("下载失败", err[:300]))
        finally:
            self.after(0, lambda: (
                self.dl_prog.config(value=0),
                self._queue_refresh_tree(),
                self._history_refresh(),
                self._log_refresh()))

    # ========== 队列管理 ==========
    def _open_output_folder(self):
        try:
            os.startfile(self.output_dir)
        except Exception:
            pass

    def _queue_refresh_tree(self):
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        with self.dl_queue_lock:
            total = len(self.dl_queue)
            done_count = sum(1 for it in self.dl_queue if it["status"] == "done")
            failed_count = sum(1 for it in self.dl_queue if it["status"] == "failed")
            for i, it in enumerate(self.dl_queue):
                icon = self._STATUS_ICONS.get(it["status"], "?")
                status_text = "%s %s" % (icon, it["status"])
                name_text = it["name"][:50] if it["name"] else it["url"][:50]
                progress_text = it.get("progress", "")
                if it["status"] == "done":
                    progress_text = "✓"
                elif it["status"] == "failed":
                    progress_text = "✗"
                self.queue_tree.insert("", "end", iid=str(i),
                                       tags=(it["status"],),
                                       values=(i + 1, status_text, name_text, progress_text))
        self.after(0, lambda d=done_count, t=total, f=failed_count: (
            self.dl_total_label.config(text="总进度: %d/%d  ✗ %d" % (d, t, f)),
            self.dl_total_prog.config(value=(d / max(t, 1)) * 100)))

    def _queue_move(self, direction):
        sel = self.queue_tree.selection()
        if not sel:
            return
        with self.dl_queue_lock:
            for iid in sel:
                idx = int(iid)
                new_idx = idx + direction
                if 0 <= new_idx < len(self.dl_queue):
                    self.dl_queue[idx], self.dl_queue[new_idx] = \
                        self.dl_queue[new_idx], self.dl_queue[idx]
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

    # ========== 历史记录 ==========
    def _history_refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        tag = self.filter_var.get()
        items = self.history.items
        row = 0
        for idx in range(len(items) - 1, -1, -1):
            h = items[idx]
            if tag != "全部" and tag not in h["type"]:
                continue
            s = "✓" if h["ok"] else "✗"
            self.tree.insert("", "end", iid=str(idx),
                             values=(h["time"], h["name"][:25],
                                     h["type"], s))
            row += 1

    def _history_delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先勾选要删除的记录")
            return
        if not messagebox.askyesno("确认", "确定删除选中的 %d 条记录？" % len(sel)):
            return
        for iid in sorted(sel, key=int, reverse=True):
            idx = int(iid)
            if 0 <= idx < len(self.history.items):
                del self.history.items[idx]
        self.history.save()
        self._history_refresh()
        self._set_status("已删除 %d 条记录" % len(sel))
        log_msg("删除历史记录 %d 条" % len(sel))

    def _history_clear(self):
        if messagebox.askyesno("确认", "清空记录?"):
            self.history.clear()
            self._history_refresh()

    # ========== 日志 ==========
    def _log_refresh(self):
        self.log_text.delete(1.0, "end")
        for line in log_read()[-200:]:
            self.log_text.insert("end", line + "\n")
        self.log_text.see("end")

    def _log_clear(self):
        self.log_text.delete(1.0, "end")
        try:
            with _LOG_LOCK:
                Path(_validated_output_file(LOG_FILE, Path.home())).write_text(
                    "", encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    import traceback as _tb

    def _global_excepthook(exc_type, exc_value, exc_tb):
        err = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        log_msg("未捕获异常:\n%s" % err)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("程序错误", "发生未处理的错误:\n%s\n\n详细已记录到日志" % exc_value)
            root.destroy()
        except Exception:
            pass

    sys.excepthook = _global_excepthook
    app = App()
    app.mainloop()
