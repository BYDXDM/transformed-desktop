"""Pure helpers for normalizing video URLs and configuring yt-dlp."""

from pathlib import Path
import re

_BILIBILI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36")


def prepare_url(value):
    """Normalize user input to a URL while supporting BV, AV and b23 links."""
    value = value.strip()
    if not value:
        return value

    url_match = re.search(r'(https?://[^\s<>"\'\]]+)', value, re.IGNORECASE)
    if url_match:
        return url_match.group(1).rstrip('，。！？、,.;!?')

    # BV 号：前后不能紧贴字母数字，避免误匹配长文本片段
    bvid_match = re.search(r'(?<![0-9A-Za-z])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])', value)
    if bvid_match:
        return f"https://www.bilibili.com/video/{bvid_match.group(1)}"

    # b23 短链可能出现在句子中间，用 search 而不是 match
    b23_match = re.search(r'(b23\.tv/[0-9A-Za-z]+)', value, re.IGNORECASE)
    if b23_match:
        return f"https://{b23_match.group(1)}"

    # AV 号：同样加词边界，避免 "brav123" 之类误伤
    avid_match = re.search(r'(?<![0-9A-Za-z])av(\d+)(?![0-9A-Za-z])', value, re.IGNORECASE)
    if avid_match:
        return f"https://www.bilibili.com/video/av{avid_match.group(1)}"

    if "." in value and re.search(r'\.[a-zA-Z]{2,}(/|$)', value):
        return "https://" + value
    return value


def is_bilibili_url(url):
    """Return whether a normalized URL is served by Bilibili."""
    lower_url = url.lower()
    return ("bilibili.com" in lower_url or "b23.tv" in lower_url
            or lower_url.startswith("bv") or lower_url.startswith("av"))


def build_download_options(url, is_mp3, output_dir, ffmpeg_path=None, progress_hook=None,
                           cookiefile=None, extra_headers=None):
    """Build yt-dlp options without performing network or filesystem I/O."""
    options = {
        "outtmpl": str(Path(output_dir) / "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        # yt-dlp 的断点续传参数名是 continuedl（"continue" 会被静默忽略）
        "continuedl": True,
        "skip_unavailable_fragments": True,
        "windowsfilenames": True,
        "noplaylist": True,
    }
    if progress_hook:
        options["progress_hooks"] = [progress_hook]

    if is_bilibili_url(url):
        headers = {"User-Agent": _BILIBILI_UA}
        # 额外请求头（如 buvid3 Cookie）仅合并进 B 站请求，防 412 风控
        if extra_headers:
            headers.update(extra_headers)
        options.update({
            "referer": "https://www.bilibili.com/",
            "http_headers": headers,
            "nocheckcertificate": False,
            "format": "ba/b" if is_mp3 else "bv*+ba/b",
        })
        if cookiefile:
            # 已登录时携带 Cookie，可下载更高清晰度（仅 B 站域名使用）
            options["cookiefile"] = str(cookiefile)
    elif is_mp3:
        options["format"] = "bestaudio/best"
    else:
        options["format"] = "bv*+ba/best"

    if not is_mp3:
        # 优先合并为 mp4（B站等 h264+aac 源），流不兼容时回退 mkv，
        # 避免 yt-dlp 默认把选了 MP4 的下载合并成 .mkv
        options["merge_output_format"] = "mp4/mkv"

    if ffmpeg_path:
        options["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

    if is_mp3:
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    return options
