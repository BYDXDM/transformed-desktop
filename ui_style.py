# -*- coding: utf-8 -*-
"""UI 视觉层：深海主题调色板 + 全套 ttk 样式定义 + 自绘控件辅助。

只负责"好看"，不含业务逻辑。调色板数据在 app_common.PALETTES，
本模块把调色板应用到 ttk.Style，并提供卡片/导航等构建辅助。
"""
import ctypes
import tkinter as tk

UI_FONT = "Microsoft YaHei UI"


def apply_palette(style, win, pal):
    """把调色板应用到 ttk.Style（可在主题切换时反复调用）。Win10 Fluent 风格。"""
    f = (UI_FONT, 9)
    fs = (UI_FONT, 8)

    # ---- 全局默认 ----
    style.configure(".", background=pal["root"], foreground=pal["fg"],
                    font=f, borderwidth=0, focuscolor=pal["root"])

    # ---- Frame / Label ----
    style.configure("TFrame", background=pal["root"])
    style.configure("TLabel", background=pal["root"], foreground=pal["fg"])
    for name, fg, bg, font in (
            ("Dim.TLabel", pal["dim"], pal["root"], fs),
            ("Faint.TLabel", pal["faint"], pal["root"], fs),
            ("Card.TLabel", pal["fg"], pal["card"], f),
            ("CardDim.TLabel", pal["dim"], pal["card"], fs),
            ("CardFaint.TLabel", pal["faint"], pal["card"], fs),
            ("CardTitle.TLabel", pal["fg"], pal["card"], (UI_FONT, 10, "bold")),
            ("CardAccent.TLabel", pal["accent"], pal["card"], fs),
            ("CardOk.TLabel", pal["ok"], pal["card"], fs),
            ("CardDanger.TLabel", pal["danger"], pal["card"], fs),
            ("Side.TLabel", pal["fg"], pal["side"], f),
            ("SideDim.TLabel", pal["dim"], pal["side"], fs),
            ("SideFaint.TLabel", pal["faint"], pal["side"], fs),
            ("H1.TLabel", pal["fg"], pal["root"], (UI_FONT, 14, "bold")),
    ):
        style.configure(name, foreground=fg, background=bg, font=font)

    # ---- 按钮（Win10：方形 + 1px 边框，悬停变浅蓝） ----
    def _btn(name, bg, fg, hov, down, border, hov_border):
        style.configure(name, background=bg, foreground=fg, borderwidth=1,
                        relief="flat", focusthickness=0, focuscolor=bg,
                        padding=(14, 6), font=f, anchor="center",
                        bordercolor=border, lightcolor=bg, darkcolor=bg)
        style.map(name,
                  background=[("disabled", bg), ("pressed", down), ("active", hov)],
                  bordercolor=[("disabled", border), ("pressed", hov_border),
                               ("active", hov_border)],
                  foreground=[("disabled", pal["faint"]), ("active", fg)],
                  lightcolor=[("!disabled", bg)], darkcolor=[("!disabled", bg)],
                  focuscolor=[("focus", bg)])

    _btn("Accent.TButton", pal["accent"], pal["accent_fg"],
         pal["accent_hover"], pal["accent_down"],
         pal["accent"], pal["accent_hover"])
    _btn("Tonal.TButton", pal["tonal"], pal["fg"],
         pal["tonal_hover"], pal["tonal_hover"],
         pal["btn_border"], pal["accent"])
    _btn("Ghost.TButton", pal["card"], pal["fg"],
         pal["card2"], pal["card2"], pal["card"], pal["card2"])
    _btn("SideGhost.TButton", pal["side"], pal["fg"],
         pal["card2"], pal["card2"], pal["side"], pal["card2"])
    _btn("Danger.TButton", pal["danger_bg"], pal["danger"],
         pal["danger_bg_hover"], pal["danger_bg_hover"],
         pal["danger_bg"], pal["danger"])

    # 小号按钮变体（继承各基础按钮的配色，只改内边距和字号）
    for base in ("Accent.TButton", "Tonal.TButton", "Ghost.TButton",
                 "SideGhost.TButton", "Danger.TButton"):
        style.configure("Small." + base, padding=(10, 4), font=fs)

    # ---- 输入框（Win10 文本框：灰边框，聚焦变强调色） ----
    style.configure("TEntry", fieldbackground=pal["input"], foreground=pal["fg"],
                    insertcolor=pal["fg"], bordercolor=pal["input_border"],
                    lightcolor=pal["input_border"], darkcolor=pal["input_border"],
                    padding=(8, 5))
    style.map("TEntry",
              bordercolor=[("focus", pal["accent"])],
              lightcolor=[("focus", pal["accent"])],
              darkcolor=[("focus", pal["accent"])],
              fieldbackground=[("disabled", pal["input"]), ("readonly", pal["input"])],
              foreground=[("disabled", pal["faint"])])

    style.configure("TCombobox", fieldbackground=pal["input"], foreground=pal["fg"],
                    background=pal["card2"], arrowcolor=pal["dim"],
                    bordercolor=pal["input_border"], lightcolor=pal["input_border"],
                    darkcolor=pal["input_border"], padding=(6, 4), arrowsize=12)
    style.map("TCombobox",
              fieldbackground=[("readonly", pal["input"]), ("focus", pal["input"]),
                               ("disabled", pal["input"])],
              background=[("active", pal["card2"]), ("readonly", pal["card2"]),
                          ("pressed", pal["card2"])],
              foreground=[("focus", pal["fg"]), ("disabled", pal["faint"])],
              arrowcolor=[("active", pal["fg"]), ("disabled", pal["faint"])],
              bordercolor=[("focus", pal["accent"])])
    # 下拉列表本身是经典 tk Listbox
    win.option_add("*TCombobox*Listbox.background", pal["card"])
    win.option_add("*TCombobox*Listbox.foreground", pal["fg"])
    win.option_add("*TCombobox*Listbox.selectBackground", pal["sel"])
    win.option_add("*TCombobox*Listbox.selectForeground", pal["sel_fg"])
    win.option_add("*TCombobox*Listbox.font", fs)
    win.option_add("*TCombobox*Listbox.relief", "flat")
    win.option_add("*TCombobox*Listbox.borderWidth", 0)

    # ---- 树状列表（Win10 列表：无框、选中整行强调色） ----
    style.configure("Treeview", background=pal["card"], fieldbackground=pal["card"],
                    foreground=pal["fg"], rowheight=30, font=f, borderwidth=0,
                    relief="flat")
    style.map("Treeview",
              background=[("selected", pal["sel"])],
              foreground=[("selected", pal["sel_fg"])])
    style.configure("Treeview.Heading", background=pal["root"], foreground=pal["dim"],
                    font=fs, relief="flat", borderwidth=0, padding=(6, 5))
    style.map("Treeview.Heading",
              background=[("active", pal["root"])],
              foreground=[("active", pal["fg"])])

    # ---- 进度条（Win10：细条） ----
    # ttkbootstrap 的进度条填充是按主题色烘焙的图片元素，background 不生效；
    # 先把 trough/pbar 元素换成 clam 主题的纯色元素，颜色才可控。
    for part in ("trough", "pbar"):
        for orient in ("Horizontal", "Vertical"):
            try:
                style.element_create(f"{orient}.Progressbar.{part}", "from", "clam")
            except Exception:
                pass

    def _bar(name, color):
        # lightcolor/darkcolor 是立体描边色：与 trough 同色保持扁平
        style.configure(name, background=color, troughcolor=pal["card2"],
                        bordercolor=pal["card2"], lightcolor=pal["card2"],
                        darkcolor=pal["card2"], thickness=6)
        style.map(name,
                  background=[("!disabled", color)],
                  lightcolor=[("!disabled", pal["card2"])],
                  darkcolor=[("!disabled", pal["card2"])])

    _bar("Horizontal.TProgressbar", pal["accent"])
    _bar("Ok.Horizontal.TProgressbar", pal["ok"])
    _bar("Danger.Horizontal.TProgressbar", pal["danger"])

    # ---- 其他 ----
    style.configure("TSeparator", background=pal["border"])
    style.configure("TScrollbar", background=pal["card2"], troughcolor=pal["root"],
                    bordercolor=pal["root"], arrowcolor=pal["dim"], relief="flat",
                    arrowsize=11, gripcount=0)
    style.map("TScrollbar",
              background=[("active", pal["border"]), ("pressed", pal["accent"])],
              arrowcolor=[("active", pal["fg"])])
    style.configure("TLabelframe", background=pal["root"], borderwidth=0)
    style.configure("TLabelframe.Label", background=pal["root"],
                    foreground=pal["dim"], font=fs)

    # ---- 胶囊单选（Win10 开关：未选=标准按钮，选中=强调色填充） ----
    style.layout("Chip.TRadiobutton", [
        ("Radiobutton.padding", {"children":
            [("Radiobutton.label", {"sticky": "nswe"})], "sticky": "nswe"})])
    style.configure("Chip.TRadiobutton", background=pal["card2"], foreground=pal["fg"],
                    font=fs, anchor="center", padding=(12, 4), borderwidth=1,
                    relief="flat", focuscolor=pal["card2"],
                    bordercolor=pal["card2"], lightcolor=pal["card2"],
                    darkcolor=pal["card2"])
    style.map("Chip.TRadiobutton",
              background=[("selected", pal["accent"]), ("active", pal["tonal_hover"])],
              foreground=[("selected", pal["accent_fg"]), ("active", pal["fg"])],
              bordercolor=[("selected", pal["accent"]), ("active", pal["accent"])])


def style_titlebar(win, dark):
    """Windows 深色标题栏 + 方角（Win10 Fluent 不做圆角）。失败静默。"""
    if not win.winfo_exists():
        return
    try:
        import sys
        if sys.platform != "win32":
            return
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        for attr, val in ((20, 1 if dark else 0),   # DWMWA_USE_IMMERSIVE_DARK_MODE
                          (33, 1)):                  # DWMWA_WINDOW_CORNER_PREFERENCE = DO_NOT_ROUND
            v = ctypes.c_int(val)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass
