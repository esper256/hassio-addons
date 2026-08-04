"""Bridge subprocess/file logs into Home Assistant's Logs tab (container stdout)."""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections import deque

# CSI / OSC color codes emitted by many game consoles.
_ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|].*?(?:\x1b\\|\x07))")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences so logs are readable and regex-friendly."""

    return _ANSI_RE.sub("", text or "")


class FlushStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every record for near-realtime HA logs."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_logging(level: int) -> None:
    """Configure root logging to unbuffered stdout (HA add-on Logs tab)."""

    root = logging.getLogger()
    root.handlers.clear()
    handler = FlushStreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


class RecentLineDeduper:
    """Suppress duplicate log mirrors within a short window."""

    def __init__(self, maxlen: int = 64, ttl_seconds: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._entries: deque[tuple[float, str]] = deque(maxlen=maxlen)
        self._ttl = ttl_seconds

    @staticmethod
    def _normalize(line: str) -> str:
        return strip_ansi(line).strip()

    def remember_if_new(self, line: str) -> bool:
        """Return True if this line is new within the TTL window (and remember it)."""

        key = self._normalize(line)
        if not key:
            return False
        now = time.time()
        with self._lock:
            while self._entries and now - self._entries[0][0] > self._ttl:
                self._entries.popleft()
            if any(existing == key for _, existing in self._entries):
                return False
            self._entries.append((now, key))
            return True


# Shared across process stdout and file-log mirroring so HA Logs stay de-duplicated.
STDOUT_DEDUPER = RecentLineDeduper()
