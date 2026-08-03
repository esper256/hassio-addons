#!/usr/bin/env python3
"""Lightweight tests that do not require SteamCMD or Docker."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game_server.backup import (  # noqa: E402
    RetentionPolicy,
    retention_from_profile,
    select_generational_keepers,
)
from game_server.config import format_bool, load_config, load_options_json  # noqa: E402
from game_server.log_tools import LogToolbox  # noqa: E402
from game_server.migrate import apply_path_migrations  # noqa: E402
from game_server.monitor import LogMonitor  # noqa: E402
from game_server.plugin import LogPatterns, PathMigration, load_plugin  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "example.game.yaml"


class ConfigTests(unittest.TestCase):
    def test_options_json_and_bool_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "options.json"
            path.write_text(
                json.dumps(
                    {
                        "world_name": "TestWorld",
                        "pause_when_empty": True,
                        "server_slots": 8,
                        "auto_update_interval_minutes": 15,
                        "update_on_start": False,
                        "backup_keep_monthly": 6,
                    }
                ),
                encoding="utf-8",
            )
            options = load_options_json(path)
            self.assertEqual(options["world_name"], "TestWorld")

            os.environ["OPTIONS_FILE"] = str(path)
            os.environ["SERVER_PASSWORD"] = "secret"
            try:
                cfg = load_config()
            finally:
                os.environ.pop("OPTIONS_FILE", None)
                os.environ.pop("SERVER_PASSWORD", None)

            self.assertEqual(cfg.game_options["world_name"], "TestWorld")
            self.assertEqual(cfg.auto_update_interval_minutes, 15)
            self.assertFalse(cfg.update_on_start)
            self.assertEqual(cfg.game_options["server_password"], "secret")
            self.assertEqual(cfg.install_dir, "/data/game")
            self.assertEqual(cfg.backup_keep_monthly, 6)
            self.assertEqual(format_bool(True, "one_zero"), "1")


class PluginTests(unittest.TestCase):
    def test_load_example_fixture(self) -> None:
        plugin = load_plugin(FIXTURE)
        self.assertEqual(plugin.name, "ExampleGame")
        self.assertEqual(plugin.steam_app_id, 1)
        self.assertEqual(plugin.install_marker, "server.bin")
        self.assertEqual(plugin.log_patterns.player_join, [])


class MonitorTests(unittest.TestCase):
    def test_dry_run_candidates_do_not_trigger_events(self) -> None:
        plugin = load_plugin(FIXTURE)
        triggered = []
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp, on_version_mismatch=triggered.append)
            self.assertFalse(mon.player_tracking_enabled)
            self.assertFalse(mon.version_mismatch_enabled)
            mon.ingest_stdout_line("Alice connected")
            mon.ingest_stdout_line("Client rejected: wrong version")
            # Dry-run may highlight, but must not mutate player/mismatch state.
            self.assertEqual(mon.state.players, set())
            self.assertFalse(mon.state.players_known)
            self.assertEqual(mon.state.version_mismatch_count, 0)
            self.assertEqual(triggered, [])
            report = mon.pattern_report()
            self.assertGreater(report["dry_run_pattern_count"], 0)
            self.assertTrue(any(item["hits"] > 0 for item in report["patterns"]))

    def test_active_patterns_trigger_events(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.log_patterns = LogPatterns(
            player_join=[r"(?P<player>[\w .-]+) connected"],
            player_leave=[r"(?P<player>[\w .-]+) disconnected"],
            version_mismatch=[r"wrong version"],
        )
        triggered = []
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp, on_version_mismatch=triggered.append)
            self.assertTrue(mon.player_tracking_enabled)
            mon.ingest_stdout_line("Alice connected")
            self.assertIn("Alice", mon.state.players)
            self.assertTrue(mon.state.players_known)
            mon.ingest_stdout_line("Alice disconnected")
            self.assertNotIn("Alice", mon.state.players)
            mon.ingest_stdout_line("Client rejected: wrong version")
            self.assertEqual(mon.state.version_mismatch_count, 1)
            self.assertEqual(len(triggered), 1)
            active_hits = [
                p for p in mon.pattern_report()["patterns"] if p["mode"] == "active"
            ]
            self.assertTrue(any(p["hits"] > 0 for p in active_hits))


class BackupRetentionTests(unittest.TestCase):
    def test_generational_keepers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stamps = [
                ("2024-01-01", "old-year"),
                ("2025-06-01", "mid"),
                ("2026-01-01", "year"),
                ("2026-02-01", "month-a"),
                ("2026-03-01", "month-b"),
                ("2026-03-10", "week"),
                ("2026-03-15", "day1"),
                ("2026-03-16", "day2"),
                ("2026-03-16T12", "recent1"),
                ("2026-03-16T18", "recent2"),
            ]
            archives = []
            for idx, (label, name) in enumerate(stamps):
                path = root / f"backup-{name}.tar.gz"
                path.write_bytes(b"x" * 100)
                if "T" in label:
                    day, hour = label.split("T")
                    y, m, d = map(int, day.split("-"))
                    ts = time.mktime((y, m, d, int(hour), 0, 0, 0, 0, -1))
                else:
                    y, m, d = map(int, label.split("-"))
                    ts = time.mktime((y, m, d, 12, 0, 0, 0, 0, -1))
                ts += idx
                os.utime(path, (ts, ts))
                archives.append(path)

            archives = sorted(archives, key=lambda p: p.stat().st_mtime, reverse=True)
            keep = select_generational_keepers(
                archives,
                RetentionPolicy(
                    keep_recent=2,
                    keep_daily=2,
                    keep_weekly=2,
                    keep_monthly=2,
                    keep_yearly=2,
                ),
            )
            self.assertIn(archives[0], keep)
            self.assertIn(archives[1], keep)


class LogToolsTests(unittest.TestCase):
    def test_capture_and_suggest(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            state = Path(tmp) / "state"
            logs.mkdir()
            state.mkdir()
            (logs / "server.log").write_text(
                "ready\nBob connected\nClient rejected: wrong version\n",
                encoding="utf-8",
            )
            recent = ["extra line with outdated client"]
            box = LogToolbox(plugin, logs, state, recent_lines_provider=lambda: recent)
            report = box.suggest(lines=50)
            self.assertTrue(
                report["matches"]["version_mismatch"]
                or report["suggestions"]["version_mismatch"]
            )
            capture = box.capture(reason="test", status={"ok": True})
            self.assertTrue(
                (state / "captures" / capture["id"] / "capture.tar.gz").is_file()
            )


class MigrationTests(unittest.TestCase):
    def test_path_migration_from_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "old"
            dst = Path(tmp) / "new"
            (src / "saves").mkdir(parents=True)
            (src / "saves" / "world.zip").write_text("data", encoding="utf-8")
            plugin = load_plugin(FIXTURE)
            plugin.path_migrations = [
                PathMigration(source=str(src), destination=str(dst), marker="saves")
            ]
            applied = apply_path_migrations(plugin)
            self.assertEqual(len(applied), 1)
            self.assertTrue((dst / "saves" / "world.zip").is_file())
            self.assertEqual(apply_path_migrations(plugin), [])


if __name__ == "__main__":
    unittest.main()
