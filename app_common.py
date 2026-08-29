# -*- coding: utf-8 -*-
"""应用级通用模块：常量、路径校验、日志、历史记录、设置持久化。"""
import json
import threading
from datetime import datetime
from pathlib import Path

APP_VERSION = "v1.6.0"
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
