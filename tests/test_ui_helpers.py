import unittest

from ui_helpers import ProgressUpdateThrottle, UiProgressEventQueue, selected_history_ids


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


if __name__ == "__main__":
    unittest.main()
