#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能测试：初始化 App 并检查关键方法/属性存在"""
import sys
import os

# 确保不弹出真实窗口（Xvfb 或直接检查）
os.environ.setdefault("DISPLAY", ":99")

errors = []

def check(name, cond):
    if not cond:
        errors.append(name)
        print("  FAIL: %s" % name)
    else:
        print("  OK:   %s" % name)

print("=" * 60)
print("transformed-win7 功能测试")
print("=" * 60)

# --- 1. 模块级函数 ---
print("\n[1] 模块级函数")
import main
check("_get_buvid3", hasattr(main, "_get_buvid3"))
check("search_bilibili_song", hasattr(main, "search_bilibili_song"))
check("get_ffmpeg_path", hasattr(main, "get_ffmpeg_path"))
check("download_ffmpeg", hasattr(main, "download_ffmpeg"))
check("log_msg", hasattr(main, "log_msg"))
check("log_read", hasattr(main, "log_read"))
check("_log_trim", hasattr(main, "_log_trim"))
check("_LOG_LOCK", hasattr(main, "_LOG_LOCK"))

# --- 2. History 类 ---
print("\n[2] History 类")
h = main.History()
check("History.load", callable(getattr(h, "load", None)))
check("History.save", callable(getattr(h, "save", None)))
check("History.add", callable(getattr(h, "add", None)))
check("History.clear", callable(getattr(h, "clear", None)))
check("History.items is list", isinstance(h.items, list))

# --- 3. App 类初始化 ---
print("\n[3] App 类关键属性/方法")
# 检查类定义中有关键方法
for method in [
    "_start_dl", "_start_queue", "_start_queue_worker",
    "_queue_worker", "_do_dl_item", "_queue_refresh_tree",
    "_queue_move", "_queue_retry_selected", "_queue_delete_selected",
    "_queue_clear", "_start_song_search", "_prepare_url",
    "_conv_mp4", "_conv_webp", "_conv_epub",
    "_history_delete_selected", "_history_refresh", "_history_clear",
    "_log_refresh", "_log_clear",
    "_open_output_folder", "_fmt_speed",
    "_on_url_focus_in", "_on_url_focus_out",
    "_set_url_placeholder", "_get_urls_from_text",
]:
    check("App.%s" % method, hasattr(main.App, method))

# --- 4. App 实例化（需要 X11 display）---
print("\n[4] App 实例化")
try:
    app = main.App()
    check("App() 创建成功", True)
    check("dl_queue 属性", hasattr(app, "dl_queue"))
    check("dl_queue_lock 属性", hasattr(app, "dl_queue_lock"))
    check("dl_queue_worker_running", hasattr(app, "dl_queue_worker_running"))
    check("dl_current_item", hasattr(app, "dl_current_item"))
    check("_dl_pct", hasattr(app, "_dl_pct"))
    check("url_text (Text widget)", hasattr(app, "url_text"))
    check("queue_tree", hasattr(app, "queue_tree"))
    check("song_var", hasattr(app, "song_var"))
    check("dl_total_label", hasattr(app, "dl_total_label"))
    check("dl_total_prog", hasattr(app, "dl_total_prog"))
    check("dl_prog", hasattr(app, "dl_prog"))
    check("dl_stat", hasattr(app, "dl_stat"))
    check("tree (history) selectmode=extended",
          str(app.tree.cget("selectmode")) == "extended")
    # 检查占位符
    content = app.url_text.get("1.0", "end").strip()
    check("URL 占位符已设置", "粘贴链接" in content)
    # 关闭窗口
    app.destroy()
except Exception as e:
    check("App() 实例化", False)
    print("    Exception: %s" % e)

# --- 5. _prepare_url 逻辑 ---
print("\n[5] _prepare_url 逻辑")
try:
    app = main.App()
    # BV号
    r = app._prepare_url("BV1xx411c7XH")
    check("BV号转换", "bilibili.com/video/BV1xx411c7XH" in r)
    # AV号
    r = app._prepare_url("av170001")
    check("AV号转换", "bilibili.com/video/av170001" in r)
    # 完整链接
    r = app._prepare_url("https://www.bilibili.com/video/BV1234567890")
    check("完整链接透传", "bilibili.com" in r)
    # b23短链
    r = app._prepare_url("b23.tv/abc123")
    check("b23短链", "https://b23.tv/abc123" in r)
    # 无协议域名
    r = app._prepare_url("youtube.com/watch?v=abc")
    check("无协议域名加https", r.startswith("https://"))
    app.destroy()
except Exception as e:
    check("_prepare_url 测试", False)
    print("    Exception: %s" % e)

# --- 6. 线程安全检查（代码审查） ---
print("\n[6] 代码审查：线程安全")
with open("main.py", "r", encoding="utf-8") as f:
    code = f.read()
# 检查 _do_convert 中的 UI 更新使用 after
check("_do_convert 使用 self.after",
      "self.after(0," in code.split("def _do_convert")[1].split("def _conv_epub")[0])
# 检查 _set_status 不再直接调用 update_idletasks
# _dl_ffmpeg_thread 中使用 after
check("_dl_ffmpeg_thread 使用 after",
      "self.after(0" in code.split("def _dl_ffmpeg_thread")[1].split("def _set_status")[0])
# 检查 _do_dl_item 使用 after
check("_do_dl_item 使用 after",
      "self.after(0" in code.split("def _do_dl_item")[1].split("def _queue_refresh_tree")[0])
# 检查 History 使用 encoding
check("History.load 使用 encoding=utf-8",
      'encoding="utf-8"' in code.split("class History")[1].split("class App")[0])
# 检查 History.save 使用 ensure_ascii
check("History.save 使用 ensure_ascii=False",
      "ensure_ascii=False" in code.split("class History")[1].split("class App")[0])
# 检查 _conv_mp4 检查 returncode
check("_conv_mp4 检查 returncode",
      "proc.returncode" in code.split("def _conv_mp4")[1].split("def _conv_webp")[0])
# 检查 _conv_mp4 检查输出文件存在
check("_conv_mp4 检查输出文件",
      "out.exists()" in code.split("def _conv_mp4")[1].split("def _conv_webp")[0])
# 检查日志锁
check("_LOG_LOCK 存在",
      "_LOG_LOCK = threading.Lock()" in code)
check("log_msg 使用 _LOG_LOCK",
      "with _LOG_LOCK" in code)
# 检查单调递增
check("单调递增进度 self._dl_pct = max(...",
      "self._dl_pct = max(self._dl_pct" in code)

# --- 总结 ---
print("\n" + "=" * 60)
if errors:
    print("FAILED: %d 项" % len(errors))
    for e in errors:
        print("  - %s" % e)
    sys.exit(1)
else:
    print("ALL PASSED")
    sys.exit(0)
