"""Pure helpers for normalizing video URLs and configuring yt-dlp."""

from pathlib import Path
import re

_BILIBILI_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def prepare_url(value):
    """Normalize user input to a URL while supporting BV, AV and b23 links."""
    value = value.strip()
    if not value:
        return value

    url_match = re.search(r'(https?://[^\s<>"\'\]]+)', value, re.IGNORECASE)
    if url_match:
        return url_match.group(1).rstrip('，。！？、,.;!?')

    bvid_match = re.search(r'(BV[0-9A-Za-z]{10})', value)
    if bvid_match:
        return f"https://www.bilibili.com/video/{bvid_match.group(1)}"

    avid_match = re.search(r'(av\d+)', value, re.IGNORECASE)
    if avid_match:
        return f"https://www.bilibili.com/video/{avid_match.group(1)}"

    b23_match = re.match(r'(b23\.tv/[0-9A-Za-z]+)', value, re.IGNORECASE)
    if b23_match:
        return f"https://{b23_match.group(1)}"

    if "." in value and re.search(r'\.[a-zA-Z]{2,}(/|$)', value):
        return "https://" + value
    return value


def is_bilibili_url(url):
    """Return whether a normalized URL is served by Bilibili."""
    lower_url = url.lower()
    return "bilibili.com" in lower_url or lower_url.startswith("bv") or lower_url.startswith("av")


def build_download_options(url, is_mp3, output_dir, ffmpeg_path=None, progress_hook=None):
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
        "continue": True,
        "skip_unavailable_fragments": True,
        "fragment_retries_base": 2,
        "windowsfilenames": True,
        "noplaylist": True,
    }
    if progress_hook:
        options["progress_hooks"] = [progress_hook]

    if is_bilibili_url(url):
        options.update({
            "referer": "https://www.bilibili.com/",
            "http_headers": {"User-Agent": _BILIBILI_UA},
            "nocheckcertificate": False,
            "format": "ba/b" if is_mp3 else "bv*+ba/b",
        })
    elif is_mp3:
        options["format"] = "bestaudio/best"
    else:
        options["format"] = "bv*+ba/best"

    if ffmpeg_path:
        options["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

    if is_mp3:
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    return options
