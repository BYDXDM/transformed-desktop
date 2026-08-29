# -*- coding: utf-8 -*-
"""格式转换实现：EPUB→TXT、视频→MP3、图片→JPG。均为纯函数。"""
import os
import re
import subprocess
from html import unescape as _html_unescape
from pathlib import Path

from PIL import Image

from app_common import _validated_output_file
from ffmpeg_tools import get_ffmpeg_path, media_duration

try:
    from ebooklib import epub
    HAS_EBOOKLIB = True
except ImportError:
    HAS_EBOOKLIB = False


def conv_epub(path, out_dir, cb):
    if not HAS_EBOOKLIB:
        return False, "请安装: pip install ebooklib"
    try:
        cb(0.1, "读取 EPUB...")
        book = epub.read_epub(path)
        name = Path(path).stem
        out = _validated_output_file(Path(out_dir) / f"{name}.txt", out_dir)
        texts = []
        items = list(book.get_items_of_type(epub.ITEM_DOCUMENT))
        for i, item in enumerate(items):
            html = item.get_body_content().decode("utf-8", errors="replace")
            text = re.sub(r'<[^>]+>', ' ', html)
            text = _html_unescape(text)
            text = re.sub(r'\s+', ' ', text).strip()
            if text: texts.append(text)
            cb(0.1 + (i/len(items))*0.8, f"解析 {i+1}/{len(items)}")
        cb(0.9, "写入文件...")
        Path(out).write_text("\n\n".join(texts), encoding="utf-8")
        cb(1.0, "完成")
        return True, str(out)
    except Exception as e:
        return False, str(e)


def conv_mp4(path, out_dir, cb):
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return False, "未找到 ffmpeg，请重新启动程序并选择自动下载"
    # GUI(pythonw) 模式下防止 ffmpeg 弹出黑色控制台窗口
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        cb(0.05, "读取时长...")
        duration = media_duration(ffmpeg, path, no_window)
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


def conv_webp(path, out_dir, cb):
    try:
        cb(0.3, "解码...")
        img = Image.open(path)
        name = Path(path).stem
        out = _validated_output_file(Path(out_dir) / f"{name}.jpg", out_dir)
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
