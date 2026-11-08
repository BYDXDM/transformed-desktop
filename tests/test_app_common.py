import unittest

from app_common import sanitize_windows_filename


class SanitizeWindowsFilenameTests(unittest.TestCase):
    def test_replaces_illegal_and_control_chars(self):
        # 9 个保留符号与控制字符都替换为下划线，其余原样保留
        self.assertEqual(
            sanitize_windows_filename('a/b\\c:d*e?f"g<h>i|j\x00\x1f\x7f'),
            "a_b_c_d_e_f_g_h_i_j___",
        )

    def test_strips_trailing_dots_and_spaces(self):
        # Windows 会静默剥掉结尾的点与空格，导致记录名与实际文件名不符
        self.assertEqual(sanitize_windows_filename("标题...  "), "标题")
        # 截断恰好断在点/空格上时同样要剥
        self.assertEqual(sanitize_windows_filename("abc. ..", max_len=5), "abc")

    def test_reserved_device_names_get_underscore_prefix(self):
        # CON.mp3 在 Windows 上同样是保留名，主干命中即加前缀；大小写不敏感
        self.assertEqual(sanitize_windows_filename("CON"), "_CON")
        self.assertEqual(sanitize_windows_filename("com1.mp4"), "_com1.mp4")
        self.assertEqual(sanitize_windows_filename("LPT9"), "_LPT9")
        # 保留名只是前缀命中不算：CONcert 是普通文件名
        self.assertEqual(sanitize_windows_filename("CONcert"), "CONcert")

    def test_truncates_by_utf16_units_without_splitting_surrogate_pair(self):
        # 截断上限按 UTF-16 编码单元计（Windows 路径长度的计数方式）
        self.assertEqual(len(sanitize_windows_filename("测" * 300, max_len=100)), 100)
        # emoji 占 2 个单元：81 个单元会切在代理对中间，应丢弃残留高代理
        emoji_title = "😀" * 80
        cut = sanitize_windows_filename(emoji_title, max_len=81)
        self.assertEqual(len(cut.encode("utf-16-le")) // 2, 80)
        cut.encode("utf-8")  # 不含孤立代理，否则这里抛 UnicodeEncodeError

    def test_empty_result_falls_back(self):
        # 全部由可剥除/可替换字符构成时清洗结果为空，交给调用方的兜底名
        self.assertEqual(sanitize_windows_filename("", fallback="bilibili"), "bilibili")
        self.assertEqual(sanitize_windows_filename(" . ", fallback="bilibili"), "bilibili")
        self.assertEqual(sanitize_windows_filename("正常标题"), "正常标题")


if __name__ == "__main__":
    unittest.main()
