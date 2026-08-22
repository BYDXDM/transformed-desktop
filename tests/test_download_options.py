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


class BilibiliDownloadOptionsTests(unittest.TestCase):
    def test_identifies_bilibili_url(self):
        self.assertTrue(is_bilibili_url("https://www.bilibili.com/video/BV1ktMr6CEUF"))
        self.assertFalse(is_bilibili_url("https://www.youtube.com/watch?v=test"))

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


if __name__ == "__main__":
    unittest.main()
