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
import tkinter.ttk as _std_ttk
from tkinter import filedialog, messagebox
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
from download_options import build_download_options, prepare_url, is_bilibili_url
from ui_helpers import (
    UiProgressEventQueue,
    selected_history_ids,
    compute_queue_move,
    is_newer_version,
    parse_drop_list,
)
from net_guard import guarded_urlopen
from app_common import (
    APP_VERSION, UI_FONT, PALETTES, THEME_ALIASES, BASE_THEMES,
    HISTORY_FILE, LOG_FILE, Logger, History, AppSettings,
    _validated_output_file, _LOG_LOCK,
)
import ui_style
from ffmpeg_tools import download_ffmpeg, get_ffmpeg_path, media_duration
from bili_api import (
    check_foreign_access,
    search_bilibili_songs,
    get_buvid3_cached,
    resolve_bilibili_media,
    _bili_cookie_header,
    bili_cookies_exist,
    bili_logout,
    bili_user_id,
    generate_login_qr,
    wait_login_qr,
    BILI_COOKIEFILE,
)
import converters

# ttkbootstrap 的 Button/Radiobutton/Progressbar 子类会把 style 参数当 bootstyle
# 解析并丢弃不认识的关键字（Accent.TButton -> TButton），导致自定义样式失效。
# 这三类控件一律用原生 ttk 版本，样式由 ui_style.apply_palette 统一定义。
Button = _std_ttk.Button
Radiobutton = _std_ttk.Radiobutton
Progressbar = _std_ttk.Progressbar

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

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

try:
    from tkinterdnd2 import DND_FILES, DND_TEXT
    HAS_DND = True
except ImportError:
    DND_FILES = DND_TEXT = None
    HAS_DND = False

# ===== 主应用 =====
def get_asset(name):
    """获取资源文件路径（兼容 PyInstaller 打包后的临时解压目录）"""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    p = base / "assets" / name
    return str(p) if p.exists() else None


class App(ttk.Window):
    def __init__(self):
        self.settings = AppSettings()
        theme = THEME_ALIASES.get(self.settings.get("theme"), self.settings.get("theme"))
        self._theme = theme if theme in PALETTES else "deep"
        super().__init__(title=f"transformed 桌面版 {APP_VERSION}",
                         themename=BASE_THEMES[self._theme])

        self.geometry("1280x800")
        self.minsize(1024, 680)

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
        self.dl_queue = []           # [{uid, url, is_mp3, status, name, error}, ...]
        self.dl_queue_lock = threading.Lock()
        self._uid_seq = 0
        self._active_workers = 0     # 正在运行的下载 worker 数
        self._ui_thread_id = threading.get_ident()
        self._ui_closing = False
        self._url_placeholder_active = True
        self._dl_pcts = {}           # uid -> 单调递增显示进度(0~1)
        try:
            self.max_parallel = max(1, min(3, int(self.settings.get("parallel") or 2)))
        except (TypeError, ValueError):
            self.max_parallel = 2
        self._progress_events = UiProgressEventQueue()

        # 侧边栏看板娘立绘（深海女仆工坊 · 鲸鱼娘 CC BY-NC-SA 4.0）
        self.img_side = self._load_whale("whale_left.webp", 210, 420)
        self._set_window_icon()

        self._build_ui()
        self._apply_theme_colors()
        ui_style.style_titlebar(self, dark=self._theme_colors()["dark"])
        self._setup_dragdrop()
        self._update_bili_btn()
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
    
    # ================= UI 构建 =================

    # ---- 自绘 tk 控件辅助（注册进 _tk_recolor，主题切换时统一重配色） ----
    def _tframe(self, parent, bg="root"):
        f = tk.Frame(parent, bg=self._theme_colors()[bg])
        self._tk_recolor.append((f, ("frame", bg)))
        return f

    def _tlabel(self, parent, text, font, fg="fg", bg="root", **kw):
        lbl = tk.Label(parent, text=text, font=font,
                       bg=self._theme_colors()[bg], fg=self._theme_colors()[fg],
                       anchor=W, **kw)
        self._tk_recolor.append((lbl, ("label", fg, bg)))
        return lbl

    def _card(self, parent):
        """带 1px 描边的卡片容器"""
        pal = self._theme_colors()
        f = tk.Frame(parent, bg=pal["card"],
                     highlightbackground=pal["border"], highlightthickness=1,
                     highlightcolor=pal["accent"])
        self._tk_recolor.append((f, ("frameb", "card")))
        return f

    def _chip(self, parent, glyph, color, size=40, icon=15):
        """Win10 磁贴风彩色图标徽章（固定品牌色，不随主题变化）"""
        c = tk.Frame(parent, width=size, height=size, bg=color)
        c.pack_propagate(False)
        g = tk.Label(c, text=glyph, font=("Segoe MDL2 Assets", icon),
                     bg=color, fg="#ffffff")
        g.place(relx=0.5, rely=0.5, anchor="center")
        return c

    def _page_header(self, parent, title, subtitle=""):
        """页面大标题（Win10 设置页风格）"""
        row = self._tframe(parent, "root")
        row.pack(fill=X, pady=(0, 12))
        self._tlabel(row, title, (UI_FONT, 19, "bold"),
                     fg="fg", bg="root").pack(anchor=W)
        if subtitle:
            self._tlabel(row, subtitle, (UI_FONT, 9),
                         fg="dim", bg="root").pack(anchor=W, pady=(2, 0))
        return row

    def _build_ui(self):
        pal = self._theme_colors()
        self._tk_recolor = []

        # ===== 底部状态栏（先占住底部） =====
        status = self._tframe(self, "side")
        status.pack(fill=X, side=BOTTOM)
        ttk.Separator(status).pack(fill=X)
        srow = self._tframe(status, "side")
        srow.pack(fill=X, padx=16, pady=5)
        self.status = ttk.Label(srow, text="就绪", style="SideDim.TLabel")
        self.status.pack(side=LEFT)
        ttk.Label(srow, text=f"transformed Desktop {APP_VERSION} · 深海女仆工坊",
                  style="SideFaint.TLabel").pack(side=RIGHT)

        # ===== 主体：侧边栏 + 页面 =====
        body = self._tframe(self, "root")
        body.pack(fill=BOTH, expand=True)

        side = self._tframe(body, "side")
        side.pack(side=LEFT, fill=Y)
        side.configure(width=228)
        side.pack_propagate(False)

        # 侧栏与内容之间的 1px 分隔线（Win10 NavigationView 样式）
        sep = tk.Frame(body, width=1, bg=pal["border"])
        sep.pack(side=LEFT, fill=Y)
        self._tk_recolor.append((sep, ("frame", "border")))

        # logo
        logo = self._tframe(side, "side")
        logo.pack(fill=X, padx=22, pady=(22, 8))
        self._tlabel(logo, "transformed", (UI_FONT, 15, "bold"),
                     fg="fg", bg="side").pack(anchor=W)
        self._tlabel(logo, f"深海女仆工坊 · {APP_VERSION}", (UI_FONT, 8),
                     fg="faint", bg="side").pack(anchor=W, pady=(2, 0))

        # 导航（Win10 NavigationView：选中项左侧 3px 强调条，MDL2 图标）
        self._page = "convert"
        self._nav_rows = {}
        for value, glyph, text in (
            ("convert", "\uE8AB", "格式转换"),
            ("download", "\uE896", "视频下载"),
            ("history", "\uE81C", "历史记录"),
            ("log", "\uE8FD", "运行日志"),
        ):
            row = tk.Frame(side, bg=pal["side"], cursor="hand2")
            row.pack(fill=X)
            pill = tk.Frame(row, width=3, bg=pal["accent"])
            icon = tk.Label(row, text=glyph, font=("Segoe MDL2 Assets", 10),
                            bg=pal["side"], fg=pal["dim"])
            label = tk.Label(row, text=text, font=(UI_FONT, 10),
                             bg=pal["side"], fg=pal["fg"])
            icon.pack(side=LEFT, padx=(20, 10), pady=9)
            label.pack(side=LEFT)
            for w in (row, icon, label):
                w.bind("<Button-1>", lambda e, v=value: self._switch_page(v))
                w.bind("<Enter>", lambda e, v=value: self._update_nav(hover=v))
                w.bind("<Leave>", lambda e: self._update_nav())
            self._nav_rows[value] = (row, pill, icon, label)
        self._update_nav()

        # 侧栏底部控制
        foot = self._tframe(side, "side")
        foot.pack(side=BOTTOM, fill=X, padx=14, pady=14)
        self.theme_btn = Button(foot, text=PALETTES[self._theme]["btn_other"],
                                    style="SideGhost.Small.TButton",
                                    command=self._toggle_theme)
        self.theme_btn.pack(side=LEFT)
        Button(foot, text="输出目录", style="SideGhost.Small.TButton",
                   command=self._set_output).pack(side=RIGHT)

        # 看板娘（底部对齐，位于导航与底部控制之间）
        if self.img_side:
            wlbl = tk.Label(side, image=self.img_side, bg=pal["side"])
            wlbl.pack(side=BOTTOM, fill=X)
            self._tk_recolor.append((wlbl, ("label", "side", "side")))

        # 页面容器
        wrap = self._tframe(body, "root")
        wrap.pack(side=LEFT, fill=BOTH, expand=True)
        self._pages = {}
        for name, builder in (("convert", self._page_convert),
                              ("download", self._page_download),
                              ("history", self._page_history),
                              ("log", self._page_log)):
            page = ttk.Frame(wrap, style="TFrame", padding=(22, 18, 22, 12))
            page.grid(row=0, column=0, sticky="nsew")
            builder(page)
            self._pages[name] = page
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self._switch_page("convert")

    def _switch_page(self, name):
        if name not in self._pages:
            return
        self._page = name
        self._pages[name].tkraise()
        self._update_nav()

    def _update_nav(self, hover=None):
        """按当前页 + 悬停项重刷导航行配色（Win10 NavigationView 语义）"""
        pal = self._theme_colors()
        for v, (row, pill, icon, label) in self._nav_rows.items():
            sel = v == self._page
            if sel:
                bg = pal["nav_sel"]
            elif v == hover:
                bg = pal["card2"]
            else:
                bg = pal["side"]
            row.config(bg=bg)
            icon.config(bg=bg, fg=pal["accent"] if sel else pal["dim"])
            label.config(bg=bg, fg=pal["fg"])
            pill.config(bg=pal["accent"])
            if sel:
                pill.pack(side=LEFT, fill=Y)
            else:
                pill.pack_forget()

    # ---- 页面：格式转换 ----
    def _page_convert(self, parent):
        self._page_header(parent, "格式转换",
                          "选择文件或直接拖进窗口，批量转换为常见格式")

        grid = ttk.Frame(parent, style="TFrame")
        grid.pack(fill=BOTH, expand=True)
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1, uniform="conv")
        grid.grid_rowconfigure(1, weight=1)

        chips = self._theme_colors()["chips"]
        self._make_converter_card(grid, 0, "EPUB → TXT", "epub", "\uE838", chips[0],
            "选择 EPUB 电子书，批量转换为纯文本",
            ".epub  →  .txt",
            lambda: self._pick("epub", [("EPUB", "*.epub")]),
            lambda: self._convert("epub"))

        self._make_converter_card(grid, 1, "MP4 → MP3", "mp4", "\uE8F1", chips[1],
            "提取视频中的音频轨道，保存为 MP3",
            ".mp4 .mkv .avi .mov .webm .flv .ts  →  .mp3",
            lambda: self._pick("mp4", [("视频文件", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.ts")]),
            lambda: self._convert("mp4"))

        self._make_converter_card(grid, 2, "WebP → JPG", "webp", "\uE9D9", chips[2],
            "将 WebP 图片批量转换为 JPEG",
            ".webp .png .jpg .gif .bmp .tiff  →  .jpg",
            lambda: self._pick("webp", [("图片", "*.webp *.png *.jpg *.jpeg *.gif *.bmp *.tiff")]),
            lambda: self._convert("webp"))

        # 底部输出目录横幅（同时填满页面留白）
        banner = self._card(parent)
        banner.pack(fill=X, side=BOTTOM, pady=(12, 0))
        b = self._tframe(banner, "card")
        b.pack(fill=X, padx=16, pady=12)
        self._chip(b, "\uE838", chips[0], size=32, icon=12).pack(side=LEFT, padx=(0, 12))
        brow = self._tframe(b, "card")
        brow.pack(fill=X, side=LEFT, expand=True)
        self._tlabel(brow, "输出目录", (UI_FONT, 10, "bold"),
                     fg="fg", bg="card").pack(anchor=W)
        self._output_path_lbl = self._tlabel(brow, self.output_dir, (UI_FONT, 8),
                                             fg="dim", bg="card")
        self._output_path_lbl.pack(anchor=W, pady=(2, 0))
        self._tlabel(brow, "支持把文件直接拖进窗口，按扩展名自动归类到对应卡片",
                     (UI_FONT, 8), fg="faint", bg="card").pack(anchor=W, pady=(2, 0))
        Button(b, text="打开文件夹", style="Accent.Small.TButton",
               command=self._open_output_folder).pack(side=RIGHT, padx=(8, 0))
        Button(b, text="更改目录", style="Ghost.Small.TButton",
               command=self._set_output).pack(side=RIGHT)

    # ---- 页面：视频下载 ----
    def _page_download(self, parent):
        pal = self._theme_colors()

        # --- 歌曲搜索 ---
        song_card = self._card(parent)
        song_card.pack(fill=X, pady=(0, 12))
        s = self._tframe(song_card, "card")
        s.pack(fill=X, padx=16, pady=12)
        srow = self._tframe(s, "card")
        srow.pack(fill=X)
        self._tlabel(srow, "歌曲搜索下载", (UI_FONT, 10, "bold"),
                     fg="fg", bg="card").pack(side=LEFT)
        self._tlabel(srow, "B站优先（国内直连）· 无结果自动用 YouTube 搜索兜底",
                     (UI_FONT, 8), fg="faint", bg="card").pack(side=RIGHT)
        srow2 = self._tframe(s, "card")
        srow2.pack(fill=X, pady=(10, 0))
        self.song_var = tk.StringVar()
        song_entry = ttk.Entry(srow2, textvariable=self.song_var)
        song_entry.pack(fill=X, side=LEFT, expand=True)
        song_entry.bind("<Return>", lambda e: self._start_song_search())
        Button(srow2, text="搜索下载", style="Accent.TButton",
                   command=self._start_song_search).pack(side=RIGHT, padx=(10, 0))

        # --- 视频链接下载 ---
        url_card = self._card(parent)
        url_card.pack(fill=X, pady=(0, 12))
        u = self._tframe(url_card, "card")
        u.pack(fill=X, padx=16, pady=12)
        urow = self._tframe(u, "card")
        urow.pack(fill=X)
        self._tlabel(urow, "视频链接下载", (UI_FONT, 10, "bold"),
                     fg="fg", bg="card").pack(side=LEFT)
        self.bili_btn = Button(urow, text="B站登录", style="Tonal.Small.TButton",
                                   command=self._bili_login, width=11)
        self.bili_btn.pack(side=RIGHT)

        self.url_text = tk.Text(u, height=4, font=(UI_FONT, 10), wrap=tk.WORD,
                                relief=tk.FLAT, borderwidth=0, padx=10, pady=8,
                                highlightthickness=1,
                                highlightbackground=pal["border"],
                                highlightcolor=pal["accent"])
        self.url_text.pack(fill=X, pady=(10, 4))
        self._url_placeholder = ("粘贴链接到此处，每行一个...\n例如:\n"
                                 "https://www.bilibili.com/video/BV...\n"
                                 "youtube.com/watch?v=...")
        self._set_url_placeholder(True)
        self.url_text.bind("<FocusIn>", self._on_url_text_focus_in)
        self.url_text.bind("<FocusOut>", self._on_url_text_focus_out)
        self._tk_recolor.append((self.url_text, ("input_text",)))
        self._tlabel(u, "每行一个链接 · 支持 B站/BV号/AV号/b23短链/YouTube/X/直链 · 可拖入窗口",
                     (UI_FONT, 8), fg="faint", bg="card").pack(anchor=W)

        brow = self._tframe(u, "card")
        brow.pack(fill=X, pady=(10, 0))
        saved_type = self.settings.get("dl_type")
        self.dl_type = tk.StringVar(value=saved_type if saved_type in ("mp4", "mp3") else "mp4")
        # 任何方式改变格式都持久化（点击/键盘/程序赋值）
        self.dl_type.trace_add("write", lambda *_: self.settings.set("dl_type", self.dl_type.get()))
        Radiobutton(brow, text="MP4 视频", variable=self.dl_type, value="mp4",
                        style="Chip.TRadiobutton").pack(side=LEFT)
        Radiobutton(brow, text="MP3 音频", variable=self.dl_type, value="mp3",
                        style="Chip.TRadiobutton").pack(side=LEFT, padx=(6, 12))
        Button(brow, text="粘贴", style="Ghost.Small.TButton",
                   command=self._paste_from_clipboard).pack(side=LEFT)

        Button(brow, text="打开文件夹", style="Ghost.Small.TButton",
                   command=self._open_output_folder).pack(side=RIGHT, padx=(8, 0))
        Button(brow, text="添加到队列", style="Tonal.Small.TButton",
                   command=self._start_dl).pack(side=RIGHT, padx=(8, 0))
        Button(brow, text="开始下载", style="Accent.Small.TButton",
                   command=self._start_queue).pack(side=RIGHT)

        # --- 下载队列 ---
        # 进度卡先占住底部、队列吃剩余空间：窗口较矮时被裁的是队列而不是进度条
        p_card = self._card(parent)
        p_card.pack(fill=X, side=BOTTOM)
        p = self._tframe(p_card, "card")
        p.pack(fill=X, padx=16, pady=12)
        prow = self._tframe(p, "card")
        prow.pack(fill=X)
        self.dl_total_label = ttk.Label(prow, text="总进度: 0/0", style="CardDim.TLabel")
        self.dl_total_label.pack(side=LEFT, padx=(0, 12))
        self.dl_total_prog = Progressbar(prow, mode="determinate",
                                         style="Ok.Horizontal.TProgressbar")
        self.dl_total_prog.pack(side=LEFT, fill=X, expand=True)
        prow2 = self._tframe(p, "card")
        prow2.pack(fill=X, pady=(8, 0))
        self.dl_stat = ttk.Label(prow2, text="", style="CardDim.TLabel")
        self.dl_stat.pack(side=LEFT, padx=(0, 12))
        self.dl_prog = Progressbar(prow2, mode="determinate",
                                   style="Horizontal.TProgressbar")
        self.dl_prog.pack(side=LEFT, fill=X, expand=True)

        q_card = self._card(parent)
        q_card.pack(fill=BOTH, expand=True, pady=(0, 12))
        q = self._tframe(q_card, "card")
        q.pack(fill=BOTH, expand=True, padx=16, pady=12)
        qrow = self._tframe(q, "card")
        qrow.pack(fill=X)
        self._tlabel(qrow, "下载队列", (UI_FONT, 10, "bold"),
                     fg="fg", bg="card").pack(side=LEFT)
        self._tlabel(qrow, "双击失败项查看错误 · 双击完成项打开文件 · Delete 删除",
                     (UI_FONT, 8), fg="faint", bg="card").pack(side=RIGHT, padx=8)

        q_cols = ("idx", "status", "name", "progress")
        self.queue_tree = ttk.Treeview(q, columns=q_cols, show="headings",
                                       height=5, selectmode="extended")
        self.queue_tree.heading("idx", text="#")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.heading("name", text="文件名 / URL")
        self.queue_tree.heading("progress", text="进度")
        self.queue_tree.column("idx", width=40, anchor=CENTER, stretch=False)
        self.queue_tree.column("status", width=96, anchor=CENTER, stretch=False)
        self.queue_tree.column("name", width=320)
        self.queue_tree.column("progress", width=90, anchor=CENTER, stretch=False)
        q_scroll = ttk.Scrollbar(q, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=q_scroll.set)
        self.queue_tree.pack(side=LEFT, fill=BOTH, expand=True, pady=(10, 0))
        q_scroll.pack(side=RIGHT, fill=Y, pady=(10, 0))
        # 键盘 Delete 删除；双击失败行看错误详情，双击完成行直接打开文件
        self.queue_tree.bind("<Delete>", lambda e: self._queue_delete_selected())
        self.queue_tree.bind("<Double-1>", self._on_queue_double_click)
        # 右键菜单
        self._queue_menu = tk.Menu(self, tearoff=0)
        self._queue_menu.add_command(label="开始下载", command=self._start_queue)
        self._queue_menu.add_separator()
        self._queue_menu.add_command(label="重试选中", command=self._queue_retry_selected)
        self._queue_menu.add_command(label="上移", command=lambda: self._queue_move(-1))
        self._queue_menu.add_command(label="下移", command=lambda: self._queue_move(1))
        self._queue_menu.add_separator()
        self._queue_menu.add_command(label="删除选中", command=self._queue_delete_selected)
        self.queue_tree.bind("<Button-3>", self._show_queue_menu)  # 右键
        self._tk_recolor.append((self._queue_menu, ("menu",)))

        q_btns = self._tframe(q, "card")
        q_btns.pack(fill=X, pady=(8, 0))
        Button(q_btns, text="上移", style="Ghost.Small.TButton",
                   command=lambda: self._queue_move(-1)).pack(side=LEFT, padx=(0, 4))
        Button(q_btns, text="下移", style="Ghost.Small.TButton",
                   command=lambda: self._queue_move(1)).pack(side=LEFT, padx=4)
        Button(q_btns, text="重试选中", style="Ghost.Small.TButton",
                   command=self._queue_retry_selected).pack(side=LEFT, padx=4)
        Button(q_btns, text="删除选中", style="Ghost.Small.TButton",
                   command=self._queue_delete_selected).pack(side=LEFT, padx=4)
        ttk.Label(q_btns, text="并发", style="CardDim.TLabel").pack(side=RIGHT, padx=(10, 4))
        self.parallel_var = tk.StringVar(value=str(self.max_parallel))
        parallel_box = ttk.Combobox(q_btns, textvariable=self.parallel_var,
                                    values=("1", "2", "3"), width=3, state="readonly")
        parallel_box.pack(side=RIGHT)
        parallel_box.bind("<<ComboboxSelected>>", self._on_parallel_change)
        Button(q_btns, text="清空队列", style="Danger.Small.TButton",
                   command=self._queue_clear).pack(side=RIGHT, padx=(16, 10))


    # ---- 页面：历史记录 ----
    def _page_history(self, parent):
        self._page_header(parent, "历史记录", "双击条目打开对应文件 · Delete 删除选中记录")
        card = self._card(parent)
        card.pack(fill=BOTH, expand=True)
        w = self._tframe(card, "card")
        w.pack(fill=BOTH, expand=True, padx=16, pady=12)

        hrow = self._tframe(w, "card")
        hrow.pack(fill=X, pady=(0, 10))
        self.filter_var = tk.StringVar(value="全部")
        for tag in ["全部", "EPUB", "MP4", "WebP", "下载"]:
            Radiobutton(hrow, text=tag, variable=self.filter_var, value=tag,
                            style="Chip.TRadiobutton",
                            command=self.history_tree_refresh).pack(side=LEFT, padx=(0, 6))
        self._history_count_lbl = ttk.Label(hrow, text="", style="CardDim.TLabel")
        self._history_count_lbl.pack(side=RIGHT)

        cols = ("time", "file", "type", "status")
        self.tree = ttk.Treeview(w, columns=cols, show="headings",
                                 selectmode="extended")
        self.tree.heading("time", text="时间")
        self.tree.heading("file", text="文件")
        self.tree.heading("type", text="类型")
        self.tree.heading("status", text="状态")
        self.tree.column("time", width=100, anchor=CENTER, stretch=False)
        self.tree.column("file", width=200)
        self.tree.column("type", width=80, anchor=CENTER, stretch=False)
        self.tree.column("status", width=50, anchor=CENTER, stretch=False)
        scroll = ttk.Scrollbar(w, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)
        self.tree.bind("<Control-a>", self._history_select_all_visible)
        self.tree.bind("<Control-A>", self._history_select_all_visible)
        self.tree.bind("<Delete>", lambda event: self._history_delete_selected())
        self.tree.bind("<Double-1>", self._on_history_double_click)

        btm = self._tframe(w, "card")
        btm.pack(fill=X, pady=(10, 0))
        Button(btm, text="全选当前", style="Ghost.Small.TButton",
                   command=self._history_select_all_visible).pack(side=LEFT)
        Button(btm, text="清空全部", style="Danger.Small.TButton",
                   command=self._history_clear).pack(side=RIGHT)
        Button(btm, text="删除选中", style="Tonal.Small.TButton",
                   command=self._history_delete_selected).pack(side=RIGHT, padx=(0, 10))

        self.history_tree_refresh()

    # ---- 页面：运行日志 ----
    def _page_log(self, parent):
        pal = self._theme_colors()
        self._page_header(parent, "运行日志", "程序运行记录（最近 200 行，完整日志在 ~/.transformed_log.txt）")
        card = self._card(parent)
        card.pack(fill=BOTH, expand=True)
        w = self._tframe(card, "card")
        w.pack(fill=BOTH, expand=True, padx=16, pady=12)

        lrow = self._tframe(w, "card")
        lrow.pack(fill=X, pady=(0, 10))
        self._tlabel(lrow, "运行日志", (UI_FONT, 10, "bold"),
                     fg="fg", bg="card").pack(side=LEFT)
        Button(lrow, text="清空", style="Danger.Small.TButton",
                   command=self._log_clear).pack(side=RIGHT)
        Button(lrow, text="刷新", style="Ghost.Small.TButton",
                   command=self._log_refresh).pack(side=RIGHT, padx=(0, 8))

        box = self._tframe(w, "input")
        box.configure(highlightthickness=1, highlightbackground=pal["border"],
                      highlightcolor=pal["accent"])
        self._tk_recolor.append((box, ("frameb", "input")))
        box.pack(fill=BOTH, expand=True)
        self.log_text = tk.Text(box, height=15, font=("Consolas", 9), wrap=tk.WORD,
                                relief=tk.FLAT, borderwidth=0, padx=10, pady=8)
        sb = ttk.Scrollbar(box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        self._log_refresh()
    
    def _on_parallel_change(self, event=None):
        """调整并行下载并发数（立即生效：增加时补齐 worker）"""
        try:
            self.max_parallel = max(1, min(3, int(self.parallel_var.get())))
        except ValueError:
            self.max_parallel = 2
        self.settings.set("parallel", self.max_parallel)
        self._ensure_workers()
        self.status.config(text=f"下载并发已设为 {self.max_parallel}")

    def _make_converter_card(self, parent, col, title, key, icon, chip, desc, exts,
                             pick_fn, conv_fn):
        """创建转换卡片（三列网格中的一列，带彩色图标徽章）"""
        card = self._card(parent)
        card.grid(row=0, column=col, sticky="new", padx=5, pady=2)
        inner = self._tframe(card, "card")
        inner.pack(fill=BOTH, expand=True, padx=16, pady=14)

        head = self._tframe(inner, "card")
        head.pack(fill=X)
        self._chip(head, icon, chip).pack(side=LEFT, padx=(0, 10))
        self._tlabel(head, title, (UI_FONT, 12, "bold"),
                     fg="fg", bg="card").pack(side=LEFT, pady=(2, 0))

        self._tlabel(inner, desc, (UI_FONT, 9), fg="dim", bg="card",
                     wraplength=250, justify=LEFT).pack(anchor=W, pady=(10, 2))
        self._tlabel(inner, exts, ("Consolas", 8), fg="faint", bg="card",
                     wraplength=250).pack(anchor=W, pady=(0, 10))

        self.convert_cards[key] = {
            "files": [],
            "label": ttk.Label(inner, text="未选择文件", style="CardDim.TLabel"),
            "progress": Progressbar(inner, mode="determinate",
                                        style="Horizontal.TProgressbar"),
            "status": ttk.Label(inner, text="", style="CardDim.TLabel"),
            "pick_fn": pick_fn,
            "conv_fn": conv_fn,
        }

        btn_frame = self._tframe(inner, "card")
        btn_frame.pack(fill=X, pady=(0, 10))

        Button(btn_frame, text="选择文件", style="Ghost.Small.TButton",
                   command=pick_fn).pack(side=LEFT)
        Button(btn_frame, text="开始转换", style="Accent.Small.TButton",
                   command=conv_fn).pack(side=LEFT, padx=(8, 0))

        self.convert_cards[key]["progress"].pack(fill=X, pady=(0, 4))
        row = self._tframe(inner, "card")
        row.pack(fill=X)
        self.convert_cards[key]["status"].pack(side=LEFT)
        self.convert_cards[key]["label"].pack(side=RIGHT)
    
    # ---- 功能方法 ----
    def _set_output(self):
        d = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir)
        if d:
            self.output_dir = d
            Path(d).mkdir(parents=True, exist_ok=True)
            self.settings.set("output_dir", d)
            if getattr(self, "_output_path_lbl", None):
                try:
                    self._output_path_lbl.config(text=d)
                except tk.TclError:
                    pass
            self.status.config(text=f"输出目录: {d}（已记住）")

    # ---- 主题 ----
    def _theme_colors(self):
        return PALETTES.get(self._theme, PALETTES["deep"])

    def _apply_theme_colors(self):
        """主题切换后：重刷全部 ttk 样式并重配色自绘 tk 控件"""
        pal = self._theme_colors()
        ui_style.apply_palette(self.style, self, pal)
        for entry in getattr(self, "_tk_recolor", []):
            w, spec = entry
            try:
                if spec[0] == "frame":
                    w.config(bg=pal[spec[1]])
                elif spec[0] == "frameb":
                    w.config(bg=pal[spec[1]],
                             highlightbackground=pal["border"],
                             highlightcolor=pal["accent"])
                elif spec[0] == "label":
                    w.config(bg=pal[spec[2]], fg=pal[spec[1]])
                elif spec[0] == "menu":
                    w.config(bg=pal["card"], fg=pal["fg"], borderwidth=0,
                             activebackground=pal["card2"],
                             activeforeground=pal["fg"])
            except tk.TclError:
                pass
        for widget in (self.url_text, self.log_text):
            widget.config(bg=pal["input"], fg=pal["fg"], insertbackground=pal["fg"],
                          highlightbackground=pal["border"],
                          highlightcolor=pal["accent"])
        self.tree.tag_configure("odd", background=pal["zebra2"])
        self.tree.tag_configure("even", background=pal["zebra1"])
        for tag, color in pal["q_tags"].items():
            self.queue_tree.tag_configure(tag, foreground=color)
        if getattr(self, "_url_placeholder_active", False):
            self.url_text.config(fg=pal["ph"])
        self.theme_btn.config(text=pal["btn_other"])
        ui_style.style_titlebar(self, dark=pal["dark"])
        if getattr(self, "_nav_rows", None):
            self._update_nav()

    def _toggle_theme(self):
        new = "day" if self._theme == "deep" else "deep"
        try:
            self.style.theme_use(BASE_THEMES[new])
        except Exception as e:
            Logger.log(f"切换主题失败: {e}")
            return
        self._theme = new
        self.settings.set("theme", new)
        self._apply_theme_colors()
        self.status.config(text=f"主题已切换: {'浅色' if new == 'day' else '深海'}")

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

    # ---- 拖拽导入（可选依赖 tkinterdnd2） ----
    _CONVERT_EXTS = {
        "epub": (".epub",),
        "mp4": (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts"),
        "webp": (".webp", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"),
    }

    def _setup_dragdrop(self):
        """注册拖放：本地文件按扩展名进转换卡片，链接文本进 URL 输入框"""
        if not HAS_DND:
            Logger.log("拖拽支持未启用：未安装 tkinterdnd2（可选依赖）")
            return
        try:
            import tkinterdnd2
            tkinterdnd2.TkinterDnD._require(self)
            self.drop_target_register(DND_FILES, DND_TEXT)
            self.dnd_bind("<<Drop>>", self._on_drop)
            Logger.log("拖拽支持已启用")
        except Exception as e:
            Logger.log(f"注册拖放失败: {e}")

    def _on_drop(self, event):
        # 不用 tk.splitlist：它会把 Windows 路径里的 \a、\t 等当 Tcl 转义符
        try:
            items = parse_drop_list(event.data)
        except Exception:
            items = [str(event.data)]
        files = links = unsupported = 0
        link_lines = []
        for raw in items:
            path = raw.strip("{} ").strip()
            if path and Path(path).is_file():
                ext = Path(path).suffix.lower()
                for key, exts in self._CONVERT_EXTS.items():
                    if ext in exts:
                        card = self.convert_cards[key]
                        card["files"].append(path)
                        card["label"].config(text=f"已选 {len(card['files'])} 个文件")
                        files += 1
                        break
                else:
                    unsupported += 1
            elif path:
                link_lines.append(path)
                links += 1
        if link_lines:
            if self._url_placeholder_active:
                self._on_url_text_focus_in()
            self.url_text.insert(tk.END, "\n".join(link_lines) + "\n")
            self.url_text.see(tk.END)
        if files:
            self._show_tab(0)
            note = f"，跳过 {unsupported} 个不支持的文件" if unsupported else ""
            self.status.config(text=f"已导入 {files} 个文件到转换列表{note}")
        elif links:
            self._show_tab(1)
            self.status.config(text="已从拖拽导入链接")

    def _show_tab(self, index):
        """切换页面；兼容旧索引：0=格式转换 1=视频下载"""
        name = {0: "convert", 1: "download"}.get(index, index)
        if name in self._pages:
            self._switch_page(name)

    # ---- B 站扫码登录 ----
    def _update_bili_btn(self):
        if bili_cookies_exist():
            uid = bili_user_id()
            self.bili_btn.config(text=f"🚪 退出{uid}" if uid else "🚪 退出登录")
        else:
            self.bili_btn.config(text="B站登录")

    def _bili_login(self):
        """已登录 → 询问退出；未登录 → 后台获取二维码并弹出扫码窗口"""
        if bili_cookies_exist():
            if messagebox.askyesno("退出登录", "确定退出 B 站登录？\n将删除本机保存的登录凭据。"):
                bili_logout()
                self._update_bili_btn()
                self.status.config(text="已退出 B 站登录")
            return
        if not HAS_QRCODE:
            self.show_toast("缺少依赖", "扫码登录需要 qrcode 库：\npip install qrcode", "warning")
            return
        self.status.config(text="正在获取 B 站登录二维码...")
        threading.Thread(target=self._bili_login_thread, daemon=True).start()

    def _bili_login_thread(self):
        qrcode_key, qr_url = generate_login_qr()
        if not qrcode_key:
            self._run_on_ui("bili-login", lambda: self.status.config(text="获取二维码失败"))
            self.show_toast("失败", "获取登录二维码失败，请稍后重试", "error", _from_thread=True)
            return
        try:
            img = qrcode.make(qr_url, box_size=6)
        except Exception as e:
            self.show_toast("失败", f"生成二维码失败: {e}", "error", _from_thread=True)
            return
        self._run_on_ui("bili-login", lambda: self._show_login_dlg(img, qrcode_key))

    def _show_login_dlg(self, qr_img, qrcode_key):
        dlg = tk.Toplevel(self)
        dlg.title("B 站扫码登录")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=self._theme_colors()["root"])

        ttk.Label(dlg, text="请用 B 站 APP 扫描二维码登录",
                  font=(UI_FONT, 10, "bold"),
                  bg=self._theme_colors()["root"],
                  fg=self._theme_colors()["fg"]).pack(padx=16, pady=(14, 6))
        photo = ImageTk.PhotoImage(qr_img)
        self._qr_photo = photo  # 持引用，防止被 GC 后图片消失
        ttk.Label(dlg, image=photo,
                  bg=self._theme_colors()["root"]).pack(padx=16, pady=4)
        status_lbl = ttk.Label(dlg, text="等待扫码…", style="Dim.TLabel")
        status_lbl.pack(padx=16, pady=(2, 4))
        ttk.Label(dlg, text="登录凭据仅保存在本机；登录后 B 站视频可下载更高清晰度",
                  font=(UI_FONT, 8), style="Faint.TLabel").pack(padx=16, pady=(0, 8))

        stop_event = threading.Event()

        def close():
            stop_event.set()
            try:
                dlg.destroy()
            except Exception:
                pass

        Button(dlg, text="取消", style="Ghost.TButton",
                   command=close).pack(pady=(0, 12))
        dlg.protocol("WM_DELETE_WINDOW", close)

        def ui_status(msg):
            self._run_on_ui("bili-login", lambda m=msg: self._safe_lbl(status_lbl, m))

        def worker():
            ok, cookies, msg = wait_login_qr(qrcode_key, status_cb=ui_status,
                                             stop_event=stop_event)
            def finish():
                if ok:
                    self._update_bili_btn()
                    self.status.config(text="✅ B 站登录成功")
                    self.show_toast("成功", "B 站登录成功，之后下载 B 站视频可获取更高清晰度", "success")
                elif msg != "已取消":
                    self.show_toast("未完成", msg, "warning")
            self._run_on_ui("bili-login", finish)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _safe_lbl(lbl, text):
        try:
            lbl.config(text=text)
        except tk.TclError:
            pass
    
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
            "epub": ("EPUB→TXT", converters.conv_epub),
            "mp4": ("MP4→MP3", converters.conv_mp4),
            "webp": ("WebP→JPG", converters.conv_webp),
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

    @staticmethod
    def _run_ffmpeg_cmd(cmd):
        """运行 ffmpeg 命令（隐藏控制台），失败抛 RuntimeError"""
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                shell=False, creationflags=no_window)
        try:
            proc.wait()
        finally:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        if proc.returncode != 0:
            err = (proc.stderr.read() or b"").decode("utf-8", errors="replace")[-300:]
            raise RuntimeError("ffmpeg 处理失败(code=%d): %s" % (proc.returncode, err))

    def _download_bili_direct(self, item, media, is_mp3, cb):
        """B站 API 直链下载（绕过网页 412）。失败抛异常，由调用方回退 yt-dlp。"""
        uid = item["uid"]
        self._dl_pcts[uid] = 0.0
        title = re.sub(r'[\\/:*?"<>|]', "_", media["title"]).strip() or "bilibili"
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
            "Referer": "https://www.bilibili.com/",
            "Cookie": _bili_cookie_header(),
        }
        out_dir = Path(self.output_dir)

        def ydl_fetch(url, lo, hi, what, tag):
            """用 yt-dlp 通用下载器拉取 CDN 直链，进度映射到 [lo, hi]"""
            def hook(d):
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    if total:
                        ratio = min(d.get("downloaded_bytes", 0) / total, 1.0)
                        cb(lo + (hi - lo) * ratio, "%s %.0f%%" % (what, ratio * 100))
            opts = {
                "outtmpl": str(out_dir / ("bili_tmp_%d_%s.%%(ext)s" % (uid, tag))),
                "quiet": True, "no_warnings": True, "noprogress": True,
                "retries": 5, "socket_timeout": 30, "continuedl": True,
                "concurrent_fragment_downloads": 4,
                "http_headers": headers,
                "progress_hooks": [hook],
            }
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([url])
            hits = sorted(out_dir.glob("bili_tmp_%d_%s.*" % (uid, tag)))
            if not hits:
                raise RuntimeError("下载失败：%s" % what)
            return hits[0]

        ffmpeg = get_ffmpeg_path()
        tmps = []
        try:
            if is_mp3:
                url = media.get("audio_url") or media.get("media_url")
                if not url:
                    raise RuntimeError("未找到音频流")
                tmp = ydl_fetch(url, 0.05, 0.80, "下载音频", "a")
                tmps.append(tmp)
                if not ffmpeg:
                    raise RuntimeError("需要 ffmpeg 转换 MP3，请先安装或自动下载 ffmpeg")
                cb(0.85, "转换 MP3...")
                out = _validated_output_file(out_dir / (title + ".mp3"), self.output_dir)
                self._run_ffmpeg_cmd([ffmpeg, "-nostdin", "-loglevel", "error",
                                      "-i", str(tmp), "-acodec", "libmp3lame",
                                      "-ab", "192k", "-y", str(out)])
            elif media["kind"] == "dash":
                v_tmp = a_tmp = None
                if media.get("video_url"):
                    v_tmp = ydl_fetch(media["video_url"], 0.05, 0.60, "下载视频流", "v")
                    tmps.append(v_tmp)
                if media.get("audio_url"):
                    a_tmp = ydl_fetch(media["audio_url"], 0.60, 0.80, "下载音频流", "a")
                    tmps.append(a_tmp)
                if v_tmp and a_tmp:
                    if not ffmpeg:
                        raise RuntimeError("需要 ffmpeg 合并音视频，请先安装或自动下载 ffmpeg")
                    cb(0.85, "合并音视频...")
                    out = _validated_output_file(out_dir / (title + ".mp4"), self.output_dir)
                    self._run_ffmpeg_cmd([ffmpeg, "-nostdin", "-loglevel", "error", "-y",
                                          "-i", str(v_tmp), "-i", str(a_tmp),
                                          "-c", "copy", "-movflags", "+faststart",
                                          str(out)])
                else:
                    src = v_tmp or a_tmp
                    if not src:
                        raise RuntimeError("未找到可下载的媒体流")
                    out = _validated_output_file(out_dir / (title + ".mp4"), self.output_dir)
                    os.replace(src, out)
            else:
                tmp = ydl_fetch(media["media_url"], 0.05, 0.85, "下载视频", "v")
                tmps.append(tmp)
                out = _validated_output_file(out_dir / (title + ".mp4"), self.output_dir)
                os.replace(tmp, out)

            cb(1.0, "完成!")
            name = Path(out).name
            item["name"] = name
            item["status"] = "done"
            item["progress"] = "100%"
            self.history.add(name, "下载", True, str(out))
            Logger.log("✅ 下载成功(直连): %s" % name)
            self._run_on_ui("download-status", lambda n=name: self.status.config(text="下载成功: %s" % n))
        finally:
            for t in tmps:
                try:
                    Path(t).unlink(missing_ok=True)
                except Exception:
                    pass
            self._dl_pcts.pop(uid, None)

    def _enqueue_urls(self):
        """把输入框中的链接加入队列（跨批次去重）。返回 (新增数, 跳过数)"""
        urls = self._get_urls_from_text()
        if not urls:
            return 0, 0
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
                self._uid_seq += 1
                self.dl_queue.append({
                    "uid": self._uid_seq, "url": url, "is_mp3": is_mp3,
                    "status": "waiting", "name": url[:80], "error": "",
                    "progress": "",
                })
                added += 1
        if added:
            self._run_on_ui("queue-refresh", self._queue_refresh_tree)
            self.url_text.delete("1.0", tk.END)
            self._set_url_placeholder(True)
        return added, skipped

    def _start_dl(self):
        """将输入框中的链接添加到下载队列（不自动开始）"""
        added, skipped = self._enqueue_urls()
        if added == 0:
            self.show_toast("提示", "没有新增链接：请输入链接，或所选链接已在队列中", "warning")
            return
        note = f"（跳过 {skipped} 个重复链接）" if skipped else ""
        self.status.config(text=f"已添加 {added} 个链接到队列{note}")
        self.show_toast("已添加", f"已将 {added} 个链接加入下载队列{note}", "info")

    def _start_queue(self):
        """开始下载：输入框中的链接直接入队并开始下载"""
        added, skipped = self._enqueue_urls()
        with self.dl_queue_lock:
            has_work = any(it["status"] in ("waiting", "retrying") for it in self.dl_queue)
        if not has_work:
            self.show_toast("提示", "没有可下载的任务：请先在输入框粘贴链接", "warning")
            return
        if added:
            note = f"，新增 {added} 个" + (f"（跳过 {skipped} 个重复）" if skipped else "")
            self.status.config(text=f"已从输入框入队{note}，开始下载")
        self._ensure_workers()

    def _ensure_workers(self):
        """确保下载 worker 数量达到设置的并发数（不足则补齐，不重复启动）"""
        with self.dl_queue_lock:
            need = self.max_parallel - self._active_workers
            if need <= 0:
                return
            self._active_workers += need
        for _ in range(need):
            threading.Thread(target=self._queue_worker, daemon=True).start()

    def _queue_worker(self):
        """后台 worker：领取 waiting/retrying 项逐个下载，队列为空时退出。
        可同时运行 max_parallel 个 worker 实现并行下载。"""
        while True:
            item = None
            with self.dl_queue_lock:
                for it in self.dl_queue:
                    if it["status"] in ("waiting", "retrying"):
                        it["status"] = "downloading"
                        item = it
                        break
            if item is None:
                # 队列空，本 worker 退出；最后一个退出时提示完成
                with self.dl_queue_lock:
                    self._active_workers -= 1
                    alive = self._active_workers
                if alive <= 0:
                    self._run_on_ui("queue-status", lambda: self.status.config(text="队列下载完成"))
                return
            self._run_on_ui("queue-refresh", self._queue_refresh_tree)
            self._run_on_ui("queue-status", lambda n=item["name"][:40]:
                       self.status.config(text=f"正在下载: {n}"))
            try:
                self._do_dl_item(item)
            except Exception as e:
                Logger.log(f"❌ 队列项异常: {e}")
                item["status"] = "failed"
                item["error"] = str(e)
            self._run_on_ui("queue-refresh", self._queue_refresh_tree)

    def _aggregate_dl_pct(self):
        """所有进行中下载的平均进度(0~1)，用于底部聚合进度条"""
        vals = list(self._dl_pcts.values())
        return sum(vals) / len(vals) if vals else 0.0

    def _do_dl_item(self, item):
        """下载单个队列项（在后台线程中执行，可多线程并行）"""
        url = item["url"]
        is_mp3 = item["is_mp3"]
        # 单调递增的显示进度(0~1)，按条目隔离以支持并行下载
        uid = item["uid"]
        self._dl_pcts[uid] = 0.0

        if not HAS_YTDLP:
            item["status"] = "failed"
            item["error"] = "请安装 yt-dlp"
            self.show_toast("缺少依赖", "请安装 yt-dlp:\npip install yt-dlp", "error", _from_thread=True)
            return

        def cb(pct, msg):
            pct = max(pct, 0.05)
            self._dl_pcts[uid] = max(self._dl_pcts[uid], pct)
            item["progress"] = f"{self._dl_pcts[uid]*100:.1f}%"
            agg = self._aggregate_dl_pct() * 100
            self._schedule_progress_ui(
                "download",
                lambda p=agg, m=msg: (
                    self.dl_prog.stop(),
                    self.dl_prog.config(value=p, mode="determinate"),
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
                    self._dl_pcts[uid] = max(self._dl_pcts[uid], mapped)
                    pct_show = self._dl_pcts[uid] * 100
                    item["progress"] = f"{pct_show:.1f}%"
                    agg = self._aggregate_dl_pct() * 100
                    self._schedule_progress_ui(
                        "download",
                        lambda p=agg, s=speed, e=eta: (
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

        # B站下载补 buvid3 Cookie（防 412 风控）；其他平台不需要
        bili_headers = None
        if is_bilibili_url(ready_url):
            buvid3 = get_buvid3_cached()
            if buvid3:
                bili_headers = {"Cookie": "buvid3=%s" % buvid3}

        # B站 412 风控：网页直取被拦时，改走 API 解析 + CDN 直链（与移动端同方案），
        # 失败再回退 yt-dlp 网页模式
        if is_bilibili_url(ready_url):
            try:
                cb(0.05, "B站直连解析...")
                media = resolve_bilibili_media(ready_url, prefer_audio=is_mp3)
                Logger.log("B站直连解析成功: %s [%s]" % (media["title"], media.get("quality", "")))
                return self._download_bili_direct(item, media, is_mp3, cb)
            except Exception as e:
                Logger.log("B站直连下载失败，回退 yt-dlp 网页模式: %s" % e)
                self._dl_pcts[uid] = 0.0

        try:
            self._dl_with_ytdlp(item, ready_url, is_mp3, is_foreign,
                                bili_headers, uid, cb, progress_hook)
        finally:
            self._dl_pcts.pop(uid, None)
            self._run_on_ui("download-finished", lambda: (
                self.dl_prog.stop(),
                self.dl_prog.config(mode="determinate"),
                self._queue_refresh_tree(),
                self.history_tree_refresh(),
                self._log_refresh()))
    
    # 瞬时网络错误特征：代理出口（如 WARP）轮换时连接会被掐断/重置，
    # 这类失败等待几秒重试一次通常就能成功
    _TRANSIENT_NET_RE = re.compile(
        r"ProxyError|RemoteDisconnected|ConnectionReset|Connection aborted|"
        r"timed out|TimeoutError|Temporary failure|WinError 10054|WinError 10060",
        re.IGNORECASE)

    @classmethod
    def _is_transient_net_error(cls, exc):
        return bool(cls._TRANSIENT_NET_RE.search(str(exc)))

    def _dl_with_ytdlp(self, item, ready_url, is_mp3, is_foreign, bili_headers,
                       uid, cb, progress_hook, _retried=False):
        """yt-dlp 通用下载（B站直连失败后的回退路径，也服务 YouTube/X/直链）。

        遇到瞬时网络错误自动重试一次：队列里显示为"重试中"。
        """
        try:
            opts = build_download_options(
                ready_url,
                is_mp3=is_mp3,
                output_dir=self.output_dir,
                ffmpeg_path=get_ffmpeg_path(),
                progress_hook=progress_hook,
                cookiefile=BILI_COOKIEFILE if BILI_COOKIEFILE.exists() else None,
                extra_headers=bili_headers,
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
            if not _retried and self._is_transient_net_error(e):
                Logger.log(f"网络抖动(代理出口可能已切换)，3 秒后自动重试: {e}")
                item["status"] = "retrying"
                item["progress"] = ""
                self._dl_pcts[uid] = 0.0
                self._run_on_ui("queue-refresh", self._queue_refresh_tree)
                time.sleep(3)
                self._dl_with_ytdlp(item, ready_url, is_mp3, is_foreign, bili_headers,
                                    uid, cb, progress_hook, _retried=True)
                return
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
                self._uid_seq += 1
                self.dl_queue.append({
                    "uid": self._uid_seq, "url": url, "is_mp3": True,
                    "status": "waiting", "name": f"🎵 {q}", "error": "",
                    "progress": "",
                })
            self._run_on_ui("song-fallback", lambda: (
                self._queue_refresh_tree(),
                self.status.config(text=f"B站无结果，已加入 YouTube 搜索: {q}")))
            self._ensure_workers()

        threading.Thread(target=run, daemon=True).start()

    def _show_song_results(self, query, results):
        """弹窗展示 B 站搜索结果，让用户选择"""
        dlg = tk.Toplevel(self)
        dlg.title(f"选择歌曲 - {query}")
        dlg.geometry("520x420")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=self._theme_colors()["root"])

        ttk.Label(dlg, text=f"🔍 搜索: {query}  （共 {len(results)} 条结果）",
                  font=(UI_FONT, 10, "bold"),
                  bg=self._theme_colors()["root"],
                  fg=self._theme_colors()["fg"]).pack(padx=12, pady=(12, 6), anchor=W)
        ttk.Label(dlg, text="点击选中后自动开始下载 MP3",
                  font=(UI_FONT, 9), style="Dim.TLabel").pack(padx=12, anchor=W)

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
                self._uid_seq += 1
                self.dl_queue.append({
                    "uid": self._uid_seq, "url": url, "is_mp3": True,
                    "status": "waiting", "name": f"🎵 {title}", "error": "",
                    "progress": "",
                })
            self._run_on_ui("queue-refresh", lambda: (
                self._queue_refresh_tree(),
                self.status.config(text=f"已加入队列: {title}")))
            self._ensure_workers()
            dlg.destroy()
            self.show_toast("已添加", f"已将 [{title}] 加入下载队列", "info")

        tree.bind("<Double-1>", on_select)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill=X, padx=12, pady=8)
        Button(btn_frame, text="▶ 下载选中", style="Accent.TButton",
                   command=on_select).pack(side=LEFT, padx=4)
        Button(btn_frame, text="取消", style="Ghost.TButton",
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
        self._ensure_workers()

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
        if getattr(self, "_history_count_lbl", None):
            try:
                self._history_count_lbl.config(
                    text=f"共 {len(items)} 条 · 显示 {row} 条" if row != len(items)
                    else f"共 {len(items)} 条记录")
            except tk.TclError:
                pass
    
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
