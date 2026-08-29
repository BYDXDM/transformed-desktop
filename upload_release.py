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
TAG = "v1.6.0"
NAME = "transformed Desktop v1.6.0"
BODY = """## transformed Desktop v1.6.0

### 新功能
- ⚡ 并行下载：下载队列支持 1~3 并发（默认 2），批量下载更快，底部进度条为聚合进度
- 🖱 拖拽导入：把文件拖进窗口自动进入对应转换卡片（EPUB/视频/图片），拖入链接自动进下载框
- 🔑 B站扫码登录：用 B 站 APP 扫码后，B 站视频可下载更高清晰度；登录凭据仅保存在本机，一键可退出
- 🎵 MP4 转 MP3 显示真实转换进度

### v1.5.0 功能回顾
- 设置持久化（输出目录/格式/主题）、剪贴板一键粘贴、深浅色主题切换、双击历史打开文件、静默检查更新

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
