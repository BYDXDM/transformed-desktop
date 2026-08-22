"""Small UI-only helpers that can be tested without starting Tk."""

from threading import Lock


class UiProgressEventQueue:
    """Bounded, thread-safe latest-value mailbox keyed by UI update source."""

    def __init__(self):
        self._lock = Lock()
        self._events = {}

    def put(self, source, callback):
        # Replace stale work instead of allowing a high-frequency worker to build a backlog.
        with self._lock:
            self._events[source] = callback

    def take_all(self):
        with self._lock:
            events = self._events
            self._events = {}
        return events


class ProgressUpdateThrottle:
    """Limit UI progress redraw scheduling to a fixed interval."""

    def __init__(self, interval_seconds=0.1):
        self.interval_seconds = interval_seconds
        self._last_scheduled_at = None

    def should_schedule(self, now):
        if self._last_scheduled_at is None or now - self._last_scheduled_at >= self.interval_seconds:
            self._last_scheduled_at = now
            return True
        return False


def selected_history_ids(visible_ids):
    """Return all currently visible Treeview item ids for Select All."""
    return tuple(visible_ids)
