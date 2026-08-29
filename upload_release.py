"""创建 GitHub Release 并上传 transformed.exe"""
import json
import urllib.request
import urllib.error
import sys
import os

from net_guard import guarded_urlopen

REPO = "BYDXDM/transformed-desktop"
# 发布始终从 master 切 tag；不指定的话 GitHub 会把新 tag 打在默认分支 HEAD 上
BRANCH = "master"
EXE = "dist/transformed.exe"
TAG = "v1.6.2"
NAME = "transformed Desktop v1.6.2"
BODY = """## transformed Desktop v1.6.2

### 交互优化
- ▶ **点击"开始下载"直接下载**：输入框粘贴链接后一键开始，无需先点"添加到队列"
- "添加到队列"保留：只入队不启动，适合攒一批再下载
- 队列已有任务时，新输入的链接会自动追加一起下载

### v1.6.1 修复回顾
- B站下载 412 风控：绕过网页直取 playurl API 解析 CDN 直链，失败自动回退
- yt-dlp 升级 2026.8.19；B站请求携带 buvid3 + 完整 Chrome UA

### 使用方式
双击 transformed.exe 即可，无需 Python 环境。MP4转MP3 与部分视频合并需要 ffmpeg，程序可自动下载。
"""

def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        token = input("请输入 GitHub Personal Access Token: ").strip()
    if not token:
        print("未提供 Token，退出")
        sys.exit(1)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "transformed-upload",
    }

    # 1. 创建 Release（target_commitish 确保 tag 落在 master HEAD）
    data = json.dumps({"tag_name": TAG, "target_commitish": BRANCH,
                       "name": NAME, "body": BODY, "draft": False, "prerelease": False}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases",
        data=data, headers=headers, method="POST"
    )
    try:
        with guarded_urlopen(req) as r:
            release = json.loads(r.read())
            upload_url = release["upload_url"].split("{")[0]
            print(f"Release created: {release['html_url']}")
    except urllib.error.HTTPError as e:
        print(f"ERROR: {e.code} {e.read().decode()}")
        sys.exit(1)

    # 2. 上传 exe
    exe_path = os.path.join(os.path.dirname(__file__), EXE)
    if not os.path.exists(exe_path):
        print(f"File not found: {exe_path}")
        sys.exit(1)

    size_mb = os.path.getsize(exe_path) / 1024 / 1024
    print(f"Uploading transformed.exe ({size_mb:.1f} MB)...")

    with open(exe_path, "rb") as f:
        upload_req = urllib.request.Request(
            f"{upload_url}?name=transformed.exe",
            data=f.read(),
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
            },
            method="POST"
        )
        try:
            with guarded_urlopen(upload_req, timeout=300) as r:
                asset = json.loads(r.read())
                print(f"Upload OK: {asset['browser_download_url']}")
        except urllib.error.HTTPError as e:
            print(f"Upload FAILED: {e.code} {e.read().decode()}")
            sys.exit(1)

    print(f"\n=== DONE! Download: https://github.com/{REPO}/releases/tag/{TAG} ===")

if __name__ == "__main__":
    main()
