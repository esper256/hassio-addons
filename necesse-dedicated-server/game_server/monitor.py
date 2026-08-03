"""Tail game logs and track players / version-mismatch signals."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .plugin import GamePlugin, LogPatterns

LOG = logging.getLogger("game_server.monitor")


@dataclass
class MonitorState:
    players: set[str] = field(default_factory=set)
    player_count: int = 0
    ready: bool = False
    version_mismatch_count: int = 0
    last_version_mismatch_at: float | None = None
    last_version_mismatch_line: str | None = None
    last_log_line: str | None = None
    recent_lines: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "players": sorted(self.players),
            "player_count": self.player_count if self.player_count or not self.players else len(self.players),
            "ready": self.ready,
            "version_mismatch_count": self.version_mismatch_count,
            "last_version_mismatch_at": self.last_version_mismatch_at,
            "last_version_mismatch_line": self.last_version_mismatch_line,
            "last_log_line": self.last_log_line,
            "uptime_seconds": int(time.time() - self.started_at),
        }


class LogMonitor:
    def __init__(
        self,
        plugin: GamePlugin,
        logs_dir: str | Path,
        on_version_mismatch: Callable[[str], None] | None = None,
    ) -> None:
        self.plugin = plugin
        self.logs_dir = Path(logs_dir)
        self.on_version_mismatch = on_version_mismatch
        self.state = MonitorState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._patterns = plugin.log_patterns
        self._join = [re.compile(p, re.I) for p in self._patterns.player_join]
        self._leave = [re.compile(p, re.I) for p in self._patterns.player_leave]
        self._mismatch = [re.compile(p, re.I) for p in self._patterns.version_mismatch]
        self._count = [re.compile(p, re.I) for p in self._patterns.player_count]
        self._ready = [re.compile(p, re.I) for p in self._patterns.ready]

    def reset_session(self) -> None:
        self.state = MonitorState()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="log-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _pick_log_file(self) -> Path | None:
        if not self.logs_dir.is_dir():
            return None
        candidates = sorted(
            [
                p
                for p in self.logs_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".log", ".txt", ""}
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        # Prefer names that look like latest/current
        for preferred in ("latest.log", "server.log", "console.log"):
            path = self.logs_dir / preferred
            if path.is_file():
                return path
        return candidates[0] if candidates else None

    def _run(self) -> None:
        current: Path | None = None
        handle = None
        inode = None
        try:
            while not self._stop.is_set():
                path = self._pick_log_file()
                if path is None:
                    time.sleep(1)
                    continue
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    time.sleep(1)
                    continue

                if handle is None or path != current or stat.st_ino != inode:
                    if handle:
                        handle.close()
                    try:
                        handle = path.open("r", encoding="utf-8", errors="replace")
                        # Follow from end for existing file; from start for brand-new
                        if current == path:
                            handle.seek(0, 2)
                        else:
                            handle.seek(0, 2)
                        current = path
                        inode = stat.st_ino
                        LOG.info("Monitoring log file %s", path)
                    except OSError:
                        handle = None
                        time.sleep(1)
                        continue

                line = handle.readline()
                if not line:
                    time.sleep(0.25)
                    continue
                self._handle_line(line.rstrip("\n"))
        finally:
            if handle:
                handle.close()

    def _handle_line(self, line: str) -> None:
        if not line.strip():
            return
        self.state.last_log_line = line
        self.state.recent_lines.append(line)

        for pattern in self._ready:
            if pattern.search(line):
                self.state.ready = True
                break

        for pattern in self._join:
            match = pattern.search(line)
            if match:
                name = match.groupdict().get("player") or (
                    match.group(1) if match.lastindex else None
                )
                if name:
                    self.state.players.add(name)
                    self.state.player_count = len(self.state.players)
                break

        for pattern in self._leave:
            match = pattern.search(line)
            if match:
                name = match.groupdict().get("player") or (
                    match.group(1) if match.lastindex else None
                )
                if name and name in self.state.players:
                    self.state.players.discard(name)
                self.state.player_count = len(self.state.players)
                break

        for pattern in self._count:
            match = pattern.search(line)
            if match:
                raw = match.groupdict().get("count") or (
                    match.group(1) if match.lastindex else None
                )
                if raw is not None:
                    try:
                        self.state.player_count = int(raw)
                    except ValueError:
                        pass
                break

        for pattern in self._mismatch:
            if pattern.search(line):
                self.state.version_mismatch_count += 1
                self.state.last_version_mismatch_at = time.time()
                self.state.last_version_mismatch_line = line
                LOG.warning("Version mismatch signal: %s", line)
                if self.on_version_mismatch:
                    try:
                        self.on_version_mismatch(line)
                    except Exception:  # noqa: BLE001
                        LOG.exception("version mismatch callback failed")
                break

    def ingest_stdout_line(self, line: str) -> None:
        """Also allow the process manager to feed stdout into the monitor."""
        self._handle_line(line)
