#!/usr/bin/env python3
"""Lightweight tests that do not require SteamCMD or Docker."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))  # repo root? package lives in game-server-base
sys.path.insert(0, str(ROOT))

from game_server.config import format_bool, load_config, load_options_json  # noqa: E402
from game_server.monitor import LogMonitor  # noqa: E402
from game_server.plugin import load_plugin  # noqa: E402


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
                    }
                ),
                encoding="utf-8",
            )
            options = load_options_json(path)
            self.assertEqual(options["world_name"], "TestWorld")
            self.assertTrue(options["pause_when_empty"])

            # Simulate HA path via OPTIONS_FILE
            import os

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
            self.assertEqual(format_bool(True, "one_zero"), "1")
            self.assertEqual(format_bool(False, "one_zero"), "0")
            self.assertEqual(format_bool("true", "true_false"), "true")


class PluginTests(unittest.TestCase):
    def test_load_necesse_yaml(self) -> None:
        plugin = load_plugin(ROOT / "games" / "necesse.yaml")
        self.assertEqual(plugin.name, "Necesse")
        self.assertEqual(plugin.steam_app_id, 1169370)
        self.assertIn("-world", plugin.arg_map.values())
        self.assertTrue(plugin.log_patterns.version_mismatch)


class MonitorTests(unittest.TestCase):
    def test_player_and_mismatch_patterns(self) -> None:
        plugin = load_plugin(ROOT / "games" / "necesse.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp)
            mon.ingest_stdout_line("Alice connected")
            self.assertIn("Alice", mon.state.players)
            mon.ingest_stdout_line("Alice disconnected")
            self.assertNotIn("Alice", mon.state.players)
            mon.ingest_stdout_line("Client rejected: wrong version")
            self.assertEqual(mon.state.version_mismatch_count, 1)


if __name__ == "__main__":
    unittest.main()
