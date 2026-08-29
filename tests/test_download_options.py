import unittest
from pathlib import Path

from download_options import build_download_options, is_bilibili_url, prepare_url


class PrepareUrlTests(unittest.TestCase):
    def test_normalizes_bv_identifier(self):
        self.assertEqual(
            prepare_url("请下载 BV1ktMr6CEUF 谢谢"),
            "https://www.bilibili.com/video/BV1ktMr6CEUF",
        )

    def test_normalizes_b23_short_link(self):
        self.assertEqual(
            prepare_url("b23.tv/abc123"),
            "https://b23.tv/abc123",
        )

    def test_normalizes_b23_short_link_mid_sentence(self):
        # b23 短链可能出现在句子中间，不能只匹配行首
        self.assertEqual(
            prepare_url("看这个 b23.tv/abc123 挺好"),
            "https://b23.tv/abc123",
        )

    def test_b23_wins_over_inner_av_number(self):
        self.assertEqual(
            prepare_url("b23.tv/abc123 和 av170001"),
            "https://b23.tv/abc123",
        )

    def test_av_number_requires_word_boundary(self):
        self.assertEqual(
            prepare_url("下载 av170001 谢谢"),
            "https://www.bilibili.com/video/av170001",
        )
        # "have123" 内含 "av" 但不是 AV 号，不应误判
        self.assertNotIn("bilibili", prepare_url("have123"))

    def test_full_url_strips_trailing_punctuation(self):
        self.assertEqual(
            prepare_url("https://www.bilibili.com/video/BV1ktMr6CEUF。"),
            "https://www.bilibili.com/video/BV1ktMr6CEUF",
        )


class BilibiliDownloadOptionsTests(unittest.TestCase):
    def test_identifies_bilibili_url(self):
        self.assertTrue(is_bilibili_url("https://www.bilibili.com/video/BV1ktMr6CEUF"))
        self.assertFalse(is_bilibili_url("https://www.youtube.com/watch?v=test"))

    def test_identifies_b23_short_link_as_bilibili(self):
        # b23 短链同样需要 B 站专属的 Referer/UA/格式策略
        self.assertTrue(is_bilibili_url("https://b23.tv/abc123"))

    def test_uses_video_and_audio_streams_for_bilibili_video(self):
        options = build_download_options(
            "https://www.bilibili.com/video/BV1ktMr6CEUF",
            is_mp3=False,
            output_dir=Path("downloads"),
            ffmpeg_path=None,
        )

        self.assertEqual(options["format"], "bv*+ba/b")
        self.assertEqual(options["referer"], "https://www.bilibili.com/")
        self.assertNotIn("postprocessors", options)

    def test_merges_video_download_to_mp4(self):
        # 选了 MP4 就应优先合并为 mp4，而不是 yt-dlp 默认的 mkv
        options = build_download_options(
            "https://www.bilibili.com/video/BV1ktMr6CEUF",
            is_mp3=False,
            output_dir=Path("downloads"),
            ffmpeg_path=None,
        )

        self.assertEqual(options["merge_output_format"], "mp4/mkv")

    def test_uses_continuedl_for_resume(self):
        # yt-dlp 的断点续传参数名是 continuedl；"continue" 会被静默忽略
        options = build_download_options(
            "https://www.bilibili.com/video/BV1ktMr6CEUF",
            is_mp3=False,
            output_dir=Path("downloads"),
            ffmpeg_path=None,
        )

        self.assertTrue(options["continuedl"])
        self.assertNotIn("continue", options)
        self.assertNotIn("fragment_retries_base", options)

    def test_uses_audio_and_ffmpeg_for_bilibili_mp3(self):
        options = build_download_options(
            "https://www.bilibili.com/video/BV1ktMr6CEUF",
            is_mp3=True,
            output_dir=Path("downloads"),
            ffmpeg_path=r"C:\ffmpeg\bin\ffmpeg.exe",
        )

        self.assertEqual(options["format"], "ba/b")
        self.assertEqual(options["ffmpeg_location"], r"C:\ffmpeg\bin")
        self.assertEqual(options["postprocessors"][0]["key"], "FFmpegExtractAudio")

    def test_omits_ffmpeg_location_when_not_found(self):
        options = build_download_options(
            "https://www.bilibili.com/video/BV1ktMr6CEUF",
            is_mp3=True,
            output_dir=Path("downloads"),
            ffmpeg_path=None,
        )

        self.assertNotIn("ffmpeg_location", options)

    def test_no_merge_format_for_audio_only(self):
        # 纯音频走 FFmpegExtractAudio 后处理器，无需 merge_output_format
        options = build_download_options(
            "https://www.youtube.com/watch?v=test",
            is_mp3=True,
            output_dir=Path("downloads"),
            ffmpeg_path=None,
        )

        self.assertNotIn("merge_output_format", options)


if __name__ == "__main__":
    unittest.main()
