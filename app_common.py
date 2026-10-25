# -*- coding: utf-8 -*-
"""应用级通用模块：常量、路径校验、日志、历史记录、设置持久化。"""
import json
import threading
from datetime import datetime
from pathlib import Path

APP_VERSION = "v1.7.0"
UI_FONT = "Segoe UI"  # 缺字形的中文由系统字体回退，观感与 Win10 原生一致

# 深浅色两套完整调色板（ui_style.apply_palette 消费）。
# 风格基准：Windows 10 设置（Fluent）——中性灰阶 + 系统强调蓝。
# dark = 是否深色（用于标题栏深色模式）；btn_other = 切换按钮显示的目标主题文字。
# 兼容旧设置值：superhero/flatly 经 THEME_ALIASES 映射。
PALETTES = {
    "deep": {
        "dark": True, "btn_other": "浅色模式",
        "root": "#1f1f1f", "side": "#1f1f1f", "nav_sel": "#333333",
        "card": "#2b2b2b", "card2": "#333333", "input": "#2b2b2b",
        "tonal": "#333333", "tonal_hover": "#3d3d3d",
        "border": "#383838",
        "btn_border": "#4a4a4a", "input_border": "#5a5a5a",
        "fg": "#ffffff", "dim": "#a6a6a6", "faint": "#767676", "ph": "#6b6b6b",
        "accent": "#0078d7", "accent_hover": "#1a86d9", "accent_down": "#005a9e",
        "accent_fg": "#ffffff",
        "ok": "#6ccb5f", "warn": "#ffb900", "danger": "#ff6b6b", "info": "#4cc2ff",
        "danger_bg": "#3c1a1e", "danger_bg_hover": "#4a2025",
        "sel": "#0078d7", "sel_fg": "#ffffff",
        "zebra1": "#2b2b2b", "zebra2": "#303030",
        # 功能卡彩色徽章（Win10 磁贴风，深浅主题共用）
        "chips": ["#00b294", "#0078d7", "#ca5010"],
        "q_tags": {"waiting": "#a6a6a6", "downloading": "#4cc2ff",
                   "done": "#6ccb5f", "failed": "#ff6b6b", "retrying": "#ffb900"},
    },
    "day": {
        "dark": False, "btn_other": "深色模式",
        "root": "#f3f3f3", "side": "#f3f3f3", "nav_sel": "#e6e6e6",
        "card": "#ffffff", "card2": "#e9e9e9", "input": "#ffffff",
        "tonal": "#e1e1e1", "tonal_hover": "#e5f1fb",
        "border": "#d9d9d9",
        "btn_border": "#adadad", "input_border": "#767676",
        "fg": "#1a1a1a", "dim": "#5f5f5f", "faint": "#8a8a8a", "ph": "#8a8a8a",
        "accent": "#0078d7", "accent_hover": "#1a86d9", "accent_down": "#005a9e",
        "accent_fg": "#ffffff",
        "ok": "#107c10", "warn": "#9a7b00", "danger": "#c50f1f", "info": "#0063b1",
        "danger_bg": "#fde7e9", "danger_bg_hover": "#fbdcdc",
        "sel": "#0078d7", "sel_fg": "#ffffff",
        "zebra1": "#ffffff", "zebra2": "#f7f7f7",
        "chips": ["#00b294", "#0078d7", "#ca5010"],
        "q_tags": {"waiting": "#5f5f5f", "downloading": "#0063b1",
                   "done": "#107c10", "failed": "#c50f1f", "retrying": "#9a7b00"},
    },
}

# 旧版设置里存的是 ttkbootstrap 主题名，映射到新调色板
THEME_ALIASES = {"superhero": "deep", "flatly": "day", "dark": "deep", "light": "day"}

# 调色板 -> ttkbootstrap 基础主题（只作底，所有样式随后被 apply_palette 覆盖）
BASE_THEMES = {"deep": "darkly", "day": "flatly"}

# 向后兼容：旧代码里的 THEMES 一律指 PALETTES
THEMES = PALETTES

HISTORY_FILE = Path.home() / ".transformed_history.json"
LOG_FILE = Path.home() / ".transformed_log.txt"
SETTINGS_FILE = (Path.home() / ".transformed_settings.json").resolve()


def _validated_output_file(path, base):
    """规范化目标路径并确保其位于 base 目录内，防止路径穿越。"""
    base = Path(base).resolve()
    target = Path(path).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"拒绝写入 {base} 之外的路径: {target}")
    return target


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
                    data = json.load(f)
                # 容错：跳过损坏/非字典条目，避免旧版本记录导致崩溃
                self.items = [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
            except Exception:
                self.items = []

    def save(self):
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self):
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


class AppSettings:
    """轻量设置持久化（输出目录/下载格式/主题等），损坏时回退默认值。"""
    DEFAULTS = {
        "output_dir": "",
        "dl_type": "mp4",
        "theme": "superhero",
        "update_last_check": 0.0,
        "parallel": 2,
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
