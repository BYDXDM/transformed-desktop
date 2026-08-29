"""创建 GitHub Release 并上传 transformed.exe"""
import json
import urllib.request
import urllib.error
import sys
import os

from net_guard import guarded_urlopen

REPO = "BYDXDM/transformed-desktop"
EXE = "dist/transformed.exe"
TAG = "v1.3.0"
NAME = "transformed Desktop v1.3.0"
BODY = """## transformed Desktop v1.3.0

### 新功能：下载队列（批量下载）
- 多行链接输入框：支持粘贴多个链接（每行一个），一次性添加到队列
- 下载队列面板：显示所有下载项（状态图标：○等待 ▶下载中 ✓完成 ✗失败）
- 上移/下移排序：调整队列中的下载顺序
- 失败重试：选中失败项右键或按钮即可重试
- 打开输出文件夹：一键打开下载目录
- 右键菜单 + Delete 键删除队列项
- 歌曲搜索结果自动加入队列
- 队列自动逐项执行，全部完成后停止

### Bug 修复
- 修复占位符文字被当成 URL 添加到队列

### 之前的更新（v1.2.0）
- B站搜索 412 风控修复 / B站MP3真正转码 / 弹窗NameError / 线程安全 / 进度条 / 日志存储 / 历史记录删除 / 鲸鱼娘二次元UI

### 使用方式
双击 transformed.exe 即可，无需 Python 环境。
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

    # 1. 创建 Release
    data = json.dumps({"tag_name": TAG, "name": NAME, "body": BODY, "draft": False, "prerelease": False}).encode()
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
