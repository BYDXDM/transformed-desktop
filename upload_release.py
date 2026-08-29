"""创建 GitHub Release 并上传 transformed.exe"""
import json
import urllib.request
import urllib.error
import sys
import os

from net_guard import guarded_urlopen

REPO = "BYDXDM/transformed-desktop"
EXE = "dist/transformed.exe"
TAG = "v1.4.4"
NAME = "transformed Desktop v1.4.4"
BODY = """## transformed Desktop v1.4.4

### Bug 修复
- 歌曲搜索（YouTube 兜底）下载后文件名/历史记录路径错误
- 选择 MP4 下载时 B站视频被合并成 .mkv，现固定优先输出 .mp4
- 断点续传参数无效导致大文件无法续传
- 句子中间粘贴的 b23.tv 短链无法识别；BV/AV 号解析误判
- 下载队列多选上移/下移顺序错乱；下载过程中无法选中行
- 历史记录并发写入可能损坏 JSON；旧版本损坏记录导致崩溃
- ffmpeg 自动下载无超时可能永久卡死；失败后残留临时文件
- URL 占位符文字在窗口切换后被当作链接提交
- 关闭窗口瞬间偶发报错；GUI 模式下 ffmpeg 转换闪黑色控制台

### 优化
- 启动提速：yt-dlp 升级检查改为每 24 小时一次（此前每次启动都联网）
- 外网检测结果缓存 10 分钟，批量下载 YouTube/X 不再逐个等待探测
- 下载队列状态中文化（等待中/下载中/完成/失败/重试中）
- 双击失败项查看错误详情，双击完成项直接打开文件
- "添加到队列"支持跨批次去重，行为与按钮语义一致

### UI
- 统一微软雅黑字体、卡片式分组框、标题栏/状态栏分隔线
- 条纹进度条、窗口图标等细节美化

### 安全
- 动态路径写入增加目录限定校验；zip 解压防路径穿越
- 网络请求统一公网地址校验（含重定向）

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
