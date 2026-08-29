# -*- coding: utf-8 -*-
"""ffmpeg 查找、自动下载与辅助探测。"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import urllib.request as _urlreq

from app_common import Logger, _validated_output_file
from net_guard import guarded_urlopen


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


def safe_extractall(zf, dest):
    """防 Zip Slip：拒绝绝对路径或包含 .. 的压缩条目再解压。"""
    dest = Path(dest).resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            raise ValueError(f"压缩包内含非法路径，已拒绝解压: {member.filename}")
    zf.extractall(dest)


def download_ffmpeg(progress_cb=None):
    """自动下载 ffmpeg for Windows"""
    if os.name != "nt":
        return False, "ffmpeg 自动下载仅支持 Windows，请手动安装"

    url = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/"
           "latest/ffmpeg-master-latest-win64-gpl-shared.zip")

    dest = get_ffmpeg_dir()
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = _validated_output_file(dest / "ffmpeg.zip", dest)
    extract_dir = dest / "_extract"

    try:
        progress_cb and progress_cb("正在下载 ffmpeg (约30MB)...")
        # 带超时+进度+公网校验的流式下载，替代无超时、易永久卡死的 urlretrieve
        req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        buf = bytearray()
        with guarded_urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                if total:
                    progress_cb and progress_cb(
                        f"正在下载 ffmpeg... {len(buf) / 1048576:.1f}/{total / 1048576:.1f} MB")
        Path(zip_path).write_bytes(bytes(buf))

        progress_cb and progress_cb("正在解压...")
        with zipfile.ZipFile(zip_path) as z:
            # 解压到临时目录（防 Zip Slip），再移动 bin/ 内容
            extract_dir.mkdir(exist_ok=True)
            safe_extractall(z, extract_dir)

        # 找到 bin 目录（解压出来可能是 ffmpeg-master-latest-win64-gpl-shared/）
        bin_dir = None
        for d in extract_dir.iterdir():
            b = d / "bin"
            if b.exists():
                bin_dir = b
                break

        if not bin_dir:
            return False, "ffmpeg 压缩包结构异常，未找到 bin 目录"

        # 移动 ffmpeg.exe 到我们的 ffmpeg/bin/
        target = dest / "bin"
        target.mkdir(exist_ok=True)
        for f in bin_dir.iterdir():
            shutil.copy2(f, target / f.name)

        if not get_ffmpeg_path():
            return False, "ffmpeg 解压完成但未找到可执行文件"

        return True, str(get_ffmpeg_path())
    except Exception as e:
        return False, f"ffmpeg 下载失败: {e}"
    finally:
        # 无论成败都清理临时文件（半截 zip / 解压目录）
        shutil.rmtree(extract_dir, ignore_errors=True)
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass


def media_duration(ffmpeg, path, no_window=0):
    """用 ffprobe 读取媒体时长（秒），失败返回 None"""
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not ffprobe.exists():
        return None
    try:
        proc = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, shell=False, timeout=30,
            creationflags=no_window)
        return float(proc.stdout.decode("ascii", "replace").strip())
    except Exception:
        return None
