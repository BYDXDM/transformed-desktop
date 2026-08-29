import json
import tempfile
import unittest
from pathlib import Path

import main


class AppSettingsTests(unittest.TestCase):
    def setUp(self):
        # 设置文件固定写在主目录；测试时绕过目录校验并改用临时文件
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_validator = main._validated_output_file
        main._validated_output_file = lambda p, base: Path(p)

    def tearDown(self):
        main._validated_output_file = self._orig_validator

    def test_round_trip(self):
        p = self.tmp / "settings.json"
        s = main.AppSettings(path=p)
        s.set("dl_type", "mp3")
        s.set("output_dir", "D:/out")
        s2 = main.AppSettings(path=p)
        self.assertEqual(s2.get("dl_type"), "mp3")
        self.assertEqual(s2.get("output_dir"), "D:/out")

    def test_corrupted_file_falls_back_to_defaults(self):
        p = self.tmp / "settings.json"
        p.write_text("{broken json", encoding="utf-8")
        s = main.AppSettings(path=p)
        self.assertEqual(s.get("dl_type"), "mp4")
        self.assertEqual(s.get("theme"), "superhero")

    def test_unknown_keys_are_dropped(self):
        p = self.tmp / "settings.json"
        p.write_text(json.dumps({"hacker_key": "x", "theme": "flatly"}),
                     encoding="utf-8")
        s = main.AppSettings(path=p)
        self.assertEqual(s.data["theme"], "flatly")
        self.assertNotIn("hacker_key", s.data)


if __name__ == "__main__":
    unittest.main()
