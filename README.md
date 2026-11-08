# transformed 桌面版

格式转换（EPUB→TXT、MP4→MP3、WebP→JPG）+ B站/YouTube/Twitter 视频下载的 Windows 桌面应用（Python + ttkbootstrap）。transformed 家族的桌面端主仓库。

## 快速开始（推荐）

双击 **run.pyw** 即可：
- 自动检查并安装依赖
- 自动启动程序
- 无需手动 pip install

## 手动运行

```bash
pip install -r requirements.txt
python main.py
```

## 可选：打包成 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name transformed ^
    --hidden-import ttkbootstrap ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import ebooklib ^
    --hidden-import yt_dlp ^
    --hidden-import mutagen ^
    --collect-all ttkbootstrap ^
    main.py
```

## 功能

- EPUB → TXT（批量）
- MP4 → MP3（批量，需要 ffmpeg）
- WebP → JPG（批量）
- B站 / YouTube / Twitter 视频下载

## 需要的依赖

- 当前 Windows：Python 3.10+（使用 `requirements.txt`）
- Windows 7 兼容构建：Python 3.8（使用固定的 `requirements-win7.txt`，功能依赖版本较旧）
- ffmpeg：https://ffmpeg.org/download.html
  - MP4 → MP3 转换需要 ffmpeg；
  - B 站等平台常提供分离的 DASH 视频/音频流，下载 MP4 时的合并也需要 ffmpeg；
  - 直接下载 MP3 时的音频转码同样需要 ffmpeg。

## 目录要点

- `main.py` — 主程序（单文件 UI，约 90KB）；`run.pyw` — 双击启动器（自动装依赖并启动）
- `bili_api.py` — B站 API（搜索、直连解析、扫码登录）；`ffmpeg_tools.py` / `converters.py` / `download_options.py` — 转换与下载核心
- `app_common.py` / `ui_style.py` / `ui_helpers.py` / `net_guard.py` — 公共逻辑、Fluent 主题、网络防护
- `tests/` — 离线单测（pytest）；`transformed_output/` — 默认输出目录
- `dist/` — 本地 PyInstaller 打包产物（`transformed.exe` 约 47MB + 内置 ffmpeg，可重建；2026-11-07 盘点时仍在）
- `.github/workflows/` — `build-exe.yml`（main → Win10 exe）、`build-win7.yml`（win7 分支 → Win7 exe）

## 多端家族

- Android 端：`../transfromed-android-fixed/`（remote `BYDXDM/transfromed`，Kotlin/Compose，v1.4.1，活跃）
- Win7 兼容版：`win7` 分支（Python 3.8 + `requirements-win7.txt` 固定旧依赖）构建，产物存于 `../win7-new/transformed-win7.exe`

## 当前状态与断点

- main 分支 v1.7.0（最后提交 2026-10-25）：Fluent/磁贴风 UI 大修 + 下载可靠性修复；工作区干净，无未推送内容
- 桌面端自 2026-10-25 起处于稳定待用状态，后续开发主力在 Android 端（2026-11-07 仍有提交）

## 注意事项

- 发布脚本 `upload_release.py` / `upload_asset.py` 从环境变量 `GITHUB_TOKEN` 读凭据（或运行时交互输入），仓库内无硬编码密钥
- ffmpeg 首次运行自动下载；B站下载靠 API 直连解析绕过网页风控（412 修复），风控升级时优先查 `bili_api.py`
