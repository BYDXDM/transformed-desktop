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
TAG = "v1.7.0"
NAME = "transformed Desktop v1.7.0"
BODY = """## transformed Desktop v1.7.0

### 全新界面（Win10 Fluent 风格）
- 全套视觉重做：左侧导航栏（格式转换 / 视频下载 / 历史记录 / 运行日志）+ 系统强调蓝，方角按钮、细进度条、卡片式布局，更接近 Windows 10 原生观感
- 深色 / 浅色双主题，跟随切换深色标题栏；看板娘移入侧边栏常驻
- 支持 Segoe UI 字体与 Segoe MDL2 系统图标

### 下载可靠性修复
- 外网探测失败自动重试，且失败只短缓存 30 秒：代理出口轮换的瞬时抖动不再把 X/YouTube 下载挡住 10 分钟
- 下载中途遇到瞬时网络错误（代理断连/超时）自动重试一次，队列显示"重试中"，断点续传接着下

### 其他
- 修复点击"清空日志"报错的问题（_LOG_LOCK 未导入）
- exe 内置看板娘素材（此前版本打包遗漏）

### v1.6.x 修复回顾
- B站下载 412 风控：绕过网页直取 playurl API 解析 CDN 直链，失败自动回退
- 点击"开始下载"直接下载，无需先添加到队列；并行下载 / 拖拽导入 / B站扫码登录

### 使用方式
双击 transformed.exe 即可，无需 Python 环境。MP4转MP3 与部分视频合并需要 ffmpeg，程序可自动下载。Win7 用户请继续使用 win7 分支构建。
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
