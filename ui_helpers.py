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


def compute_queue_move(n, selected, direction, blocked=()):
    """Compute a one-step queue move for a multi-selection.

    n:        total number of items.
    selected: indexes of items to move (each moves exactly one step).
    direction: -1 to move up, +1 to move down.
    blocked:  indexes that must not move and must not be crossed
              (e.g. the item currently downloading).

    Returns the new order as a list where order[position] = original index.
    Selected items keep their relative order; moves that would collide with
    another selected item, a blocked item, or the list edge are skipped.
    """
    order = list(range(n))
    pos = {item: p for p, item in enumerate(order)}
    sel = {i for i in selected if 0 <= i < n}
    # blocked 保持绝对语义：正在下载的项自己不动，别人也不能越过它
    blocked = {i for i in blocked if 0 <= i < n}

    # 向下时从最底下开始处理，向上时从最顶上开始处理，
    # 这样先处理的项目腾出的空位不会影响未处理项目的判断
    for item in sorted(sel, reverse=(direction > 0)):
        if item in blocked:
            continue
        p = pos[item]
        q = p + direction
        if not (0 <= q < n):
            continue
        other = order[q]
        if other in sel or other in blocked:
            continue
        order[p], order[q] = other, item
        pos[item], pos[other] = q, p
    return order
