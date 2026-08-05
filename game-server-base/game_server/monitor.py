"""Tail game logs; active patterns trigger events, candidates stay dry-run."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .log_bridge import STDOUT_DEDUPER, strip_ansi
from .patterns import DEFAULT_CANDIDATE_PATTERNS
from .plugin import PLAYER_TRACKING_PRESENCE, GamePlugin

LOG = logging.getLogger("game_server.monitor")


@dataclass
class PatternStat:
    category: str
    pattern: str
    mode: str  # "active" | "dry_run"
    hits: int = 0
    first_hit_at: float | None = None
    last_hit_at: float | None = None
    last_line: str | None = None
    # Newest last; Ingress shows up to these recent hits per regex.
    recent_lines: deque[str] = field(default_factory=lambda: deque(maxlen=5))

    def note(self, line: str) -> None:
        now = time.time()
        self.hits += 1
        if self.first_hit_at is None:
            self.first_hit_at = now
        self.last_hit_at = now
        self.last_line = line
        self.recent_lines.append(line)

    def to_dict(self) -> dict[str, Any]:
        stale = False
        if self.hits > 0 and self.last_hit_at is not None:
            # Previously useful pattern with no hits for 6h while server runs.
            stale = (time.time() - self.last_hit_at) > 6 * 3600
        return {
            "category": self.category,
            "pattern": self.pattern,
            "mode": self.mode,
            "hits": self.hits,
            "first_hit_at": self.first_hit_at,
            "last_hit_at": self.last_hit_at,
            "last_line": self.last_line,
            "recent_lines": list(self.recent_lines),
            "stale": stale,
        }


@dataclass
class MonitorState:
    players: set[str] = field(default_factory=set)
    player_count: int | None = None
    players_known: bool = False
    ready: bool = False
    # Human-readable game version announced in logs (e.g. "1.3.1").
    game_version: str | None = None
    game_version_seen_at: float | None = None
    game_version_line: str | None = None
    version_mismatch_count: int = 0
    last_version_mismatch_at: float | None = None
    last_version_mismatch_line: str | None = None
    last_log_line: str | None = None
    recent_lines: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    # Recent lines that matched any pattern (active or dry-run), newest last.
    highlighted_lines: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=80)
    )
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        count = len(self.players) if self.players else self.player_count
        return {
            "players": sorted(self.players),
            "player_count": count,
            # True when at least one player is known to be online (count or set).
            "players_present": (
                bool(self.players)
                if self.players
                else (None if count is None else int(count) > 0)
            ),
            "players_known": self.players_known,
            "ready": self.ready,
            "game_version": self.game_version,
            "game_version_seen_at": self.game_version_seen_at,
            "game_version_line": self.game_version_line,
            "version_mismatch_count": self.version_mismatch_count,
            "last_version_mismatch_at": self.last_version_mismatch_at,
            "last_version_mismatch_line": self.last_version_mismatch_line,
            "last_log_line": self.last_log_line,
            "highlighted_lines": list(self.highlighted_lines),
            "uptime_seconds": int(time.time() - self.started_at),
        }


@dataclass
class _CompiledPattern:
    category: str
    pattern: str
    mode: str
    regex: re.Pattern[str]
    stat: PatternStat


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
        self._compiled: list[_CompiledPattern] = []
        self._stats: dict[tuple[str, str, str], PatternStat] = {}
        self._build_patterns()

    def _build_patterns(self) -> None:
        active = plugin_patterns_as_dict(self.plugin)
        candidates = merge_candidates(
            DEFAULT_CANDIDATE_PATTERNS,
            self.plugin.log_pattern_candidates,
        )

        for category, patterns in active.items():
            for pattern in patterns:
                self._add_compiled(category, pattern, "active")

        for category, patterns in candidates.items():
            for pattern in patterns:
                # Don't duplicate an identical active pattern as dry-run.
                if pattern in active.get(category, []):
                    continue
                self._add_compiled(category, pattern, "dry_run")

        if not self.player_tracking_enabled:
            LOG.warning(
                "No active player log patterns configured; updates will not wait "
                "for an empty server. Dry-run candidates will only highlight lines."
            )
        if not self.version_mismatch_enabled:
            LOG.info(
                "No active version-mismatch patterns; mismatch will not trigger updates."
            )

    def _add_compiled(self, category: str, pattern: str, mode: str) -> None:
        key = (mode, category, pattern)
        if key in self._stats:
            return
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            LOG.error("Invalid %s pattern for %s (%s): %s", mode, category, pattern, exc)
            return
        stat = PatternStat(category=category, pattern=pattern, mode=mode)
        self._stats[key] = stat
        self._compiled.append(
            _CompiledPattern(
                category=category,
                pattern=pattern,
                mode=mode,
                regex=regex,
                stat=stat,
            )
        )

    @property
    def player_tracking_enabled(self) -> bool:
        active = plugin_patterns_as_dict(self.plugin)
        return bool(
            active.get("player_join")
            or active.get("player_leave")
            or active.get("player_count")
            or active.get("players_empty")
        )

    @property
    def player_tracking_mode(self) -> str:
        return str(getattr(self.plugin, "player_tracking_mode", "count") or "count")

    @property
    def presence_tracking(self) -> bool:
        return self.player_tracking_mode == PLAYER_TRACKING_PRESENCE

    @property
    def version_mismatch_enabled(self) -> bool:
        return bool(plugin_patterns_as_dict(self.plugin).get("version_mismatch"))

    def reset_session(self) -> None:
        """Reset per-session player/ready state; keep cumulative pattern stats."""
        highlighted = self.state.highlighted_lines
        recent = self.state.recent_lines
        self.state = MonitorState()
        # Keep a little continuity in the UI across restarts.
        self.state.highlighted_lines = highlighted
        self.state.recent_lines = recent

    def pattern_report(self) -> dict[str, Any]:
        stats = [stat.to_dict() for stat in self._stats.values()]
        stats.sort(
            key=lambda item: (
                0 if item["mode"] == "active" else 1,
                item["category"],
                -(item["hits"] or 0),
                item["pattern"],
            )
        )
        return {
            "player_tracking_enabled": self.player_tracking_enabled,
            "version_mismatch_enabled": self.version_mismatch_enabled,
            "active_pattern_count": sum(1 for s in stats if s["mode"] == "active"),
            "dry_run_pattern_count": sum(1 for s in stats if s["mode"] == "dry_run"),
            "patterns": stats,
            "recent_highlights": list(self.state.highlighted_lines)[-40:],
        }

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
                self._handle_line(line.rstrip("\n"), source="file")
        finally:
            if handle:
                handle.close()

    def _handle_line(self, line: str, *, source: str = "file") -> None:
        line = strip_ansi(line)
        if not line.strip():
            return
        # File-only lines never appear on process stdout; mirror them into HA Logs.
        # Lines already emitted as [game] from process stdout are skipped via dedupe.
        if source == "file" and STDOUT_DEDUPER.remember_if_new(line):
            LOG.info("[game-log] %s", line)
        self.state.last_log_line = line
        self.state.recent_lines.append(line)

        matched_meta: list[dict[str, str]] = []
        active_hits: dict[str, re.Match[str]] = {}

        for item in self._compiled:
            match = item.regex.search(line)
            if not match:
                continue
            item.stat.note(line)
            matched_meta.append(
                {
                    "mode": item.mode,
                    "category": item.category,
                    "pattern": item.pattern,
                }
            )
            if item.mode == "active" and item.category not in active_hits:
                active_hits[item.category] = match

        if matched_meta:
            self.state.highlighted_lines.append(
                {
                    "ts": time.time(),
                    "line": line,
                    "matches": matched_meta,
                }
            )

        # Only active patterns mutate runtime state / fire callbacks.
        if "ready" in active_hits:
            self.state.ready = True

        if "player_join" in active_hits:
            match = active_hits["player_join"]
            name = match.groupdict().get("player") or (
                match.group(1) if match.lastindex else None
            )
            if name:
                self.state.players.add(str(name).strip())
            self.state.players_known = True
            if self.presence_tracking:
                # Occupied — exact headcount unknown / unused.
                self.state.player_count = max(1, len(self.state.players))
            else:
                self.state.player_count = len(self.state.players)

        if "player_leave" in active_hits:
            match = active_hits["player_leave"]
            name = match.groupdict().get("player") or (
                match.group(1) if match.lastindex else None
            )
            removed = False
            cleaned = str(name).strip() if name else ""
            if cleaned and cleaned in self.state.players:
                self.state.players.discard(cleaned)
                removed = True
            self.state.players_known = True
            if self.presence_tracking:
                if self.state.players:
                    self.state.player_count = len(self.state.players)
                elif removed:
                    # Last tracked name left → idle.
                    self.state.player_count = 0
                # Unknown leave name: keep prior occupancy until players_empty.
            else:
                self.state.player_count = len(self.state.players)

        if "players_empty" in active_hits:
            self.state.players.clear()
            self.state.player_count = 0
            self.state.players_known = True

        if "player_count" in active_hits:
            match = active_hits["player_count"]
            raw = match.groupdict().get("count") or (
                match.group(1) if match.lastindex else None
            )
            if raw is not None:
                try:
                    self.state.player_count = int(raw)
                    self.state.players_known = True
                    if self.state.player_count <= 0:
                        self.state.players.clear()
                except ValueError:
                    pass

        if "game_version" in active_hits:
            match = active_hits["game_version"]
            raw = match.groupdict().get("version") or (
                match.group(1) if match.lastindex else None
            )
            if raw is not None:
                version = str(raw).strip().rstrip(".,;")
                if version:
                    if version != self.state.game_version:
                        LOG.info("Game version from logs: %s", version)
                    self.state.game_version = version
                    self.state.game_version_seen_at = time.time()
                    self.state.game_version_line = line

        if "version_mismatch" in active_hits:
            self.state.version_mismatch_count += 1
            self.state.last_version_mismatch_at = time.time()
            self.state.last_version_mismatch_line = line
            LOG.warning("Active version-mismatch pattern hit: %s", line)
            if self.on_version_mismatch:
                try:
                    self.on_version_mismatch(line)
                except Exception as exc:  # noqa: BLE001
                    # Keep monitoring logs, but surface the bug once.
                    LOG.exception(
                        "version mismatch callback failed; disabling callback"
                    )
                    self.state.last_version_mismatch_line = (
                        f"callback error: {exc}; last line: {line}"
                    )
                    self.on_version_mismatch = None

    def ingest_stdout_line(self, line: str) -> None:
        self._handle_line(line, source="stdout")


def plugin_patterns_as_dict(plugin: GamePlugin) -> dict[str, list[str]]:
    patterns = plugin.log_patterns
    return {
        "ready": list(patterns.ready or []),
        "player_join": list(patterns.player_join or []),
        "player_leave": list(patterns.player_leave or []),
        "player_count": list(patterns.player_count or []),
        "players_empty": list(patterns.players_empty or []),
        "game_version": list(patterns.game_version or []),
        "version_mismatch": list(patterns.version_mismatch or []),
    }


def merge_candidates(
    defaults: dict[str, list[str]],
    overrides: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {
        key: list(values) for key, values in defaults.items()
    }
    if not overrides:
        return merged
    for key, values in overrides.items():
        bucket = merged.setdefault(key, [])
        for value in values:
            if value not in bucket:
                bucket.append(value)
    return merged
