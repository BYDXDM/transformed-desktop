import unittest

from ui_helpers import (
    ProgressUpdateThrottle,
    UiProgressEventQueue,
    compute_queue_move,
    is_newer_version,
    parse_drop_list,
    selected_history_ids,
)


class ProgressUpdateThrottleTests(unittest.TestCase):
    def test_first_update_is_allowed(self):
        throttle = ProgressUpdateThrottle(interval_seconds=0.1)

        self.assertTrue(throttle.should_schedule(now=1.0))

    def test_updates_inside_interval_are_coalesced(self):
        throttle = ProgressUpdateThrottle(interval_seconds=0.1)
        self.assertTrue(throttle.should_schedule(now=1.0))
        self.assertFalse(throttle.should_schedule(now=1.05))
        self.assertTrue(throttle.should_schedule(now=1.10))


class UiProgressEventQueueTests(unittest.TestCase):
    def test_keeps_only_latest_event_for_each_source(self):
        events = UiProgressEventQueue()
        events.put("download", "old")
        events.put("conversion", "convert")
        events.put("download", "new")

        self.assertEqual(events.take_all(), {"download": "new", "conversion": "convert"})

    def test_take_all_clears_drained_events(self):
        events = UiProgressEventQueue()
        events.put("download", "progress")
        events.take_all()

        self.assertEqual(events.take_all(), {})

    def test_replaces_pending_callback_without_a_backlog(self):
        events = UiProgressEventQueue()
        for value in range(1_000):
            events.put("download", value)

        self.assertEqual(events.take_all(), {"download": 999})


class HistorySelectionTests(unittest.TestCase):
    def test_returns_all_visible_history_ids_in_display_order(self):
        self.assertEqual(selected_history_ids(("8", "3", "1")), ("8", "3", "1"))

    def test_empty_visible_rows_returns_empty_selection(self):
        self.assertEqual(selected_history_ids(()), ())


class IsNewerVersionTests(unittest.TestCase):
    def test_detects_newer_version(self):
        self.assertTrue(is_newer_version("v1.5.0", "v1.4.4"))
        self.assertTrue(is_newer_version("v1.4.5", "v1.4.4"))
        self.assertTrue(is_newer_version("2.0", "v1.9.9"))

    def test_same_or_older_is_not_newer(self):
        self.assertFalse(is_newer_version("v1.4.4", "v1.4.4"))
        self.assertFalse(is_newer_version("v1.4.3", "v1.4.4"))
        self.assertFalse(is_newer_version("v1.3", "v1.4.4"))

    def test_unparsable_versions_do_not_trigger_update(self):
        self.assertFalse(is_newer_version("", "v1.4.4"))
        self.assertFalse(is_newer_version("unknown", "v1.4.4"))
        self.assertFalse(is_newer_version(None, "v1.4.4"))

    def test_short_versions_pad_for_comparison(self):
        self.assertTrue(is_newer_version("v1.5", "v1.4.9"))
        self.assertFalse(is_newer_version("v1", "v1.0.1"))


class ParseDropListTests(unittest.TestCase):
    def test_bare_paths_preserve_backslashes(self):
        # Tcl splitlist 会把 \a \t 当转义符；这里必须原样保留
        self.assertEqual(
            parse_drop_list(r"D:\ai\test\drop_demo.png"),
            [r"D:\ai\test\drop_demo.png"],
        )

    def test_braced_paths_with_spaces(self):
        self.assertEqual(
            parse_drop_list("{C:/my files/a b.mp4} {D:/x.epub}"),
            ["C:/my files/a b.mp4", "D:/x.epub"],
        )

    def test_mixed_files_and_links(self):
        self.assertEqual(
            parse_drop_list(r"D:\ai\书.epub https://b23.tv/abc123"),
            [r"D:\ai\书.epub", "https://b23.tv/abc123"],
        )

    def test_empty_and_multiple_spaces(self):
        self.assertEqual(parse_drop_list("   "), [])
        self.assertEqual(parse_drop_list("  a   b  "), ["a", "b"])
        self.assertEqual(parse_drop_list(""), [])


class ComputeQueueMoveTests(unittest.TestCase):
    """queue_move 返回 order 列表，order[位置] = 原条目编号"""

    def test_single_item_moves_down(self):
        # [A,B,C] 选中 0 下移 → [B,A,C]
        self.assertEqual(compute_queue_move(3, [0], +1), [1, 0, 2])

    def test_single_item_moves_up(self):
        # [A,B,C] 选中 2 上移 → [A,C,B]
        self.assertEqual(compute_queue_move(3, [2], -1), [0, 2, 1])

    def test_move_at_edge_is_noop(self):
        self.assertEqual(compute_queue_move(3, [0], -1), [0, 1, 2])
        self.assertEqual(compute_queue_move(3, [2], +1), [0, 1, 2])

    def test_multi_selection_down_keeps_relative_order(self):
        # 旧实现 [0,1] 下移会得到 [B,C,A]；正确语义是整块下移 [C,A,B]
        self.assertEqual(compute_queue_move(3, [0, 1], +1), [2, 0, 1])

    def test_multi_selection_up_is_noop_when_at_top(self):
        # 旧实现会把选中的两条互相交换；顶部上移应原地不动
        self.assertEqual(compute_queue_move(3, [0, 1], -1), [0, 1, 2])

    def test_scattered_selection_each_moves_one_step(self):
        # [A,B,C,D,E] 选中 2、4 下移 → C 到 3，E 到不了 5，保持 [A,B,D,C,E]
        self.assertEqual(compute_queue_move(5, [2, 4], +1), [0, 1, 3, 2, 4])

    def test_downloading_item_is_never_crossed(self):
        # [A,B,C] 选中 0（待移动），1 正在下载 → 0 无法越过 1
        self.assertEqual(compute_queue_move(3, [0], +1, blocked=[1]), [0, 1, 2])

    def test_downloading_item_itself_does_not_move(self):
        self.assertEqual(compute_queue_move(3, [1], +1, blocked=[1]), [0, 1, 2])

    def test_out_of_range_indexes_are_ignored(self):
        self.assertEqual(compute_queue_move(2, [0, 5, -1], +1), [1, 0])


if __name__ == "__main__":
    unittest.main()
