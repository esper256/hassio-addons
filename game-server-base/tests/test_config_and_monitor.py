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
from game_server.log_bridge import RecentLineDeduper  # noqa: E402
from game_server.log_tools import LogToolbox  # noqa: E402
from game_server.monitor import LogMonitor  # noqa: E402
from game_server.plugin import LogPatterns, load_plugin  # noqa: E402
from game_server.steam_gate import SteamGate, SteamPolicy, reset_gate_for_tests  # noqa: E402
from game_server.steamcmd import (  # noqa: E402
    _build_app_update_cmd,
    _run_streaming,
    looks_missing_configuration,
    parse_app_info_build_id,
    prepare_steam_env,
    wait_for_app_info,
)
from game_server.version import app_version  # noqa: E402

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
                        "backup_retention": "extended",
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
            self.assertEqual(cfg.backup_retention, "extended")
            self.assertEqual(cfg.retention().keep_monthly, 24)
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
    def test_profiles(self) -> None:
        standard = retention_from_profile("standard")
        self.assertEqual(standard.keep_daily, 7)
        self.assertEqual(standard.keep_weekly, 4)
        self.assertEqual(standard.keep_monthly, 12)
        self.assertEqual(retention_from_profile("nope").profile, "standard")

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


class SteamGateTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_gate_for_tests()
        self.now = 1_000_000.0
        self.sleeps: list[float] = []

    def tearDown(self) -> None:
        reset_gate_for_tests()

    def _gate(self, tmp: str) -> SteamGate:
        policy = SteamPolicy(
            min_interval_seconds=90,
            max_retries=3,
            retry_base_seconds=60,
            retry_max_seconds=900,
            retry_jitter_ratio=0.0,
            failure_backoff_base_seconds=120,
            failure_backoff_max_seconds=3600,
            rate_limit_cooldown_seconds=21600,
            min_check_interval_minutes=15,
        )
        return SteamGate(
            Path(tmp) / "steam_gate.json",
            policy,
            time_fn=lambda: self.now,
            sleep_fn=self.sleeps.append,
        )

    def test_retry_and_check_clamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._gate(tmp)
            self.assertEqual(gate.clamp_retries(99), 3)
            self.assertEqual(gate.clamp_check_interval_minutes(5), 15)
            self.assertEqual(gate.clamp_check_interval_minutes(0), 0)
            self.assertEqual(gate.retry_delay_seconds(1), 60)
            self.assertEqual(gate.retry_delay_seconds(2), 120)
            self.assertEqual(gate.retry_delay_seconds(5), 900)

    def test_rate_limit_forces_long_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._gate(tmp)
            gate.note_failure("ERROR! Rate Limit Exceeded", kind="app_update")
            self.assertGreaterEqual(gate.cooldown_remaining(), 21599)
            self.assertTrue(gate.looks_rate_limited("Login Rate Limited"))

    def test_failure_backoff_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._gate(tmp)
            gate.note_failure("network blip", kind="app_info")
            self.assertGreaterEqual(gate.cooldown_remaining(), 119)
            path = Path(tmp) / "steam_gate.json"
            self.assertTrue(path.is_file())
            restored = SteamGate(
                path,
                gate.policy,
                time_fn=lambda: self.now,
                sleep_fn=self.sleeps.append,
            )
            self.assertEqual(restored.consecutive_failures, 1)
            self.assertGreater(restored.cooldown_remaining(), 0)

    def test_session_enforces_spacing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._gate(tmp)
            with gate.session("app_info"):
                pass
            # Next session should wait remaining min interval via sleep_fn chunks.
            original_sleep = gate._sleep

            def advance_sleep(seconds: float) -> None:
                self.sleeps.append(seconds)
                self.now += seconds

            gate._sleep = advance_sleep  # type: ignore[method-assign]
            with gate.session("app_update"):
                pass
            self.assertGreaterEqual(sum(self.sleeps), 89)
            gate._sleep = original_sleep  # type: ignore[method-assign]


class VersionTests(unittest.TestCase):
    def test_app_version_reads_env(self) -> None:
        old = os.environ.get("APP_VERSION")
        os.environ["APP_VERSION"] = "2.1.8-test"
        try:
            self.assertEqual(app_version(), "2.1.8-test")
        finally:
            if old is None:
                os.environ.pop("APP_VERSION", None)
            else:
                os.environ["APP_VERSION"] = old


class LogBridgeTests(unittest.TestCase):
    def test_recent_line_deduper(self) -> None:
        deduper = RecentLineDeduper(maxlen=8, ttl_seconds=30)
        self.assertTrue(deduper.remember_if_new("Player joined"))
        self.assertFalse(deduper.remember_if_new("  Player joined  "))
        self.assertTrue(deduper.remember_if_new("Player left"))
        self.assertFalse(deduper.remember_if_new(""))

    def test_steamcmd_streaming_captures_output(self) -> None:
        code, output = _run_streaming(
            [sys.executable, "-c", "print('steam-line-one'); print('steam-line-two')"],
            timeout=10,
            prefix="[steamcmd-test]",
        )
        self.assertEqual(code, 0)
        self.assertIn("steam-line-one", output)
        self.assertIn("steam-line-two", output)


class SteamCMDHelperTests(unittest.TestCase):
    def test_missing_configuration_detection(self) -> None:
        self.assertTrue(
            looks_missing_configuration(
                "ERROR! Failed to install app '1169370' (Missing configuration)"
            )
        )
        self.assertFalse(looks_missing_configuration("Success! App '1' fully installed"))

    def test_parse_app_info_build_id(self) -> None:
        sample = (
            '"1"\n{\n  "branches"\n  {\n    "public"\n    {\n'
            '      "buildid"\t\t"424242"\n    }\n  }\n}\n'
        )
        self.assertEqual(parse_app_info_build_id(sample, "public"), "424242")
        self.assertIsNone(parse_app_info_build_id("Missing configuration", "public"))
        self.assertIsNone(parse_app_info_build_id("", "public"))

    def test_wait_for_app_info_polls_until_ready(self) -> None:
        plugin = load_plugin(FIXTURE)
        calls = {"n": 0}
        outputs = [
            "not ready yet",
            '"1"\n{\n  "branches"\n  {\n    "public"\n    {\n'
            '      "buildid"\t\t"99"\n    }\n  }\n}\n',
        ]

        def fake_run(cmd, *, timeout, prefix="[steamcmd]", env=None):  # noqa: ANN001
            idx = min(calls["n"], len(outputs) - 1)
            calls["n"] += 1
            return 0, outputs[idx]

        with tempfile.TemporaryDirectory() as tmp:
            steamcmd_dir = Path(tmp) / "steamcmd"
            steamcmd_dir.mkdir()
            (steamcmd_dir / "steamcmd.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            old_home = os.environ.get("STEAM_HOME")
            os.environ["STEAM_HOME"] = str(Path(tmp) / "steam-home")
            import game_server.steamcmd as steamcmd_mod

            original = steamcmd_mod._run_streaming
            steamcmd_mod._run_streaming = fake_run  # type: ignore[assignment]
            try:
                env = prepare_steam_env(Path(tmp) / "game")
                build_id = wait_for_app_info(
                    steamcmd_dir,
                    plugin,
                    env=env,
                    timeout_seconds=20,
                    poll_interval_seconds=0.01,
                )
            finally:
                steamcmd_mod._run_streaming = original  # type: ignore[assignment]
                if old_home is None:
                    os.environ.pop("STEAM_HOME", None)
                else:
                    os.environ["STEAM_HOME"] = old_home
            self.assertEqual(build_id, "99")
            self.assertGreaterEqual(calls["n"], 2)

    def test_build_cmd_orders_force_install_before_login(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.steam_platform = "linux"
        with tempfile.TemporaryDirectory() as tmp:
            steamcmd_dir = Path(tmp) / "steamcmd"
            steamcmd_dir.mkdir()
            (steamcmd_dir / "steamcmd.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            install_dir = Path(tmp) / "game"
            cmd = _build_app_update_cmd(
                steamcmd_dir,
                install_dir,
                plugin,
                validate=True,
                platform="linux",
            )
            joined = " ".join(cmd)
            self.assertIn("+@sSteamCmdForcePlatformType linux", joined)
            self.assertLess(cmd.index("+force_install_dir"), cmd.index("+login"))
            self.assertLess(cmd.index("+login"), cmd.index("+app_update"))
            self.assertIn("validate", cmd)
            self.assertEqual(cmd[-1], "+quit")

    def test_prepare_steam_env_creates_steamapps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "game"
            home = Path(tmp) / "steam-home"
            old_home = os.environ.get("STEAM_HOME")
            os.environ["STEAM_HOME"] = str(home)
            try:
                env = prepare_steam_env(install_dir)
            finally:
                if old_home is None:
                    os.environ.pop("STEAM_HOME", None)
                else:
                    os.environ["STEAM_HOME"] = old_home
            self.assertEqual(env["HOME"], str(home))
            self.assertTrue((install_dir / "steamapps").is_dir())
            self.assertTrue((home / "Steam").is_dir())


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


if __name__ == "__main__":
    unittest.main()
