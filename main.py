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
class Logger:
    @staticmethod
    def log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except:
            pass
        return entry
    
    @staticmethod
    def read():
        if LOG_FILE.exists():
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        return []

class History:
    def __init__(self):
        self.items = []
        self.load()
    
    def load(self):
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r") as f:
                    self.items = json.load(f)
            except:
                self.items = []
    
    def save(self):
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(self.items[-500:], f, indent=2)
    
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
class App(ttk.Window):
    def __init__(self):
        super().__init__(title="transformed", themename="superhero")
        
        self.geometry("1100x720")
        self.minsize(900, 600)
        
        self.history = History()
        self.task_running = False
        self.convert_cards = {}
        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        self.output_dir = str(exe_dir / "transformed_output")
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        self._build_ui()
        self._check_deps()
    
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
        try:
            def cb(msg):
                self.status.config(text=msg)
                self.update_idletasks()
            
            ok, result = download_ffmpeg(cb)
            if ok:
                self.status.config(text="✅ ffmpeg 安装完成，MP4转MP3现可用")
                self.show_toast("成功", "ffmpeg 已自动安装完成！", "success", _from_thread=True)
            else:
                self.status.config(text="ffmpeg 安装失败")
                self.show_toast("失败", result, "error", _from_thread=True)
        except Exception as e:
            self.status.config(text="ffmpeg 安装失败")
            self.show_toast("失败", str(e), "error", _from_thread=True)
        finally:
            self.task_running = False
    
    def show_toast(self, title, msg, level="info", _from_thread=False):
        """线程安全的对话框。后台线程调用传 _from_thread=True"""
        if _from_thread:
            self.after(0, lambda: self._show_toast_ui(title, msg))
            return
        self._show_toast_ui(title, msg)
    
    def _show_toast_ui(self, title, msg):
        dialog = ttk.Toplevel(self)
        dialog.title(title)
        dw, dh = 540, 240
        # 居中且可拖动
        sx = self.winfo_x() + (self.winfo_width() - dw) // 2
        sy = self.winfo_y() + (self.winfo_height() - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{sx}+{sy}")
        dialog.resizable(False, False)
        dialog.transient(self)
        # 不 grab_set，允许拖动和操作主窗口
        
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=BOTH, expand=True)
        ttk.Label(frame, text=msg, font=("", 11),
                 wraplength=480, justify="left").pack(pady=18, fill=BOTH, expand=True)
        ttk.Button(frame, text="  确定  ", command=dialog.destroy).pack()
    
    def _build_ui(self):
        # ===== 顶部标题栏 =====
        header = ttk.Frame(self, padding=15)
        header.pack(fill=X)
        
        ttk.Label(header, text="transformed", font=("", 22, "bold"),
                 bootstyle="inverse-primary").pack(side=LEFT)
        ttk.Label(header, text="格式转换 · 视频下载",
                 font=("", 10)).pack(side=LEFT, padx=10)
        
        # 设置按钮
        ttk.Button(header, text="⚙ 输出目录",
                  command=self._set_output, bootstyle="outline").pack(side=RIGHT, padx=2)
        ttk.Button(header, text="⟳", width=3,
                  command=lambda: self.history_tree_refresh(),
                  bootstyle="outline").pack(side=RIGHT, padx=2)
        
        # ===== 主区域 =====
        main = ttk.Panedwindow(self, orient=HORIZONTAL)
        main.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        # 左侧功能面板
        left = ttk.Frame(main)
        main.add(left, weight=3)
        
        # 右侧历史面板
        right = ttk.Frame(main)
        main.add(right, weight=2)
        
        self._build_left(left)
        self._build_right(right)
        
        # ===== 底部状态栏 =====
        status = ttk.Frame(self, padding=5)
        status.pack(fill=X, side=BOTTOM)
        self.status = ttk.Label(status, text="就绪", bootstyle="secondary")
        self.status.pack(side=LEFT)
        ttk.Label(status, text="transformed Desktop v1.0",
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
            "提取 MP4 视频中的音频轨道，保存为 MP3",
            lambda: self._pick("mp4", [("MP4", "*.mp4")]),
            lambda: self._convert("mp4"))
        
        # WebP
        self._make_converter_card(tab1, "WebP → JPG", "webp",
            "将 WebP 图片批量转换为 JPEG 格式",
            lambda: self._pick("webp", [("WebP", "*.webp")]),
            lambda: self._convert("webp"))
        
        # --- Tab 2: 网络下载 ---
        tab2 = ttk.Frame(nb, padding=15)
        nb.add(tab2, text="🌐 网络下载")
        
        # URL 输入
        ttk.Label(tab2, text="视频链接 / BV号 / AV号",
                 font=("", 12)).pack(anchor=W)
        
        url_frame = ttk.Frame(tab2)
        url_frame.pack(fill=X, pady=5)
        
        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var,
                             font=("", 11))
        url_entry.pack(fill=X, side=LEFT, expand=True)
        url_entry.insert(0, "支持 B站 / YouTube / Twitter / 直链")
        url_entry.bind("<FocusIn>", lambda e: self.url_var.set("") if
                      self.url_var.get() == "支持 B站 / YouTube / Twitter / 直链" else None)
        
        # 格式选择
        opt = ttk.Frame(tab2)
        opt.pack(fill=X, pady=10)
        
        self.dl_type = tk.StringVar(value="mp4")
        ttk.Radiobutton(opt, text="🎬 视频 MP4", variable=self.dl_type,
                       value="mp4", bootstyle="success").pack(side=LEFT, padx=2)
        ttk.Radiobutton(opt, text="🎵 音频 MP3", variable=self.dl_type,
                       value="mp3", bootstyle="warning").pack(side=LEFT, padx=2)
        
        ttk.Button(opt, text="⬇ 下载", bootstyle="success",
                  command=self._start_dl).pack(side=RIGHT, padx=5)
        
        # 下载进度
        self.dl_prog = ttk.Progressbar(tab2, mode="determinate", bootstyle="info")
        self.dl_prog.pack(fill=X, pady=5)
        self.dl_stat = ttk.Label(tab2, text="")
        self.dl_stat.pack(anchor=W)
        
        # 支持列表
        info = ttk.Frame(tab2, padding=10)
        info.pack(fill=X, pady=10)
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
        card = ttk.Frame(parent, padding=12, bootstyle="secondary")
        card.pack(fill=X, pady=6)
        
        # 标题行
        hdr = ttk.Frame(card)
        hdr.pack(fill=X)
        ttk.Label(hdr, text=title, font=("", 13, "bold")).pack(side=LEFT)
        
        self.convert_cards[key] = {
            "files": [],
            "label": ttk.Label(hdr, text="未选择文件", bootstyle="secondary"),
            "progress": ttk.Progressbar(card, mode="determinate", bootstyle="success"),
            "status": ttk.Label(card, text=""),
            "pick_fn": pick_fn,
            "conv_fn": conv_fn,
        }
        
        self.convert_cards[key]["label"].pack(side=LEFT, padx=10)
        
        ttk.Label(card, text=desc, bootstyle="secondary").pack(anchor=W, pady=2)
        
        btn_frame = ttk.Frame(card)
        btn_frame.pack(fill=X, pady=5)
        
        ttk.Button(btn_frame, text="📂 选择文件",
                  command=pick_fn, bootstyle="primary-outline").pack(side=LEFT, padx=2)
        ttk.Button(btn_frame, text="▶ 开始转换",
                  command=conv_fn, bootstyle="success").pack(side=LEFT, padx=2)
        
        self.convert_cards[key]["label"].pack()
        self.convert_cards[key]["progress"].pack(fill=X, pady=4)
        self.convert_cards[key]["status"].pack(anchor=W)
    
    # ---- 右侧历史 ----
    def _build_right(self, parent):
        ttk.Label(parent, text="📜 转换记录", font=("", 13, "bold"),
                 bootstyle="inverse-secondary").pack(fill=X, pady=5)
        
        # 筛选
        filt = ttk.Frame(parent)
        filt.pack(fill=X)
        self.filter_var = tk.StringVar(value="全部")
        for tag in ["全部", "EPUB", "MP4", "WebP", "下载"]:
            ttk.Radiobutton(filt, text=tag, variable=self.filter_var,
                          value=tag, command=self.history_tree_refresh,
                          bootstyle="outline").pack(side=LEFT, padx=2)
        
        # 树状表格
        cols = ("time", "file", "type", "status")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings",
                                 height=18, bootstyle="info")
        self.tree.heading("time", text="时间")
        self.tree.heading("file", text="文件")
        self.tree.heading("type", text="类型")
        self.tree.heading("status", text="状态")
        self.tree.column("time", width=90)
        self.tree.column("file", width=160)
        self.tree.column("type", width=70)
        self.tree.column("status", width=40)
        
        scroll = ttk.Scrollbar(parent, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)
        
        # 底部按钮
        btm = ttk.Frame(parent)
        btm.pack(fill=X, pady=5)
        ttk.Button(btm, text="🗑 清空", bootstyle="danger-outline",
                  command=self._history_clear).pack(side=RIGHT)
        
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
        
        try:
            for i, f in enumerate(files):
                def mk_cb(i, f):
                    def cb(pct, msg):
                        overall = (i / total) + (pct / total)
                        ct["progress"]["value"] = overall * 100
                        ct["status"].config(text=f"[{i+1}/{total}] {Path(f).name}: {msg}")
                        self.dl_prog["value"] = overall * 100
                        self.dl_stat.config(text=f"{typ_name}: [{i+1}/{total}]")
                        self.update_idletasks()
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
                self.status.config(text=f"{'完成' if ok else '失败'}: {Path(f).name}")
        finally:
            # 确保无论成功/异常都重置状态，防止卡死
            self.task_running = False
            ct["files"] = []
            ct["label"].config(text="完成 ✓")
            ct["progress"]["value"] = 0
            self.dl_prog["value"] = 0
            self.history_tree_refresh()
            self._log_refresh()
            self.show_toast("完成", f"批量 {typ_name} 转换完成!\n保存至: {self.output_dir}", "success", _from_thread=True)
    
    def _conv_epub(self, path, out_dir, cb):
        if not HAS_EBOOKLIB:
            return False, "请安装: pip install ebooklib"
        try:
            cb(0.1, "读取 EPUB...")
            book = epub.read_epub(path)
            name = Path(path).stem
            out = Path(out_dir) / f"{name}.txt"
            texts = []
            items = list(book.get_items_of_type(9))
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
            subprocess.run(cmd, capture_output=True)
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

        # 2. Bilibili BV号 (BV 后12位字母数字)
        m = re.match(r'(BV[0-9A-Za-z]{10,12})', url)
        if m:
            return f"https://www.bilibili.com/video/{m.group(1)}"
        # 3. AV号
        m = re.match(r'(av\d+)', url, re.IGNORECASE)
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

    def _start_dl(self):
        if self.task_running:
            self.show_toast("提示", "正在下载", "warning")
            return
        url = self.url_var.get().strip()
        if not url or url == "支持 B站 / YouTube / Twitter / 直链":
            self.show_toast("提示", "请输入链接", "warning")
            return
        self.task_running = True
        threading.Thread(target=self._do_dl, args=(url,), daemon=True).start()
    
    def _do_dl(self, url):
        is_mp3 = self.dl_type.get() == "mp3"
        
        if not HAS_YTDLP:
            self.task_running = False
            self.show_toast("缺少依赖", "请安装 yt-dlp:\npip install yt-dlp", "error", _from_thread=True)
            return
        
        def cb(pct, msg):
            self.dl_prog["value"] = pct * 100
            self.dl_stat.config(text=msg)
            self.update_idletasks()
        
        ready_url = self._prepare_url(url)
        cb(0.05, "解析链接...")
        Logger.log(f"下载: {url} -> {ready_url}")
        
        try:
            opts = {
                "outtmpl": str(Path(self.output_dir) / "%(title)s.%(ext)s"),
                "quiet": True, "no_warnings": True,
            }
            # ffmpeg_location 需指向含 ffmpeg.exe 的实际目录
            ffmpeg_bin = get_ffmpeg_path()
            if ffmpeg_bin:
                opts["ffmpeg_location"] = str(Path(ffmpeg_bin).parent)
            
            # 3. 先判断平台再设格式
            if "bilibili.com" in ready_url or ready_url.startswith("BV") or ready_url.startswith("av"):
                # B站：用 bv*+ba 保证有音视频
                if is_mp3:
                    opts["format"] = "ba/b"
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
            self.history.add(name, "下载", True, fn)
            Logger.log(f"✅ 下载成功: {name}")
            self.status.config(text=f"下载成功: {name}")
            self.show_toast("下载成功", f"已保存:\n{fn}", "success", _from_thread=True)
        except Exception as e:
            Logger.log(f"❌ 下载失败: {e}")
            self.status.config(text="下载失败")
            self.show_toast("下载失败", str(e), "error", _from_thread=True)
        finally:
            self.task_running = False
            self.dl_prog["value"] = 0
            self.history_tree_refresh()
            self._log_refresh()
    
    def history_tree_refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        tag = self.filter_var.get()
        for h in reversed(self.history.items):
            if tag != "全部" and tag not in h["type"]:
                continue
            s = "✓" if h["ok"] else "✗"
            self.tree.insert("", END, values=(h["time"], h["name"][:25], h["type"], s))
    
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
            open(LOG_FILE, "w").close()
        except:
            pass


if __name__ == "__main__":
    app = App()
    app.mainloop()
