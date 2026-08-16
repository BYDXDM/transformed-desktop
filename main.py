#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transformed 桌面版 - 现代化 UI
格式转换 + 网络视频下载
"""

import sys
import io
# 强制使用 UTF-8，解决 Windows 控制台乱码
if sys.stdout and hasattr(sys.stdout, 'encoding'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
try:
    io.sys = sys
except Exception:
    pass

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import threading
import os
import sys
import json
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageTk
import base64
import io

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

# ===== ffmpeg 管理 =====
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
    zip_path = dest / "ffmpeg.zip"
    
    try:
        progress_cb and progress_cb("正在下载 ffmpeg (约30MB)...")
        import urllib.request
        urllib.request.urlretrieve(url, zip_path)
        
        progress_cb and progress_cb("正在解压...")
        import zipfile
        with zipfile.ZipFile(zip_path) as z:
            # 解压到临时，然后移动 bin/ 内容
            extract_dir = dest / "_extract"
            extract_dir.mkdir(exist_ok=True)
            z.extractall(extract_dir)
        
        # 找到 bin 目录（解压出来可能是 ffmpeg-master-latest-win64-gpl-shared/）
        bin_dir = None
        for d in extract_dir.iterdir():
            b = d / "bin"
            if b.exists():
                bin_dir = b
                break
        
        if bin_dir:
            # 移动 ffmpeg.exe 到我们的 ffmpeg/bin/
            target = dest / "bin"
            target.mkdir(exist_ok=True)
            for f in bin_dir.iterdir():
                shutil.copy2(f, target / f.name)
        
        # 清理
        shutil.rmtree(extract_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        
        return True, str(get_ffmpeg_path())
    except Exception as e:
        return False, f"ffmpeg 下载失败: {e}"

# ===== 工具类 =====
import urllib.request as _urlreq
import urllib.parse

def check_foreign_access():
    """检测当前网络能否访问外网(YouTube等)。返回 (bool, 信息)
    - 能访问外网: (True, 描述)
    - 不能(需代理): (False, 原因描述)
    """
    # 通过 ipinfo 获取出口 IP 归属地
    try:
        req = _urlreq.Request("https://ipinfo.io/json", 
                             headers={"User-Agent": "Mozilla/5.0"})
        with _urlreq.urlopen(req, timeout=5) as r:
            import json as _j
            data = _j.loads(r.read().decode())
            country = data.get("country", "")
            ip = data.get("ip", "?")
            org = data.get("org", "")
            if country == "CN":
                return False, f"当前 IP({ip})归属中国，直连外网受限，下载 YouTube/X 需代理"
            return True, f"当前 IP({ip}) 非中国归属，可访问外网"
    except Exception as e:
        # ipinfo 都连不上，尝试直接测 google 连通性
        try:
            req = _urlreq.Request("https://www.youtube.com", 
                                 headers={"User-Agent": "Mozilla/5.0"})
            with _urlreq.urlopen(req, timeout=5) as r:
                return True, "可访问外网(YouTube可达)"
        except Exception:
            return False, "无法访问外网(YouTube不可达)，可能需要代理"


def _get_buvid3():
    """从 B 站指纹接口获取真实 buvid3（硬编码假值会被 412 风控拦截）"""
    try:
        req = _urlreq.Request(
            "https://api.bilibili.com/x/frontend/finger/spi",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })
        with _urlreq.urlopen(req, timeout=8) as r:
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
        with _urlreq.urlopen(req, timeout=8) as r:
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
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > _LOG_MAX:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-(_LOG_MAX - 100):])
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
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.items[-500:], f, indent=2, ensure_ascii=False)
    
    def add(self, name, typ, ok, out=""):
        self.items.append({
            "time": datetime.now().strftime("%m-%d %H:%M"),
            "name": name, "type": typ,
            "ok": ok, "out": out
        })
        self.save()
    
    def clear(self):
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
        super().__init__(title="transformed", themename="superhero")
        
        self.geometry("1280x800")
        self.minsize(1050, 650)
        
        self.history = History()
        self.task_running = False
        self.convert_cards = {}
        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        self.output_dir = str(exe_dir / "transformed_output")
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # ===== 下载队列 =====
        self.dl_queue = []           # [{url, is_mp3, status, name, error}, ...]
        self.dl_queue_lock = threading.Lock()
        self.dl_queue_worker_running = False
        self.dl_current_item = None  # 当前正在下载的队列项引用
        self._url_placeholder_active = True
        self._dl_pct = 0.0
        
        # 两侧看板娘立绘（深海女仆工坊 · 鲸鱼娘 CC BY-NC-SA 4.0）
        # 目标高度 = 窗口高(800) - header(55) - status(35) - padding(30) ≈ 680
        self._whale_h = 680
        self.img_left = self._load_whale("whale_left.webp", 235, self._whale_h)
        self.img_right = self._load_whale("whale_right.webp", 235, self._whale_h)
        
        self._build_ui()
        self._check_deps()
    
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
            self.after(0, lambda m=msg: self.status.config(text=m))
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
        """可靠的消息弹窗。后台线程调用传 _from_thread=True"""
        if _from_thread:
            self.after(0, lambda: self._show_toast_ui(title, msg, level))
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
        header = ttk.Frame(self, padding=(18, 14, 14, 8))
        header.pack(fill=X)
        
        ttk.Label(header, text="🐳 transformed", font=("", 22, "bold"),
                 bootstyle="inverse-primary").pack(side=LEFT)
        ttk.Label(header, text="格式转换 · 视频下载 · 深海女仆工坊",
                 font=("", 10), bootstyle="secondary").pack(side=LEFT, padx=12, pady=(6, 0))
        
        # 设置按钮
        ttk.Button(header, text="⚙ 输出目录",
                  command=self._set_output, bootstyle="outline").pack(side=RIGHT, padx=2)
        ttk.Button(header, text="⟳", width=3,
                  command=lambda: self.history_tree_refresh(),
                  bootstyle="outline").pack(side=RIGHT, padx=2)
        
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
        self.status = ttk.Label(status, text="🐳 就绪", bootstyle="secondary")
        self.status.pack(side=LEFT)
        ttk.Label(status, text="transformed Desktop v1.2 · 深海女仆工坊",
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
            "将 WebP 图片批量转换为 JPEG 格式",
            lambda: self._pick("webp", [("WebP", "*.webp")]),
            lambda: self._convert("webp"))
        
        # --- Tab 2: 网络下载 ---
        tab2 = ttk.Frame(nb, padding=15)
        nb.add(tab2, text="🌐 网络下载")

        # ---- 歌曲搜索下载 ----
        song_box = ttk.Labelframe(tab2, text="🎵 歌曲搜索下载（MP3）", padding=12)
        song_box.pack(fill=X, pady=(0, 10))

        ttk.Label(song_box, text="输入歌手 / 歌名，自动搜索下载 MP3",
                 font=("", 10), bootstyle="secondary").pack(anchor=W)

        song_frame = ttk.Frame(song_box)
        song_frame.pack(fill=X, pady=5)

        self.song_var = tk.StringVar()
        song_entry = ttk.Entry(song_frame, textvariable=self.song_var,
                             font=("", 11))
        song_entry.pack(fill=X, side=LEFT, expand=True)
        song_entry.bind("<Return>", lambda e: self._start_song_search())

        ttk.Button(song_frame, text="🔍 搜索下载",
                  bootstyle="warning", command=self._start_song_search).pack(side=RIGHT, padx=5)

        ttk.Label(song_box, text="搜索来源: B站优先（国内直连），暂无则手机外站兜底。",
                 font=("", 9), bootstyle="secondary").pack(anchor=W)

        # ---- 视频链接批量下载 ----
        url_box = ttk.Labelframe(tab2, text="🎬 视频链接下载（支持批量）", padding=12)
        url_box.pack(fill=X, pady=(0, 8))

        ttk.Label(url_box, text="每行一个链接，支持 B站/BV号/AV号/b23短链/YouTube/X/直链",
                 font=("", 9), bootstyle="secondary").pack(anchor=W, pady=(0, 4))

        # 多行文本输入框
        self.url_text = tk.Text(url_box, height=4, font=("", 10),
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

        self.dl_type = tk.StringVar(value="mp4")
        ttk.Radiobutton(btn_row, text="🎬 MP4", variable=self.dl_type,
                       value="mp4", bootstyle="success").pack(side=LEFT, padx=2)
        ttk.Radiobutton(btn_row, text="🎵 MP3", variable=self.dl_type,
                       value="mp3", bootstyle="warning").pack(side=LEFT, padx=2)

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
        q_cols = ("idx", "status", "name", "progress", "action")
        self.queue_tree = ttk.Treeview(queue_box, columns=q_cols, show="headings",
                                       height=8, bootstyle="info", selectmode="extended")
        self.queue_tree.heading("idx", text="#")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.heading("name", text="文件名 / URL")
        self.queue_tree.heading("progress", text="进度")
        self.queue_tree.heading("action", text="操作")
        self.queue_tree.column("idx", width=40, anchor=CENTER, stretch=False)
        self.queue_tree.column("status", width=80, anchor=CENTER, stretch=False)
        self.queue_tree.column("name", width=280)
        self.queue_tree.column("progress", width=70, anchor=CENTER, stretch=False)
        self.queue_tree.column("action", width=60, anchor=CENTER, stretch=False)
        self.queue_tree.tag_configure("waiting", foreground="#8899aa")
        self.queue_tree.tag_configure("downloading", foreground="#00ccff")
        self.queue_tree.tag_configure("done", foreground="#44cc44")
        self.queue_tree.tag_configure("failed", foreground="#ff5555")
        self.queue_tree.tag_configure("retrying", foreground="#ffaa00")
        q_scroll = ttk.Scrollbar(queue_box, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=q_scroll.set)
        self.queue_tree.pack(side=LEFT, fill=BOTH, expand=True)
        q_scroll.pack(side=RIGHT, fill=Y)
        # 键盘 Delete 删除
        self.queue_tree.bind("<Delete>", lambda e: self._queue_delete_selected())
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

        self.dl_total_label = ttk.Label(prog_box, text="总进度: 0/0", font=("", 9))
        self.dl_total_label.pack(anchor=W)
        self.dl_total_prog = ttk.Progressbar(prog_box, mode="determinate", bootstyle="success")
        self.dl_total_prog.pack(fill=X, pady=2)

        ttk.Label(prog_box, text="当前:", font=("", 9)).pack(anchor=W, pady=(4, 0))
        self.dl_prog = ttk.Progressbar(prog_box, mode="determinate", bootstyle="info")
        self.dl_prog.pack(fill=X, pady=2)
        self.dl_stat = ttk.Label(prog_box, text="")
        self.dl_stat.pack(anchor=W)

        # 支持列表
        info = ttk.Frame(tab2, padding=(6, 6, 6, 0))
        info.pack(fill=X, pady=(4, 0))
        ttk.Label(info, text="✅ 支持的平台",
                 font=("", 11, "bold")).pack(anchor=W)
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
        """创建转换卡片"""
        icons = {"epub": "📖", "mp4": "🎬", "webp": "🖼️"}
        tip = {"epub": "电子书转纯文本", "mp4": "提取视频音频", "webp": "图片转 JPEG"}
        
        card = ttk.Frame(parent, padding=12, bootstyle="secondary")
        card.pack(fill=X, pady=7)
        
        # 标题行
        hdr = ttk.Frame(card)
        hdr.pack(fill=X)
        ttk.Label(hdr, text=f"{icons.get(key, '📁')} {title}", font=("", 14, "bold"),
                 bootstyle="inverse-primary").pack(side=LEFT, padx=(2, 8))
        ttk.Label(hdr, text=tip.get(key, ""), font=("", 9),
                 bootstyle="secondary").pack(side=LEFT, pady=(4, 0))
        
        self.convert_cards[key] = {
            "files": [],
            "label": ttk.Label(hdr, text="未选择文件", bootstyle="secondary"),
            "progress": ttk.Progressbar(card, mode="determinate", bootstyle="success"),
            "status": ttk.Label(card, text=""),
            "pick_fn": pick_fn,
            "conv_fn": conv_fn,
        }
        
        self.convert_cards[key]["label"].pack(side=RIGHT, padx=10)
        
        ttk.Label(card, text=desc, bootstyle="secondary").pack(anchor=W, pady=2)
        
        btn_frame = ttk.Frame(card)
        btn_frame.pack(fill=X, pady=5)
        
        ttk.Button(btn_frame, text="📂 选择文件",
                  command=pick_fn, bootstyle="primary-outline").pack(side=LEFT, padx=2)
        ttk.Button(btn_frame, text="▶ 开始转换",
                  command=conv_fn, bootstyle="success").pack(side=LEFT, padx=2)
        
        self.convert_cards[key]["progress"].pack(fill=X, pady=4)
        self.convert_cards[key]["status"].pack(anchor=W)
    
    # ---- 右侧历史 ----
    def _build_right(self, parent):
        ttk.Label(parent, text="📜 转换记录", font=("", 14, "bold"),
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
        
        # 底部按钮
        btm = ttk.Frame(parent)
        btm.pack(fill=X, pady=5)
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
            self.status.config(text=f"输出目录: {d}")
    
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
                    self.after(0, lambda n=Path(f).name, i=i, rt=reason_text: (
                        ct["status"].config(text=f"[{i+1}/{total}] {n}: {rt}，跳过"),
                        self.update()))
                    self.history.add(Path(f).name, typ_name, True, "skipped:" + skip_reason)
                    continue
                
                def mk_cb(i, f):
                    def cb(pct, msg):
                        overall = (i / total) + (pct / total)
                        # 线程安全：用 after 调度回主线程更新 UI
                        self.after(0, lambda p=overall, n=i, fn=Path(f).name, m=msg, t=typ_name: (
                            ct["progress"].config(value=min(p * 100, 100)),
                            ct["status"].config(text=f"[{n+1}/{total}] {fn}: {m}"),
                            self.dl_prog.config(value=min(p * 100, 100)),
                            self.dl_stat.config(text=f"{t}: [{n+1}/{total}]"),
                            self.update()))
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
                self.after(0, lambda u=ok, n=Path(f).name: self.status.config(
                    text=f"{'完成' if u else '失败'}: {n}"))
        finally:
            # 确保无论成功/异常都重置状态，防止卡死（UI 操作调度回主线程）
            self.task_running = False
            self.after(0, lambda k=ct: (
                k["label"].config(text="完成 ✓"),
                k["progress"].config(value=0),
                self.dl_prog.config(value=0),
                self.history_tree_refresh(),
                self._log_refresh(),
                self.update()))
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
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n\n".join(texts))
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)
    
    def _conv_mp4(self, path, out_dir, cb):
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            return False, "未找到 ffmpeg，请重新启动程序并选择自动下载"
        try:
            cb(0.2, "提取音频...")
            name = Path(path).stem
            out = Path(out_dir) / f"{name}.mp3"
            cmd = [ffmpeg, "-i", str(path), "-vn",
                   "-acodec", "libmp3lame", "-ab", "192k",
                   "-y", str(out)]
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")[-300:]
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
        """智能处理输入：支持裸 BV/AV 号、b23短链、完整链接、混合文本"""
        url = url.strip()
        if not url:
            return url

        # 1. 从混合文本中提取 URL（用户可能粘贴带说明的文字）
        url_match = re.search(r'(https?://[^\s<>"\'\]]+)', url, re.IGNORECASE)
        if url_match:
            url = url_match.group(1).rstrip('，。！？、,.;!?')
            return url

        # 2. Bilibili BV号 (BV 后12位字母数字)，从任意位置提取
        m = re.search(r'(BV[0-9A-Za-z]{10})', url)
        if m:
            return f"https://www.bilibili.com/video/{m.group(1)}"
        # 3. AV号
        m = re.search(r'(av\d+)', url, re.IGNORECASE)
        if m:
            return f"https://www.bilibili.com/video/{m.group(1)}"
        # 4. b23.tv 短链（分享常用）
        m = re.match(r'(b23\.tv/[0-9A-Za-z]+)', url, re.IGNORECASE)
        if m:
            return f"https://{m.group(1)}"
        # 5. 无协议完整域名
        if "." in url and re.search(r'\.[a-zA-Z]{2,}(/|$)', url):
            return "https://" + url
        # 6. 其他原样返回
        return url

    # ========== 下载队列相关 ==========
    _STATUS_ICONS = {
        "waiting": "○", "downloading": "▶", "done": "✓",
        "failed": "✗", "retrying": "↻",
    }

    def _on_url_text_focus_in(self, event=None):
        """文本框获得焦点时，若为占位符则清空"""
        if self._url_placeholder_active:
            self.url_text.delete("1.0", tk.END)
            self.url_text.config(fg="#e0e0e0")
            self._url_placeholder_active = False

    def _on_url_text_focus_out(self, event=None):
        """文本框失去焦点时，若为空则恢复占位符"""
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
        """从多行文本框提取 URL 列表（自动跳过占位符文字）"""
        # 如果当前显示的是占位符，直接返回空
        if self._url_placeholder_active:
            return []
        self._set_url_placeholder(False)
        raw = self.url_text.get("1.0", tk.END).strip()
        if not raw:
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
        """将文本框中的链接添加到下载队列"""
        urls = self._get_urls_from_text()
        if not urls:
            self.show_toast("提示", "请输入至少一个视频链接", "warning")
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
        self.status.config(text=f"已添加 {added} 个链接到队列")
        self.show_toast("已添加", f"已将 {added} 个链接加入下载队列", "info")
        # 清空输入框
        self.url_text.delete("1.0", tk.END)
        self._set_url_placeholder(True)
        # 自动启动队列 worker
        self._start_queue_worker()

    def _start_queue(self):
        """手动点击开始下载"""
        self._start_queue_worker()

    def _start_queue_worker(self):
        """启动队列消费线程（如果尚未运行）"""
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
                self.dl_queue_worker_running = False
                self.after(0, lambda: self.status.config(text="队列下载完成"))
                return
            item["status"] = "downloading"
            self.dl_current_item = item
            self.after(0, self._queue_refresh_tree)
            self.after(0, lambda n=item["name"][:40]:
                       self.status.config(text=f"正在下载: {n}"))
            try:
                self._do_dl_item(item)
            except Exception as e:
                Logger.log(f"❌ 队列项异常: {e}")
                item["status"] = "failed"
                item["error"] = str(e)
            self.dl_current_item = None
            self.after(0, self._queue_refresh_tree)

    def _do_dl_item(self, item):
        """下载单个队列项（在后台线程中执行）"""
        url = item["url"]
        is_mp3 = item["is_mp3"]
        # 单调递增的显示进度(0~1)
        self._dl_pct = 0.0

        if not HAS_YTDLP:
            item["status"] = "failed"
            item["error"] = "请安装 yt-dlp"
            self.after(0, lambda: self.show_toast("缺少依赖", "请安装 yt-dlp:\npip install yt-dlp", "error", _from_thread=True))
            return

        def cb(pct, msg):
            pct = max(pct, 0.05)
            self._dl_pct = max(self._dl_pct, pct)
            item["progress"] = f"{self._dl_pct*100:.1f}%"
            self.after(0, lambda p=self._dl_pct, m=msg: (
                self.dl_prog.stop(),
                self.dl_prog.config(value=p * 100, mode="determinate"),
                self.dl_stat.config(text=m),
                self._queue_refresh_tree(),
                self.update_idletasks()))

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
                self.after(0, lambda r=reason: (
                    self.dl_prog.config(value=0),
                    self.show_toast("需要代理",
                        f"该视频在 YouTube/X，当前网络无法直接访问。\n\n{r}\n\n"
                        f"建议: 开启代理/VPN 后重试。\nB站等国内视频不受影响，可正常下载。",
                        "warning", _from_thread=True)))
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
                    self.after(0, lambda p=pct_show, s=speed, e=eta: (
                        self.dl_prog.stop(),
                        self.dl_prog.config(value=min(p, 100), mode="determinate"),
                        self.dl_stat.config(
                            text=f"下载中 {p:.1f}%  {self._fmt_speed(s)}  ETA {e}s" if s else
                                 f"下载中... {p:.1f}%"),
                        self._queue_refresh_tree(),
                        self.update()))
                else:
                    self.after(0, lambda s=speed: (
                        self.dl_prog.config(mode="indeterminate"),
                        self.dl_prog.start(12),
                        self.dl_stat.config(text=f"下载中... {self._fmt_speed(s)}"),
                        self.update()))
            elif status == 'finished':
                self.after(0, lambda: (
                    self.dl_prog.stop(),
                    self.dl_prog.config(mode="determinate", value=95),
                    self.dl_stat.config(text="95% 合并/转码中..."),
                    self.update()))

        try:
            opts = {
                "outtmpl": str(Path(self.output_dir) / "%(title)s.%(ext)s"),
                "quiet": True, "no_warnings": True,
                "progress_hooks": [progress_hook],
                "noprogress": True,
                "retries": 5,
                "fragment_retries": 5,
                "socket_timeout": 30,
                "concurrent_fragment_downloads": 4,
                "continue": True,
                "skip_unavailable_fragments": True,
                "fragment_retries_base": 2,
                "windowsfilenames": True,
                "noplaylist": True,
            }
            if "bilibili" in ready_url or ready_url.startswith("BV") or ready_url.startswith("av"):
                opts.update({
                    "referer": "https://www.bilibili.com/",
                    "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win6; x64) AppleWebKit/537.36"},
                    "nocheckcertificate": False,
                })
            ffmpeg_bin = get_ffmpeg_path()
            if ffmpeg_bin:
                opts["ffmpeg_location"] = str(Path(ffmpeg_bin).parent)

            if "bilibili.com" in ready_url or ready_url.startswith("BV") or ready_url.startswith("av"):
                if is_mp3:
                    opts["format"] = "ba/b"
                    opts.update({
                        "postprocessors": [{
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }],
                    })
                else:
                    opts["format"] = "bv*+ba/b"
            else:
                if is_mp3:
                    opts.update({
                        "format": "bestaudio/best",
                        "postprocessors": [{
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }],
                    })
                else:
                    opts["format"] = "bv*+ba/best"

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
            Logger.log(f"✅ 下载成功: {name}")
            self.after(0, lambda n=name: self.status.config(text=f"下载成功: {n}"))
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
            self.after(0, lambda: (
                self.status.config(text=f"下载失败: {item['name'][:30]}"),
                self.show_toast("下载失败", err[:300] + hint, "error", _from_thread=True),
                self.dl_prog.stop(),
                self.dl_prog.config(value=0, mode="determinate")))
        finally:
            self.after(0, lambda: (
                self.dl_prog.stop(),
                self.dl_prog.config(mode="determinate"),
                self._queue_refresh_tree(),
                self.history_tree_refresh(),
                self._log_refresh(),
                self.update()))
    
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
                self.after(0, lambda r=results: self._show_song_results(q, r))
                return
            # 3. B 站无结果 → ytsearch 兜底（直接加入队列）
            url = f"ytsearch:{q}"
            with self.dl_queue_lock:
                self.dl_queue.append({
                    "url": url, "is_mp3": True,
                    "status": "waiting", "name": f"🎵 {q}", "error": "",
                    "progress": "",
                })
            self.after(0, lambda: (
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
                  font=("", 11, "bold"), bootstyle="info").pack(padx=12, pady=(12, 6), anchor=W)
        ttk.Label(dlg, text="点击选中后自动加入下载队列",
                  font=("", 9), bootstyle="secondary").pack(padx=12, anchor=W)

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
            self.after(0, lambda: (
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
        """刷新队列 Treeview + 总进度"""
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        with self.dl_queue_lock:
            total = len(self.dl_queue)
            done_count = sum(1 for it in self.dl_queue if it["status"] == "done")
            failed_count = sum(1 for it in self.dl_queue if it["status"] == "failed")
            for i, it in enumerate(self.dl_queue):
                icon = self._STATUS_ICONS.get(it["status"], "?")
                status_text = f"{icon} {it['status']}"
                name_text = it["name"][:50] if it["name"] else it["url"][:50]
                progress_text = it.get("progress", "")
                if it["status"] == "done":
                    progress_text = "✓"
                elif it["status"] == "failed":
                    progress_text = "✗"
                self.queue_tree.insert("", END, iid=str(i),
                                       tags=(it["status"],),
                                       values=(i + 1, status_text, name_text, progress_text, ""))
        self.after(0, lambda d=done_count, t=total, f=failed_count: (
            self.dl_total_label.config(text=f"总进度: {d}/{t}  ✗ {f}"),
            self.dl_total_prog.config(value=(d / max(t, 1)) * 100),
            self.update()))

    def _show_queue_menu(self, event):
        iid = self.queue_tree.identify_row(event.y)
        if iid and iid not in self.queue_tree.selection():
            self.queue_tree.selection_set(iid)
        self._queue_menu.tk_popup(event.x_root, event.y_root)

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


    def history_tree_refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        tag = self.filter_var.get()
        items = self.history.items
        # 从新到旧插入；iid 绑定原始索引，供"删除选中"精准定位
        row = 0
        for idx in range(len(items) - 1, -1, -1):
            h = items[idx]
            if tag != "全部" and tag not in h["type"]:
                continue
            s = "✓" if h["ok"] else "✗"
            self.tree.insert("", END, iid=str(idx),
                             tags=("even" if row % 2 == 0 else "odd",),
                             values=(h["time"], h["name"][:25], h["type"], s))
            row += 1
    
    def _history_delete_selected(self):
        """删除勾选的记录（支持多选）"""
        sel = self.tree.selection()
        if not sel:
            self.show_toast("提示", "请先勾选要删除的记录", "warning")
            return
        if not messagebox.askyesno("确认", f"确定删除选中的 {len(sel)} 条记录？"):
            return
        # iid 即 history.items 的原始索引；倒序删除避免索引位移
        for iid in sorted(sel, key=int, reverse=True):
            idx = int(iid)
            if 0 <= idx < len(self.history.items):
                del self.history.items[idx]
        self.history.save()
        self.history_tree_refresh()
        self.status.config(text=f"已删除 {len(sel)} 条记录")
        Logger.log(f"🗑 删除历史记录 {len(sel)} 条")
    
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
                open(LOG_FILE, "w", encoding="utf-8").close()
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
