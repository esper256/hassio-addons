"""Browser/Ingress-friendly log capture and pattern-suggestion helpers.

Goal: tune game log regexes without SSH into Portainer/HAOS containers.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .plugin import GamePlugin

LOG = logging.getLogger("game_server.log_tools")

KEYWORD_HINTS = {
    "player_join": [
        r"\bconnected\b",
        r"\bjoined\b",
        r"\blogin\b",
        r"\bentering\b",
    ],
    "player_leave": [
        r"\bdisconnected\b",
        r"\bleft\b",
        r"\blogout\b",
        r"\bleaving\b",
    ],
    "version_mismatch": [
        r"\bversion\b",
        r"\boutdated\b",
        r"\bmismatch\b",
        r"\bincompatible\b",
        r"\bwrong version\b",
        r"\bupdate\b",
    ],
    "ready": [
        r"\blistening\b",
        r"\bstarted\b",
        r"\bready\b",
        r"\bdone\b",
        r"\bworld loaded\b",
    ],
}


class LogToolbox:
    def __init__(
        self,
        plugin: GamePlugin,
        logs_dir: str | Path,
        state_dir: str | Path,
        recent_lines_provider,
    ) -> None:
        self.plugin = plugin
        self.logs_dir = Path(logs_dir)
        self.state_dir = Path(state_dir)
        self.captures_dir = self.state_dir / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.recent_lines_provider = recent_lines_provider

    def pick_log_file(self) -> Path | None:
        if not self.logs_dir.is_dir():
            return None
        for preferred in ("latest.log", "server.log", "console.log"):
            path = self.logs_dir / preferred
            if path.is_file():
                return path
        candidates = sorted(
            [p for p in self.logs_dir.iterdir() if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def tail_file(self, path: Path | None = None, lines: int = 400) -> list[str]:
        path = path or self.pick_log_file()
        if path is None or not path.is_file():
            return []
        try:
            # Efficient-ish tail for moderate log files.
            data = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return data[-max(1, lines) :]
        except OSError:
            return []

    def analyze_lines(self, lines: Iterable[str]) -> dict[str, Any]:
        patterns = self.plugin.log_patterns
        compiled = {
            "player_join": patterns.compiled("player_join"),
            "player_leave": patterns.compiled("player_leave"),
            "version_mismatch": patterns.compiled("version_mismatch"),
            "player_count": patterns.compiled("player_count"),
            "ready": patterns.compiled("ready"),
        }
        matches: dict[str, list[str]] = {k: [] for k in compiled}
        unmatched_interesting: list[str] = []
        suggestions: dict[str, list[dict[str, str]]] = {k: [] for k in KEYWORD_HINTS}

        for line in lines:
            text = line.rstrip("\n")
            if not text.strip():
                continue
            hit = False
            for key, regs in compiled.items():
                for reg in regs:
                    if reg.search(text):
                        if len(matches[key]) < 50:
                            matches[key].append(text)
                        hit = True
                        break
            if hit:
                continue
            for key, hints in KEYWORD_HINTS.items():
                for hint in hints:
                    if re.search(hint, text, re.I):
                        if len(suggestions[key]) < 40:
                            suggestions[key].append(
                                {
                                    "line": text,
                                    "suggested_regex": _suggest_regex(text, key),
                                    "hint": hint,
                                }
                            )
                        if len(unmatched_interesting) < 100:
                            unmatched_interesting.append(text)
                        break

        return {
            "configured_patterns": {
                "player_join": patterns.player_join,
                "player_leave": patterns.player_leave,
                "version_mismatch": patterns.version_mismatch,
                "player_count": patterns.player_count,
                "ready": patterns.ready,
            },
            "matches": matches,
            "suggestions": suggestions,
            "unmatched_interesting": unmatched_interesting,
        }

    def suggest(self, lines: int = 500) -> dict[str, Any]:
        recent = list(self.recent_lines_provider())
        file_lines = self.tail_file(lines=lines)
        # Prefer union, file first then memory
        merged: list[str] = []
        seen = set()
        for line in file_lines + recent:
            if line in seen:
                continue
            seen.add(line)
            merged.append(line)
        report = self.analyze_lines(merged)
        report["source_log"] = str(self.pick_log_file()) if self.pick_log_file() else None
        report["line_count_analyzed"] = len(merged)
        return report

    def list_captures(self) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.captures_dir.iterdir(), reverse=True):
            if not path.is_dir():
                continue
            meta_path = path / "capture.json"
            meta = {}
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = {}
            archive = path / "capture.tar.gz"
            items.append(
                {
                    "id": path.name,
                    "path": str(path),
                    "created_at": meta.get("created_at"),
                    "reason": meta.get("reason"),
                    "has_archive": archive.is_file(),
                    # Relative path so Home Assistant Ingress (X-Ingress-Path) works.
                    "download_path": f"api/logs/captures/{path.name}/download",
                }
            )
        return items

    def capture(
        self,
        reason: str = "manual",
        status: dict[str, Any] | None = None,
        lines: int = 800,
    ) -> dict[str, Any]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        capture_id = f"{stamp}-{reason}"
        dest = self.captures_dir / capture_id
        dest.mkdir(parents=True, exist_ok=True)

        recent = list(self.recent_lines_provider())
        file_lines = self.tail_file(lines=lines)
        (dest / "recent_stdout.txt").write_text(
            "\n".join(recent) + ("\n" if recent else ""),
            encoding="utf-8",
        )
        (dest / "log_tail.txt").write_text(
            "\n".join(file_lines) + ("\n" if file_lines else ""),
            encoding="utf-8",
        )

        src_log = self.pick_log_file()
        if src_log and src_log.is_file():
            try:
                shutil.copy2(src_log, dest / src_log.name)
            except OSError as exc:
                LOG.warning("Could not copy log file: %s", exc)

        analysis = self.analyze_lines(file_lines + recent)
        (dest / "analysis.json").write_text(
            json.dumps(analysis, indent=2),
            encoding="utf-8",
        )
        if status is not None:
            (dest / "status.json").write_text(
                json.dumps(status, indent=2, default=str),
                encoding="utf-8",
            )

        meta = {
            "id": capture_id,
            "reason": reason,
            "created_at": time.time(),
            "created_at_iso": datetime.now(timezone.utc).isoformat(),
            "source_log": str(src_log) if src_log else None,
            "game": self.plugin.name,
            "steam_app_id": self.plugin.steam_app_id,
        }
        (dest / "capture.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        archive = dest / "capture.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in dest.iterdir():
                if path.name == "capture.tar.gz":
                    continue
                tar.add(path, arcname=path.name)

        # Keep only the newest 30 captures
        captures = sorted(
            [p for p in self.captures_dir.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        for stale in captures[30:]:
            shutil.rmtree(stale, ignore_errors=True)

        LOG.info("Created log capture %s (%s)", capture_id, reason)
        return {
            "id": capture_id,
            "path": str(dest),
            "download_path": f"api/logs/captures/{capture_id}/download",
            "analysis_summary": {
                key: len(vals) for key, vals in analysis.get("matches", {}).items()
            },
            "suggestion_counts": {
                key: len(vals) for key, vals in analysis.get("suggestions", {}).items()
            },
        }

    def capture_archive_path(self, capture_id: str) -> Path | None:
        path = self.captures_dir / capture_id / "capture.tar.gz"
        return path if path.is_file() else None


def _suggest_regex(line: str, category: str) -> str:
    """Produce a conservative starter regex from a sample line."""

    # Collapse obvious player-name-ish tokens between keywords.
    text = re.escape(line)
    text = text.replace(r"\ ", " ")
    if category in {"player_join", "player_leave"}:
        text = re.sub(
            r"(connected|disconnected|joined|left|login|logout)",
            r"(?P<player>[\\w .-]+) \1",
            line,
            count=1,
            flags=re.I,
        )
        return text
    # Fallback: case-insensitive substring of the original line trimmed
    snippet = line.strip()
    if len(snippet) > 120:
        snippet = snippet[:120]
    return re.escape(snippet)
