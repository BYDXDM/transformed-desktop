#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transformed - Win7 版 (纯 tkinter，无 ttkbootstrap)
格式转换 + 视频下载
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

HISTORY_FILE = Path.home() / ".transformed_history.json"
LOG_FILE = Path.home() / ".transformed_log.txt"

# 颜色方案（深色简洁）
BG = "#1e1e2e"
FG = "#e0e0e0"
ACCENT = "#7aa2f7"
CARD_BG = "#2a2a3e"
BTN_BG = "#565f89"

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

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
        import urllib.request, zipfile
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


class History:
    def __init__(self):
        self.items = []
        self.load()
    def load(self):
        if HISTORY_FILE.exists():
            try:
                self.items = json.load(open(HISTORY_FILE))
            except:
                self.items = []
    def save(self):
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        json.dump(self.items[-500:], open(HISTORY_FILE, "w"), indent=2)
    def add(self, name, typ, ok, out=""):
        self.items.append({"time": datetime.now().strftime("%m-%d %H:%M"),
                           "name": name, "type": typ, "ok": ok, "out": out})
        self.save()
    def clear(self):
        self.items = []
        self.save()


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
        self._build_ui()
        self._check_deps()

    def _style_config(self):
        self.style.configure("TFrame", background=BG)
        self.style.configure("TLabel", background=BG, foreground=FG)
        self.style.configure("TLabelframe", background=BG, foreground=FG)
        self.style.configure("TLabelframe.Label", background=BG, foreground=FG)
        self.style.configure("TButton", background=BTN_BG, foreground=FG,
                             padding=6)
        self.style.map("TButton", background=[("active", ACCENT)])
        self.style.configure("TNotebook", background=BG)
        self.style.configure("TNotebook.Tab", background=CARD_BG, foreground=FG,
                             padding=(12, 5))
        self.style.configure("Treeview", background=CARD_BG, foreground=FG,
                             fieldbackground=CARD_BG, rowheight=22)
        self.style.configure("Treeview.Heading", background=BTN_BG, foreground=FG)

    def _check_deps(self):
        missing = []
        if not HAS_YTDLP: missing.append("yt-dlp")
        if not HAS_EBOOKLIB: missing.append("ebooklib")
        if Image is None: missing.append("pillow")
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
        ok, result = download_ffmpeg(self._set_status)
        self.task_running = False
        if ok:
            self._set_status("ffmpeg 安装完成")
            messagebox.showinfo("成功", "ffmpeg 已安装!")
        else:
            self._set_status("ffmpeg 安装失败")
            messagebox.showerror("失败", result)

    def _set_status(self, msg):
        self.status_cfg["text"] = msg
        self.update_idletasks()

    def _build_ui(self):
        # 标题
        tk.Label(self, text="transformed", font=("", 20, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor=W, padx=12, pady=(10, 0))
        tk.Label(self, text="格式转换 · 视频下载", bg=BG, fg=FG).pack(anchor=W, padx=12)

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
        ttk.Label(lf, text=desc).pack(anchor=W)
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
        status.pack(anchor=W)
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
            self.convert_cards[key]["label"].config(text=f"已选 {len(files)} 个")

    def _build_download_tab(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  网络下载  ")
        ttk.Label(tab, text="视频链接 / BV号 / AV号").pack(anchor=W)
        self.url_var = tk.StringVar()
        tk.Entry(tab, textvariable=self.url_var, width=60,
                 bg=CARD_BG, fg=FG, insertbackground=FG).pack(fill=tk.X, pady=4)
        opt = ttk.Frame(tab)
        opt.pack(fill=tk.X, pady=4)
        self.dl_type = tk.StringVar(value="mp4")
        ttk.Radiobutton(opt, text="视频 MP4", variable=self.dl_type,
                        value="mp4").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(opt, text="音频 MP3", variable=self.dl_type,
                        value="mp3").pack(side=tk.LEFT, padx=4)
        ttk.Button(opt, text="下载", command=self._start_dl).pack(side=tk.RIGHT)
        self.dl_prog = ttk.Progressbar(tab, mode="determinate")
        self.dl_prog.pack(fill=tk.X, pady=4)
        self.dl_stat = ttk.Label(tab, text="")
        self.dl_stat.pack(anchor=W)
        ttk.Label(tab, text="支持: B站 / YouTube / Twitter / 直链",
                  foreground=ACCENT).pack(anchor=W, pady=(10, 0))

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
        ttk.Label(parent, text="  转换记录  ").pack(anchor=W, pady=(0, 4))
        filt = ttk.Frame(parent)
        filt.pack(fill=tk.X)
        self.filter_var = tk.StringVar(value="全部")
        for tag in ["全部", "EPUB", "MP4", "WebP", "下载"]:
            ttk.Radiobutton(filt, text=tag, variable=self.filter_var,
                            value=tag, command=self._history_refresh).pack(side=tk.LEFT, padx=2)
        cols = ("time", "file", "type", "status")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c, w, t in [("time", 80, "时间"), ("file", 160, "文件"),
                        ("type", 70, "类型"), ("status", 40, "状态")]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=4)
        ttk.Button(parent, text="清空", command=self._history_clear).pack(anchor=E)
        self._history_refresh()

    # ---- 转换逻辑 ----
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
            def cb(pct, msg):
                overall = (i / total) + (pct / total)
                ct["prog"]["value"] = overall * 100
                ct["status"].config(text=f"[{i+1}/{total}] {Path(f).name}: {msg}")
                self.update_idletasks()
            ok, result = fn(f, self.output_dir, cb)
            self.history.add(Path(f).name, typ, ok, result if ok else "")
        self.task_running = False
        ct["files"] = []
        ct["label"].config(text="完成")
        ct["prog"]["value"] = 0
        self._history_refresh()
        self._log_refresh()
        messagebox.showinfo("完成", f"{typ} 转换完成！\n保存至: {self.output_dir}")

    def _conv_epub(self, path, out_dir, cb):
        if not HAS_EBOOKLIB:
            return False, "缺 ebooklib"
        try:
            cb(0.1, "读取...")
            book = epub.read_epub(path)
            out = Path(out_dir) / f"{Path(path).stem}.txt"
            texts = []
            items = list(book.get_items_of_type(9))
            for i, it in enumerate(items):
                html = it.get_body_content().decode("utf-8", errors="replace")
                import html as hm
                text = re.sub(r"<[^>]+>", " ", html)
                text = hm.unescape(text)
                text = re.sub(r"\s+", " ", text).strip()
                if text: texts.append(text)
                cb(0.1 + (i/len(items))*0.8, f"解析 {i+1}/{len(items)}")
            open(out, "w", encoding="utf-8").write("\n\n".join(texts))
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
            out = Path(out_dir) / f"{Path(path).stem}.mp3"
            subprocess.run([ff, "-i", str(path), "-vn", "-acodec",
                            "libmp3lame", "-ab", "192k", "-y", str(out)],
                           capture_output=True)
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
            out = Path(out_dir) / f"{Path(path).stem}.jpg"
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            img.save(out, "JPEG", quality=92)
            cb(1.0, "完成")
            return True, str(out)
        except Exception as e:
            return False, str(e)

    # ---- 下载 ----
    def _start_dl(self):
        if self.task_running:
            messagebox.showwarning("提示", "任务执行中")
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入链接")
            return
        if not HAS_YTDLP:
            messagebox.showerror("缺依赖", "请安装 yt-dlp")
            return
        self.task_running = True
        threading.Thread(target=self._do_dl, args=(url,), daemon=True).start()

    def _do_dl(self, url):
        is_mp3 = self.dl_type.get() == "mp3"
        def cb(pct, msg):
            self.dl_prog["value"] = pct * 100
            self.dl_stat.config(text=msg)
            self.update_idletasks()
        try:
            cb(0.05, "解析...")
            opts = {"outtmpl": str(Path(self.output_dir) / "%(title)s.%(ext)s"),
                    "quiet": True, "no_warnings": True}
            ff = get_ffmpeg_path()
            if ff: opts["ffmpeg_location"] = str(Path(ff).parent.parent)
            if is_mp3:
                opts.update({"format": "bestaudio/best",
                             "postprocessors": [{"key": "FFmpegExtractAudio",
                                                 "preferredcodec": "mp3",
                                                 "preferredquality": "192"}]})
            else:
                opts["format"] = "best[height<=720]/best"
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            fn = ydl.prepare_filename(info)
            if is_mp3:
                fn = str(Path(fn).with_suffix(".mp3"))
            self.history.add(Path(fn).name, "下载", True, fn)
            self._set_status("下载成功")
            messagebox.showinfo("成功", f"已保存:\n{fn}")
        except Exception as e:
            self._set_status("下载失败")
            messagebox.showerror("失败", str(e))
        self.task_running = False
        self.dl_prog["value"] = 0
        self._history_refresh()

    # ---- 历史/日志 ----
    def _history_refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        tag = self.filter_var.get()
        for h in reversed(self.history.items):
            if tag != "全部" and tag not in h["type"]:
                continue
            self.tree.insert("", "end", values=(h["time"], h["name"][:25],
                                               h["type"], "✓" if h["ok"] else "✗"))

    def _history_clear(self):
        if messagebox.askyesno("确认", "清空记录?"):
            self.history.clear()
            self._history_refresh()

    def _log_refresh(self):
        self.log_text.delete(1.0, "end")
        if LOG_FILE.exists():
            lines = open(LOG_FILE).read().splitlines()[-200:]
            for l in lines:
                self.log_text.insert("end", l + "\n")
        self.log_text.see("end")

    def _log_clear(self):
        self.log_text.delete(1.0, "end")
        try:
            open(LOG_FILE, "w").close()
        except: pass


if __name__ == "__main__":
    app = App()
    app.mainloop()
