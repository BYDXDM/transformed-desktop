# transformed 桌面版

格式转换 + 视频下载工具（Python 桌面应用）

## 快速开始（推荐）

双击 **run.pyw** 即可：
- 自动检查并安装可选依赖
- 自动启动程序
- 依赖安装失败时仍可进入主界面；安装依赖后重启程序即可启用对应功能
- 无需手动 pip install

## 手动运行

```bash
pip install pillow yt-dlp mutagen ebooklib
python main.py
```

## 可选：打包成 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name transformed ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import ebooklib ^
    --hidden-import yt_dlp ^
    --hidden-import mutagen ^
    main.py
```

## 功能

- EPUB → TXT（批量）
- MP4 → MP3（批量，需要 ffmpeg）
- WebP → JPG（批量）
- B站 / YouTube / Twitter 视频下载

## 需要的依赖

- Python 3.8+
- ffmpeg（MP4→MP3 用）：https://ffmpeg.org/download.html
