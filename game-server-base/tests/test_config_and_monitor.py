#!/usr/bin/env python3
"""Lightweight tests that do not require SteamCMD or Docker."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game_server.backup import (  # noqa: E402
    EMPTY_WORLD,
    BackupManager,
    RetentionPolicy,
    retention_from_profile,
    select_generational_keepers,
)
from game_server.disk import format_bytes  # noqa: E402
from game_server.config import (  # noqa: E402
    SupervisorConfig,
    format_bool,
    load_config,
    load_options_json,
)
from game_server.log_bridge import RecentLineDeduper, strip_ansi  # noqa: E402
from game_server.log_tools import LogToolbox, discover_log_file  # noqa: E402
from game_server.monitor import LogMonitor  # noqa: E402
from game_server.plugin import LogPatterns, load_plugin  # noqa: E402
from game_server.process_manager import ProcessManager  # noqa: E402
from game_server.steam_gate import SteamGate, SteamPolicy, reset_gate_for_tests  # noqa: E402
from game_server.status_http import (  # noqa: E402
    DEFAULT_UI_THEME,
    HTML_PAGE,
    _STATUS_HTML_KEYS,
    _fmt_ago,
    _format_backups,
    _format_backup_options,
    _format_crashes_hint,
    _format_disk,
    _format_game_version,
    _format_highlights,
    _format_pattern_rows,
    _format_running,
    _format_subtitle,
    _format_update_check_hint,
    _format_uptime,
    _format_world_save,
    _ui_view,
    healthz_ok,
    render_status_html,
    resolve_ui_theme,
)
from game_server.world_save import (  # noqa: E402
    ActiveWorld,
    WorldSaveSpec,
    backup_sources_for,
    locate_active_world,
    prepare_world_download,
    world_save_is_downloadable,
)
from game_server.steamcmd import (  # noqa: E402
    UpdateCheckResult,
    _app_info_cmd,
    _build_app_update_cmd,
    _run_streaming,
    configure_steamcmd_version_path,
    looks_missing_configuration,
    looks_missing_file_permissions,
    parse_app_info_build_id,
    prepare_steam_env,
    read_local_install_meta,
    remember_steamcmd_version,
    server_installed,
    steamcmd_client_version,
    update_available,
    wait_for_app_info,
)
from game_server.supervisor import GameServerSupervisor  # noqa: E402
from game_server.version import app_version  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "example.game.yaml"
NECESSE_PLUGIN = ROOT.parent / "necesse-dedicated-server" / "games" / "game.yaml"
STATIONEERS_PLUGIN = ROOT.parent / "stationeers-dedicated-server" / "games" / "game.yaml"


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

            plugin = load_plugin(FIXTURE)
            os.environ["OPTIONS_FILE"] = str(path)
            # Game option env keys come from the plugin (WORLD_NAME via arg_map),
            # not a hardcoded allowlist in config.py.
            os.environ["WORLD_NAME"] = "FromEnv"
            try:
                cfg = load_config(game_env_keys=plugin.docker_env_keys())
            finally:
                os.environ.pop("OPTIONS_FILE", None)
                os.environ.pop("WORLD_NAME", None)

            self.assertEqual(cfg.game_options["world_name"], "FromEnv")
            self.assertEqual(cfg.auto_update_interval_minutes, 15)
            self.assertEqual(cfg.auto_update_check_hour, 5)
            self.assertFalse(cfg.update_on_start)
            self.assertEqual(cfg.install_dir, "/data/game")
            self.assertEqual(cfg.backup_retention, "extended")
            self.assertEqual(cfg.retention().keep_monthly, 24)
            self.assertEqual(format_bool(True, "one_zero"), "1")

    def test_game_env_keys_not_accepted_without_plugin(self) -> None:
        os.environ["WORLD_TYPE"] = "Lunar"
        os.environ["STATUS_HTTP_PORT"] = "8101"
        try:
            cfg = load_config()
        finally:
            os.environ.pop("WORLD_TYPE", None)
            os.environ.pop("STATUS_HTTP_PORT", None)
        self.assertNotIn("world_type", cfg.game_options)
        self.assertEqual(cfg.status_http_port, 8101)

    def test_plugin_docker_env_keys_cover_cli_surface(self) -> None:
        stationeers = load_plugin(STATIONEERS_PLUGIN)
        keys = set(stationeers.docker_env_keys())
        self.assertIn("WORLD_NAME", keys)
        self.assertIn("WORLD_TYPE", keys)
        self.assertIn("SERVER_NAME", keys)
        self.assertIn("UPDATE_PORT", keys)
        self.assertIn("DIFFICULTY", keys)
        self.assertNotIn("JAVA_OPTS", keys)

        necesse = load_plugin(NECESSE_PLUGIN)
        necesse_keys = set(necesse.docker_env_keys())
        self.assertIn("WORLD_NAME", necesse_keys)
        self.assertIn("SERVER_PASSWORD", necesse_keys)
        self.assertIn("JAVA_OPTS", necesse_keys)
        self.assertNotIn("WORLD_TYPE", necesse_keys)
        self.assertNotIn("START_CONDITION", necesse_keys)


class PluginTests(unittest.TestCase):
    def test_load_example_fixture(self) -> None:
        plugin = load_plugin(FIXTURE)
        self.assertEqual(plugin.name, "ExampleGame")
        self.assertEqual(plugin.steam_app_id, 1)
        self.assertEqual(plugin.install_marker, "server.bin")
        self.assertEqual(plugin.log_patterns.player_join, [])
        self.assertIsNotNone(plugin.world_save)
        assert plugin.world_save is not None
        self.assertEqual(plugin.world_save.strategy, "named_path")
        self.assertIn("{world_name}.zip", plugin.world_save.paths[0])

    def test_load_stationeers_plugin_builds_unity_cli(self) -> None:
        self.assertTrue(STATIONEERS_PLUGIN.is_file(), f"missing {STATIONEERS_PLUGIN}")
        plugin = load_plugin(STATIONEERS_PLUGIN)
        self.assertEqual(plugin.name, "Stationeers")
        self.assertEqual(plugin.steam_app_id, 600760)
        self.assertEqual(plugin.install_marker, "rocketstation_DedicatedServer.x86_64")
        self.assertEqual(plugin.settings_flag, "-settings")
        self.assertIn("GamePort", plugin.settings_map.values())
        self.assertEqual(plugin.player_tracking_mode, "presence")
        self.assertTrue(plugin.log_patterns.game_version)
        self.assertTrue(plugin.log_patterns.player_join)
        self.assertTrue(plugin.log_patterns.players_empty)
        self.assertEqual(plugin.ui_theme.get("accent"), "#5ec8ff")
        cfg = SupervisorConfig(
            drop_privileges=False,
            status_http_enabled=False,
            backup_enabled=False,
            ha_notifications=False,
            game_options={
                "world_name": "FamilyStation",
                "world_type": "Lunar",
                "server_name": "Family Stationeers",
                "server_port": 27016,
                "update_port": 27015,
                "server_slots": 10,
                "server_visible": True,
                "auto_save": True,
                "save_interval": 300,
                "auto_pause": True,
                "upnp_enabled": False,
                "use_steam_p2p": False,
                "bind_ip": "0.0.0.0",
                "data_dir": "/data/world",
                "logs_dir": "/data/logs",
            },
        )
        cmd = ProcessManager(plugin, cfg).build_command()
        self.assertEqual(cmd[0], "./rocketstation_DedicatedServer.x86_64")
        self.assertIn("-file", cmd)
        self.assertIn("start", cmd)
        self.assertIn("FamilyStation", cmd)
        self.assertIn("Lunar", cmd)
        self.assertIn("-settings", cmd)
        self.assertIn("GamePort", cmd)
        self.assertIn("27016", cmd)
        self.assertIn("UpdatePort", cmd)
        self.assertIn("27015", cmd)
        self.assertIn("SavePath", cmd)
        self.assertIn("/data/world", cmd)
        # Optional empty fields must not inject blank tokens before -noclear.
        file_idx = cmd.index("-file")
        noclear_idx = cmd.index("-noclear")
        self.assertEqual(
            cmd[file_idx:noclear_idx],
            ["-file", "start", "FamilyStation", "Lunar"],
        )


class StationeersPresenceTests(unittest.TestCase):
    """Presence-mode tracking from real Stationeers log shapes."""

    def test_join_leave_empty_and_version(self) -> None:
        plugin = load_plugin(STATIONEERS_PLUGIN)
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp)
            self.assertTrue(mon.presence_tracking)
            mon.ingest_stdout_line(
                "Initialize engine version: 2022.3.62f3 (96770f904ca7)"
            )
            self.assertIsNone(mon.state.game_version)
            mon.ingest_stdout_line("16:49:34: Version : 0.2.6403.27689")
            self.assertEqual(mon.state.game_version, "0.2.6403.27689")
            mon.ingest_stdout_line(
                "16:52:09: Client: TheFrizz (76561197968471340). Connected. 4944 / 4944"
            )
            self.assertTrue(mon.state.players_known)
            self.assertEqual(mon.state.player_count, 1)
            self.assertIn("TheFrizz", mon.state.players)
            mon.ingest_stdout_line(
                "16:52:50: Client disconnected: 382805979229700724 | TheFrizz"
                "  \tconnectTime: 176.7s, ClientId: 76561197968471340"
            )
            self.assertEqual(mon.state.player_count, 0)
            self.assertEqual(mon.state.players, set())
            mon.ingest_stdout_line(
                "16:52:09: Client: TheFrizz (76561197968471340). Connected. 4944 / 4944"
            )
            self.assertEqual(mon.state.player_count, 1)
            mon.ingest_stdout_line(
                "16:52:50: No clients connected. Will save and pause in 10 seconds."
            )
            self.assertEqual(mon.state.player_count, 0)
            self.assertEqual(mon.state.players, set())

    def test_recent_matches_keep_five_lines(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.log_patterns = LogPatterns(ready=[r"\bready\b"])
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp)
            for i in range(7):
                mon.ingest_stdout_line(f"server ready line {i}")
            ready_stat = next(
                p
                for p in mon.pattern_report()["patterns"]
                if p["category"] == "ready" and p["mode"] == "active"
            )
            self.assertEqual(ready_stat["hits"], 7)
            self.assertEqual(len(ready_stat["recent_lines"]), 5)
            self.assertEqual(ready_stat["recent_lines"][0], "server ready line 2")
            self.assertEqual(ready_stat["recent_lines"][-1], "server ready line 6")


class NecessePatternPromotionTests(unittest.TestCase):
    """Exercise the new-game workflow: promote proven dry-run lines into active patterns."""

    def test_real_highlight_lines_drive_ready_players_and_version(self) -> None:
        self.assertTrue(NECESSE_PLUGIN.is_file(), f"missing {NECESSE_PLUGIN}")
        plugin = load_plugin(NECESSE_PLUGIN)
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp)
            self.assertTrue(mon.player_tracking_enabled)
            self.assertTrue(mon.presence_tracking)
            samples = [
                "[2026-08-03 13:57:00] Loading dedicated server on version 1.3.1.",
                (
                    '[2026-08-03 13:57:06] Started server using port 14159 with 10 slots '
                    'on world "FamilyWorld.zip", game version 1.3.1.'
                ),
                "[2026-08-03 13:57:06] Found 0 saved players.",
                "[2026-08-03 13:57:06] Type help for list of commands.",
                (
                    "[2026-08-03 13:57:21] Suggesting garbage collection "
                    "due to empty server..."
                ),
                'Client "76561197968471340" connected on slot 1/10.',
                "Creating new player: 76561197968471340",
                (
                    'Player 76561197968471340 ("TestPlayer") '
                    "disconnected with message: Quit"
                ),
            ]
            for line in samples:
                mon.ingest_stdout_line(line)

            self.assertTrue(mon.state.ready)
            self.assertEqual(mon.state.game_version, "1.3.1")
            self.assertTrue(mon.state.players_known)
            self.assertEqual(mon.state.players, set())
            self.assertEqual(mon.state.player_count, 0)

            # Re-join after leave to confirm identity is SteamID64, not display name.
            mon.ingest_stdout_line(
                'Client "76561197968471340" connected on slot 1/10.'
            )
            self.assertEqual(mon.state.players, {"76561197968471340"})
            self.assertEqual(mon.state.player_count, 1)

            # Mismatched leave identity must not stick occupancy in presence mode.
            mon.ingest_stdout_line(
                'Player TestPlayer (76561197968471340) disconnected with message: Quit'
            )
            self.assertEqual(mon.state.players, set())
            self.assertEqual(mon.state.player_count, 0)

            # Misleading dry-run hits must not become active player_count signals.
            self.assertEqual(plugin.log_patterns.player_count, [])

            report = mon.pattern_report()
            active = {
                (p["category"], p["mode"])
                for p in report["patterns"]
                if p["mode"] == "active"
            }
            self.assertIn(("player_join", "active"), active)
            self.assertIn(("player_leave", "active"), active)
            self.assertIn(("ready", "active"), active)
            self.assertIn(("version_mismatch", "active"), active)

    def test_wrong_version_line_triggers_active_mismatch(self) -> None:
        plugin = load_plugin(NECESSE_PLUGIN)
        self.assertEqual(plugin.ui_theme.get("accent"), "#d4a25a")
        self.assertEqual(plugin.stop_timeout_seconds, 240)
        self.assertEqual(plugin.stop_stdin_commands, ["save", "exit"])
        triggered: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp, on_version_mismatch=triggered.append)
            self.assertTrue(mon.version_mismatch_enabled)
            line = (
                '[2026-08-04 08:45:04] Client "76561197968471340" '
                "had wrong version (1.3.0)."
            )
            mon.ingest_stdout_line(line)
            self.assertEqual(mon.state.version_mismatch_count, 1)
            self.assertEqual(triggered, [line])

    def test_monitor_finds_necesse_logs_under_data_dir(self) -> None:
        """Empty /data/logs must not blind the monitor when Necesse logs under world/."""

        plugin = load_plugin(NECESSE_PLUGIN)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs_dir = root / "logs"
            world = root / "world"
            logs_dir.mkdir()
            world.mkdir()
            plugin.data_dir = str(world)
            latest = world / "latest-server-log.txt"
            latest.write_text(
                'Client "76561197968471340" had wrong version (1.3.0).\n',
                encoding="utf-8",
            )
            self.assertEqual(discover_log_file(logs_dir, world), latest)
            mon = LogMonitor(plugin, logs_dir)
            self.assertEqual(mon._pick_log_file(), latest)


class PresenceLeaveResetTests(unittest.TestCase):
    def test_unknown_leave_clears_occupancy(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.player_tracking_mode = "presence"
        plugin.log_patterns = LogPatterns(
            player_join=[r"(?P<player>\S+) joined"],
            player_leave=[r"(?P<player>\S+) left"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp)
            mon.ingest_stdout_line("Alice joined")
            self.assertEqual(mon.state.player_count, 1)
            mon.ingest_stdout_line("SomeoneElse left")
            self.assertEqual(mon.state.players, set())
            self.assertEqual(mon.state.player_count, 0)


class WorldSaveLocatorTests(unittest.TestCase):
    def test_named_path_prefers_plugin_template(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "saves" / "worlds" / "FamilyWorld.zip"
            world.parent.mkdir(parents=True)
            world.write_bytes(b"x" * 2048)
            (root / "noise.log").write_text("ignore me", encoding="utf-8")
            located = locate_active_world(
                plugin,
                {"world_name": "FamilyWorld"},
                data_dir=str(root),
            )
            self.assertEqual(located.scope, "named_path")
            self.assertEqual(located.bytes, 2048)
            self.assertEqual(located.label, "FamilyWorld.zip")
            self.assertEqual(backup_sources_for(plugin, str(root)), ["/data/world"])

    def test_named_path_missing_does_not_sum_data_dir(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "noise.bin").write_bytes(b"y" * 4096)
            located = locate_active_world(
                plugin,
                {"world_name": "FamilyWorld"},
                data_dir=str(root),
            )
            self.assertEqual(located.scope, "missing")
            self.assertEqual(located.bytes, 0)
            self.assertTrue(str(located.path or "").endswith("FamilyWorld.zip"))
            value, hint = _format_world_save({"world_save": located.to_dict()})
            self.assertEqual(value, "—")
            self.assertIn("FamilyWorld.zip", hint)

    def test_world_save_download_file_and_directory_zip(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "saves" / "worlds" / "FamilyWorld.zip"
            world.parent.mkdir(parents=True)
            world.write_bytes(b"SAVE-BYTES")
            located = locate_active_world(
                plugin,
                {"world_name": "FamilyWorld"},
                data_dir=str(root),
            )
            self.assertTrue(
                world_save_is_downloadable(located, data_dir=str(root))
            )
            prepared = prepare_world_download(located, data_dir=str(root))
            self.assertIsNotNone(prepared)
            assert prepared is not None
            self.assertEqual(prepared.path, world.resolve())
            self.assertEqual(prepared.filename, "FamilyWorld.zip")
            self.assertIsNone(prepared.cleanup_path)

            folder = root / "saves" / "worlds" / "FolderWorld"
            folder.mkdir()
            (folder / "chunk.bin").write_bytes(b"CHUNK")
            from game_server.world_save import ActiveWorld

            dir_world = ActiveWorld(
                bytes=5,
                path=str(folder),
                label="FolderWorld",
                scope="named_path",
            )
            zipped = prepare_world_download(dir_world, data_dir=str(root))
            self.assertIsNotNone(zipped)
            assert zipped is not None
            self.assertEqual(zipped.filename, "FolderWorld.zip")
            self.assertEqual(zipped.content_type, "application/zip")
            self.assertTrue(zipped.path.is_file())
            self.assertEqual(zipped.cleanup_path, zipped.path)
            import zipfile

            with zipfile.ZipFile(zipped.path) as zf:
                self.assertIn("chunk.bin", zf.namelist())
            zipped.path.unlink(missing_ok=True)

            # Path outside data_dir must be rejected.
            outside = root.parent / "escape.bin"
            outside.write_bytes(b"nope")
            bad = ActiveWorld(
                bytes=4,
                path=str(outside),
                label="escape.bin",
                scope="named_path",
            )
            self.assertFalse(
                world_save_is_downloadable(bad, data_dir=str(root))
            )
            self.assertIsNone(prepare_world_download(bad, data_dir=str(root)))

    def test_no_world_save_spec_uses_backup_sources_only(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.world_save = None
        plugin.backup_paths = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cfg.txt").write_bytes(b"z" * 100)
            located = locate_active_world(
                plugin,
                {"world_name": "FamilyWorld"},
                data_dir=str(root),
            )
            self.assertEqual(located.scope, "backup_sources")
            self.assertEqual(located.bytes, 100)
            self.assertEqual(located.label, "world data")

    def test_named_path_does_not_guess_alternate_layouts(self) -> None:
        plugin = load_plugin(FIXTURE)
        # A save outside declared templates must stay missing — no path guessing.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            odd = root / "worlds" / "FamilyWorld.zip"
            odd.parent.mkdir(parents=True)
            odd.write_bytes(b"x" * 50)
            located = locate_active_world(
                plugin,
                {"world_name": "FamilyWorld"},
                data_dir=str(root),
            )
            self.assertEqual(located.scope, "missing")

            with self.assertRaises(ValueError):
                WorldSaveSpec.from_dict(
                    {
                        "strategy": "heuristic",
                        "paths": ["{data_dir}/saves/{world_name}"],
                    }
                )
            with self.assertRaises(ValueError):
                WorldSaveSpec.from_dict(
                    {
                        "strategy": "named_path",
                        "paths": ["{data_dir}/saves/worlds/{world_name}.zip"],
                        "allow_heuristic_fallback": True,
                    }
                )


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

    def test_dry_run_matches_generic_ready_join_and_count_lines(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp)
            mon.ingest_stdout_line(
                "\x1b[39m[12:59:33] Server started successfully, version: 1.2.3"
            )
            mon.ingest_stdout_line("[12:59:40] Alice joined the game")
            mon.ingest_stdout_line("[12:59:41] Players online: 1")
            highlights = mon.state.highlighted_lines
            self.assertTrue(highlights)
            joined = "\n".join(item["line"] for item in highlights)
            self.assertIn("Server started", joined)
            self.assertNotIn("\x1b[", joined)
            self.assertIn("joined the game", joined.lower())
            self.assertIn("players online", joined.lower())
            # Dry-run game_version candidates highlight but must not capture.
            self.assertIsNone(mon.state.game_version)
            self.assertTrue(
                any(
                    any(m.get("category") == "game_version" for m in item.get("matches") or [])
                    for item in highlights
                )
            )
            ready_stat = next(
                p
                for p in mon.pattern_report()["patterns"]
                if p["category"] == "ready" and p["hits"] > 0
            )
            self.assertEqual(len(ready_stat["recent_lines"]), 1)

    def test_active_game_version_capture(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.log_patterns = LogPatterns(
            game_version=[r"\bgame version\s+(?P<version>\d+(?:\.\d+)+)\b"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            mon = LogMonitor(plugin, tmp)
            mon.ingest_stdout_line(
                '[2026-08-03 12:59:33] Started server using port 14159 '
                'with 10 slots on world "FamilyWorld.zip", game version 1.3.1.'
            )
            self.assertEqual(mon.state.game_version, "1.3.1")
            self.assertIsNotNone(mon.state.game_version_seen_at)
            value, build, installed = _format_game_version(
                {
                    "game_version": mon.state.game_version,
                    "monitor": mon.state.to_dict(),
                    "local_build_id": "24494683",
                    "install_last_updated_at": time.time() - 3600,
                }
            )
            self.assertEqual(value, "1.3.1")
            self.assertEqual(build, "Steam build 24494683")
            self.assertTrue(installed.startswith("Installed "))

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
    def test_archive_summary_and_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            source = root / "world"
            source.mkdir()
            (source / "save.bin").write_bytes(b"x" * 100)
            mgr = BackupManager(
                backup_dir,
                [source],
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
            )
            empty = mgr.archive_summary()
            self.assertEqual(empty["count"], 0)
            count, oldest, newest = _format_backups({"backups": mgr.to_dict()})
            self.assertEqual(count, "0")
            self.assertEqual(oldest, "No backups yet")

            older = backup_dir / "backup-20260101T000000Z-schedule.tar.gz"
            newer = backup_dir / "backup-20260803T120000Z-schedule.tar.gz"
            backup_dir.mkdir()
            older.write_bytes(b"y" * 80)
            newer.write_bytes(b"z" * 80)
            # Force deterministic mtimes.
            os.utime(older, (1_700_000_000, 1_700_000_000))
            os.utime(newer, (1_700_100_000, 1_700_100_000))
            summary = mgr.archive_summary()
            self.assertEqual(summary["count"], 2)
            self.assertEqual(summary["oldest_name"], older.name)
            self.assertEqual(summary["newest_name"], newer.name)
            count, oldest, newest = _format_backups({"backups": mgr.to_dict()})
            self.assertEqual(count, "2")
            self.assertTrue(oldest.startswith("Oldest: "))
            self.assertTrue(newest.startswith("Newest: "))

    def test_pre_restore_safety_copy_outside_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            source = root / "world"
            source.mkdir()
            (source / "save.bin").write_bytes(b"ORIGINAL-WORLD-DATA" * 8)
            failures: list[str] = []
            mgr = BackupManager(
                backup_dir,
                [source],
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
            )
            mgr.set_failure_callback(failures.append)
            archive = mgr.create_backup(reason="schedule")
            self.assertIsNotNone(archive)
            assert archive is not None
            (source / "save.bin").write_bytes(b"CHANGED-WORLD-DATA!" * 8)
            safety = mgr.create_backup(reason="safety", outside_rotation=True)
            self.assertIsNotNone(safety)
            assert safety is not None
            # Safety copies must survive rotation prune of backup-*.
            self.assertTrue(safety.name.startswith("pre-restore-"))
            self.assertTrue(safety.name.endswith(".zip"))
            self.assertTrue(archive.name.endswith(".zip"))
            for i in range(30):
                fake = backup_dir / f"backup-20260101T{i:06d}Z-schedule.zip"
                fake.write_bytes(b"z" * 80)
                os.utime(fake, (1_700_000_000 + i, 1_700_000_000 + i))
            mgr._prune()
            self.assertTrue(safety.is_file())
            self.assertIsNone(mgr.resolve_archive("../evil.zip"))
            mgr.restore_archive(archive.name, prior_safety_backup=safety)
            self.assertEqual(
                (source / "save.bin").read_bytes(),
                b"ORIGINAL-WORLD-DATA" * 8,
            )
            mgr._register_failure("no space")
            self.assertEqual(failures, ["no space"])

    def test_refuse_wipe_without_safety_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            backup_dir.mkdir()
            source = root / "world"
            source.mkdir()
            (source / "save.bin").write_bytes(b"PRECIOUS-SAVE" * 32)
            mgr = BackupManager(
                backup_dir,
                [source],
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
            )
            with self.assertRaises(RuntimeError) as ctx:
                mgr.clear_world_sources(prior_safety_backup=None)
            self.assertIn("safety backup", str(ctx.exception).lower())
            self.assertTrue((source / "save.bin").is_file())
            # Tiny worlds still require a safety copy (not skipped by min_source_bytes).
            mgr.min_source_bytes = 10_000_000
            self.assertTrue(mgr.sources_have_any_data())
            self.assertFalse(mgr.validate_sources()[0])
            safety = mgr.create_safety_backup(reason="safety")
            self.assertIsNotNone(safety)
            assert safety is not None
            mgr.clear_world_sources(prior_safety_backup=safety)
            self.assertFalse(any(source.iterdir()))

    def test_pre_restore_pruned_by_age_not_generational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            backup_dir.mkdir()
            source = root / "world"
            source.mkdir()
            (source / "save.bin").write_bytes(b"DATA" * 64)
            mgr = BackupManager(
                backup_dir,
                [source],
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
                retention=RetentionPolicy(
                    keep_recent=1,
                    keep_daily=0,
                    keep_weekly=0,
                    keep_monthly=0,
                    keep_yearly=0,
                    pre_restore_keep_days=7,
                    profile="test",
                ),
            )
            now = time.time()
            recent = []
            for i in range(3):
                (source / "save.bin").write_bytes(f"NEW-{i}".encode() * 32)
                path = mgr.create_safety_backup(reason=f"new{i}")
                self.assertIsNotNone(path)
                assert path is not None
                os.utime(path, (now - i * 60, now - i * 60))
                recent.append(path)
            old = []
            for i in range(2):
                (source / "save.bin").write_bytes(f"OLD-{i}".encode() * 32)
                path = mgr.create_safety_backup(reason=f"old{i}")
                self.assertIsNotNone(path)
                assert path is not None
                # Older than the 7-day keep window.
                stale = now - (10 * 86400) - i
                os.utime(path, (stale, stale))
                old.append(path)
            # Creating safety copies must not prune yet (prune_after=False).
            self.assertEqual(len(list(backup_dir.glob("pre-restore-*.zip"))), 5)
            mgr.apply_retention()
            remaining = {p.name for p in backup_dir.glob("pre-restore-*.zip")}
            self.assertEqual(remaining, {p.name for p in recent})
            for path in old:
                self.assertFalse(path.is_file())

    def test_pre_update_keeps_only_newest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            source = root / "world"
            source.mkdir()
            (source / "save.bin").write_bytes(b"DATA" * 64)
            mgr = BackupManager(
                backup_dir,
                [source],
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
            )
            first = mgr.create_backup(reason="pre-update")
            second = mgr.create_backup(reason="pre-update")
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first is not None and second is not None
            self.assertTrue(first.name.startswith("pre-update-"))
            self.assertTrue(second.name.startswith("pre-update-"))
            remaining = list(backup_dir.glob("pre-update-*.zip"))
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].name, second.name)
            # Legacy naming is also pruned down to one newest pre-update.
            legacy = backup_dir / "backup-20200101T000000Z-pre-update.tar.gz"
            legacy.write_bytes(b"z" * 80)
            os.utime(legacy, (1_600_000_000, 1_600_000_000))
            mgr.apply_retention()
            pre_updates = mgr.list_pre_update_archives()
            self.assertEqual(len(pre_updates), 1)
            self.assertEqual(pre_updates[0].name, second.name)

    def test_clear_world_sources_resets_to_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            source = root / "world"
            source.mkdir()
            (source / "saves").mkdir()
            (source / "saves" / "worlds").mkdir(parents=True)
            (source / "saves" / "worlds" / "FamilyWorld.zip").write_bytes(
                b"WORLD-BYTES" * 32
            )
            mgr = BackupManager(
                backup_dir,
                [source],
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
            )
            safety = mgr.create_backup(reason="before-empty", outside_rotation=True)
            self.assertIsNotNone(safety)
            assert safety is not None
            result = mgr.clear_world_sources(prior_safety_backup=safety)
            self.assertTrue(result["ok"])
            self.assertTrue(result["empty"])
            # Directory inode kept (ownership/mode); only contents cleared.
            self.assertTrue(source.is_dir())
            self.assertFalse(any(source.iterdir()))
            # Empty world has nothing to validate for a normal backup.
            valid, _reason = mgr.validate_sources()
            self.assertFalse(valid)

    def test_file_world_backup_copies_bytes_without_recompress(self) -> None:
        """Named single-file saves (e.g. Necesse .zip) are copied as-is."""

        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "world"
            worlds = data / "saves" / "worlds"
            worlds.mkdir(parents=True)
            payload = b"PK\x03\x04-NECESSE-WORLD-BYTES" * 64
            world_zip = worlds / "FamilyWorld.zip"
            world_zip.write_bytes(payload)
            backup_dir = root / "backups"

            def locate() -> ActiveWorld:
                return locate_active_world(
                    plugin,
                    {"world_name": "FamilyWorld", "data_dir": str(data)},
                    data_dir=str(data),
                )

            mgr = BackupManager(
                backup_dir,
                [data],
                world_locator=locate,
                data_dir=data,
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
            )
            archive = mgr.create_backup(reason="schedule")
            self.assertIsNotNone(archive)
            assert archive is not None
            self.assertTrue(archive.name.endswith(".zip"))
            self.assertEqual(archive.read_bytes(), payload)
            # Restoring must put the same bytes back on the world path.
            world_zip.write_bytes(b"CHANGED")
            safety = mgr.create_safety_backup(reason="safety")
            self.assertIsNotNone(safety)
            assert safety is not None
            mgr.restore_archive(archive.name, prior_safety_backup=safety)
            self.assertEqual(world_zip.read_bytes(), payload)
            # Empty-world clear removes the save file, not the whole data dir.
            other = data / "cfg.bin"
            other.write_bytes(b"keep-me")
            safety2 = mgr.create_safety_backup(reason="before-empty")
            assert safety2 is not None
            mgr.clear_world_sources(prior_safety_backup=safety2)
            self.assertFalse(world_zip.exists())
            self.assertTrue(other.is_file())

    def test_legacy_tar_gz_restore_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            backup_dir.mkdir()
            source = root / "world"
            source.mkdir()
            (source / "save.bin").write_bytes(b"LEGACY-LIVE" * 16)
            # Build a legacy tar.gz the old supervisor would have written.
            import tarfile

            archive = backup_dir / "backup-20260101T000000Z-schedule.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(source, arcname=source.name)
            (source / "save.bin").write_bytes(b"CHANGED!!!!" * 16)
            mgr = BackupManager(
                backup_dir,
                [source],
                interval_minutes=0,
                enabled=True,
                min_source_bytes=1,
            )
            safety = mgr.create_safety_backup(reason="safety")
            self.assertIsNotNone(safety)
            assert safety is not None
            mgr.restore_archive(archive.name, prior_safety_backup=safety)
            self.assertEqual((source / "save.bin").read_bytes(), b"LEGACY-LIVE" * 16)

    def test_profiles(self) -> None:
        standard = retention_from_profile("standard")
        self.assertEqual(standard.keep_daily, 7)
        self.assertEqual(standard.keep_weekly, 4)
        self.assertEqual(standard.keep_monthly, 12)
        self.assertEqual(standard.pre_restore_keep_days, 7)
        self.assertEqual(retention_from_profile("minimal").pre_restore_keep_days, 1)
        self.assertEqual(retention_from_profile("extended").pre_restore_keep_days, 30)
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


class StatusFormatTests(unittest.TestCase):
    def test_html_page_placeholders_are_only_known_fields(self) -> None:
        """Catch unescaped JSON/CSS braces before they break Ingress GET /."""

        import string

        fields = {
            name
            for _, name, _, _ in string.Formatter().parse(HTML_PAGE)
            if name is not None
        }
        # Literal JSON like {"archive":...} shows up as a field named '"archive"'.
        suspicious = {
            name
            for name in fields
            if name.startswith(("'", '"')) or ":" in name or "," in name
        }
        self.assertEqual(
            suspicious,
            set(),
            "HTML_PAGE has unescaped {...} literals; double braces as {{ }}",
        )
        self.assertEqual(fields, set(_STATUS_HTML_KEYS) | {"base_href"})

    def test_render_status_html_matches_http_handler_path(self) -> None:
        """Integration-ish: full page render with realistic restore UI content."""

        view = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "game_uptime_seconds": 125,
                "supervisor_uptime_seconds": 3600,
                "last_start_reason": "boot",
                "crash_count": 0,
                "app_version": "2.1.19",
                "steamcmd_version": "1",
                "game_version": "1.3.1",
                "local_build_id": "24494683",
                "install_last_updated_at": time.time() - 86400,
                "world_save": {
                    "bytes": 2 * 1024 * 1024,
                    "label": "FamilyWorld.zip",
                    "scope": "named_path",
                    "downloadable": True,
                },
                "disk": {"ok": True, "free_mb": 2048, "min_free_disk_mb": 512},
                "backups": {
                    "archive_count": 1,
                    "restorable": [
                        {
                            "name": "backup-20260804T010000Z-schedule.tar.gz",
                            "kind": "backup",
                            "mtime": time.time() - 3600,
                        }
                    ],
                },
                "waits_for_empty_server": "yes",
                "monitor": {
                    "player_count": 0,
                    "players_known": True,
                    "highlighted_lines": [],
                },
                "log_patterns": {
                    "patterns": [
                        {
                            "mode": "active",
                            "category": "ready",
                            "pattern": r"Started server",
                            "hits": 1,
                            "last_line": "Started server using port 14159",
                        }
                    ]
                },
                "log_captures": [],
            },
            "Necesse",
        )
        html = render_status_html(view, base_href="/api/hassio_ingress/token/")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Necesse", html)
        self.assertNotIn("Start new empty world", html)
        self.assertIn("NEW WORLD", html)
        self.assertIn(f'value="{EMPTY_WORLD}"', html)
        self.assertIn("Restore selected backup", html)
        self.assertIn("capture-row > button", html)
        # Docs examples must survive format() as literal JSON text.
        self.assertIn('{"archive":"…","confirm":true}', html)
        self.assertIn('{"empty":true,"confirm":true}', html)
        self.assertIn("backup-20260804T010000Z-schedule.tar.gz", html)
        self.assertIn('href="/api/hassio_ingress/token/"', html)
        self.assertIn(f"--accent: {DEFAULT_UI_THEME['accent']}", html)
        self.assertIn('href="api/world/download"', html)
        self.assertIn("FamilyWorld.zip", html)
        # Hero order: Uptime → Crashes … World save → Backups → Free disk
        uptime_i = html.index(">Uptime<")
        crashes_i = html.index(">Game server crashes<")
        world_i = html.index(">World save<")
        backups_i = html.index(">Backups<")
        disk_i = html.index(">Free disk<")
        self.assertLess(uptime_i, crashes_i)
        self.assertLess(crashes_i, world_i)
        self.assertLess(world_i, backups_i)
        self.assertLess(backups_i, disk_i)
        self.assertIn("Recent matches (newest first)", html)
        self.assertIn(">Pattern</th>", html)
        # Default (no debug_mode): log-watch hidden; players hidden without tracking.
        self.assertIn('id="log-watch"', html)
        self.assertIn("hidden", view["log_watch_class"])
        self.assertTrue(view["log_watch_hidden"])
        self.assertTrue(view["players_card_hidden"])

    def test_status_http_get_index_returns_200(self) -> None:
        """Live HTTP GET / — same path Ingress hits on OPEN WEB UI."""

        import urllib.error
        import urllib.request

        from game_server.status_http import StatusServer

        status = {
            "running": True,
            "lifecycle": "running",
            "game_uptime_seconds": 10,
            "supervisor_uptime_seconds": 10,
            "crash_count": 0,
            "backups": {"archive_count": 0, "restorable": []},
            "disk": {"ok": True, "free_mb": 1024, "min_free_disk_mb": 512},
            "monitor": {"player_count": 0, "players_known": False},
            "log_patterns": {"patterns": []},
            "log_captures": [],
            "waits_for_empty_server": "no_player_tracking",
        }
        # Bind an ephemeral port; no SUPERVISOR_TOKEN ⇒ peer allowlist open.
        old = os.environ.pop("SUPERVISOR_TOKEN", None)
        server = StatusServer("127.0.0.1", 0, lambda: status, game_name="Necesse")
        try:
            server.start()
            assert server._httpd is not None
            port = server._httpd.server_address[1]
            with urllib.request.urlopen(  # noqa: S310 - local test server
                f"http://127.0.0.1:{port}/", timeout=5
            ) as resp:
                body = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 200)
            self.assertIn("Necesse", body)
            self.assertIn("NEW WORLD", body)
            self.assertNotIn("Start new empty world", body)
            uptime_i = body.index(">Uptime<")
            crashes_i = body.index(">Game server crashes<")
            world_i = body.index(">World save<")
            backups_i = body.index(">Backups<")
            disk_i = body.index(">Free disk<")
            self.assertLess(uptime_i, crashes_i)
            self.assertLess(world_i, backups_i)
            self.assertLess(backups_i, disk_i)
        except urllib.error.HTTPError as exc:
            self.fail(f"GET / failed with HTTP {exc.code}: {exc.read()!r}")
        finally:
            server.stop()
            if old is not None:
                os.environ["SUPERVISOR_TOKEN"] = old

    def test_status_http_world_download_streams_file(self) -> None:
        import urllib.error
        import urllib.request

        from game_server.status_http import StatusServer

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "FamilyWorld.zip"
            payload = b"LIVE-WORLD-BYTES"
            world.write_bytes(payload)

            def download() -> dict:
                return {
                    "path": str(world),
                    "filename": "FamilyWorld.zip",
                    "content_type": "application/zip",
                    "cleanup_path": None,
                }

            old = os.environ.pop("SUPERVISOR_TOKEN", None)
            server = StatusServer(
                "127.0.0.1",
                0,
                lambda: {
                    "running": True,
                    "lifecycle": "running",
                    "monitor": {},
                    "log_patterns": {"patterns": []},
                    "log_captures": [],
                    "backups": {"archive_count": 0, "restorable": []},
                },
                game_name="Necesse",
                world_download_callback=download,
            )
            try:
                server.start()
                assert server._httpd is not None
                port = server._httpd.server_address[1]
                with urllib.request.urlopen(  # noqa: S310 - local test server
                    f"http://127.0.0.1:{port}/api/world/download", timeout=5
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.read(), payload)
                    self.assertIn(
                        "FamilyWorld.zip",
                        resp.headers.get("Content-Disposition", ""),
                    )
            except urllib.error.HTTPError as exc:
                self.fail(
                    f"GET /api/world/download failed with HTTP {exc.code}: "
                    f"{exc.read()!r}"
                )
            finally:
                server.stop()
                if old is not None:
                    os.environ["SUPERVISOR_TOKEN"] = old

    def test_world_save_and_disk_cards_in_ui_view(self) -> None:
        view = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "game_uptime_seconds": 10,
                "last_start_reason": "restore",
                "crash_count": 0,
                "world_save": {
                    "bytes": 2 * 1024 * 1024,
                    "label": "FamilyWorld.zip",
                    "scope": "named_path",
                },
                "disk": {"ok": False, "free_mb": 100, "min_free_disk_mb": 512},
                "backups": {
                    "archive_count": 1,
                    "restorable": [
                        {
                            "name": "backup-20260804T010000Z-schedule.tar.gz",
                            "kind": "backup",
                            "mtime": time.time() - 3600,
                        }
                    ],
                },
                "waits_for_empty_server": "yes",
            },
            "Necesse",
        )
        # Goals: world size readable, low disk flagged, restore list includes archive
        # plus NEW WORLD; disk hero shows free space without min-threshold noise.
        self.assertRegex(view["world_save"], r"\d")
        self.assertIn("FamilyWorld", view["world_save_hint"])
        self.assertNotIn("api/world/download", view["world_save_hint"])
        linked = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "world_save": {
                    "bytes": 2048,
                    "label": "FamilyWorld.zip",
                    "scope": "named_path",
                    "downloadable": True,
                },
                "monitor": {},
            },
            "Necesse",
        )
        self.assertIn('href="api/world/download"', linked["world_save_hint"])
        self.assertIn("FamilyWorld.zip", linked["world_save_hint"])
        self.assertEqual(view["disk_class"], "bad")
        self.assertEqual(view["disk_hint"], "")
        self.assertEqual(view["uptime_hint"], "Since world restore")
        self.assertIn(
            "backup-20260804T010000Z-schedule.tar.gz",
            view["backup_options"],
        )
        self.assertIn("NEW WORLD", view["backup_options"])
        self.assertIn(f'value="{EMPTY_WORLD}"', view["backup_options"])
        value, css, hint = _format_disk(
            {"disk": {"ok": True, "free_mb": 2048, "min_free_disk_mb": 512}}
        )
        self.assertEqual(css, "good")
        self.assertRegex(value, r"GiB|GB|MiB|MB")
        self.assertEqual(hint, "")
        themed = resolve_ui_theme({"accent": "#d4a25a", "good": "#6fbf8a"})
        self.assertEqual(themed["accent"], "#d4a25a")
        self.assertEqual(themed["bg"], DEFAULT_UI_THEME["bg"])
        html = render_status_html(
            _ui_view(
                {"running": True, "lifecycle": "running", "monitor": {}},
                "Necesse",
                ui_theme={"accent": "#d4a25a", "glow": "#243f33"},
            )
        )
        self.assertIn("--accent: #d4a25a", html)
        self.assertIn("#243f33", html)

    def test_fmt_ago(self) -> None:
        now = 1_700_000_000.0
        # Relative ages should stay human-readable (exact wording can drift).
        self.assertIn("now", _fmt_ago(now - 10, now=now))
        self.assertRegex(_fmt_ago(now - 120, now=now), r"\d+m")
        self.assertRegex(_fmt_ago(now - 7200, now=now), r"\d+h")
        self.assertRegex(_fmt_ago(now - 86400 * 3, now=now), r"\d+d")

    def test_format_bytes(self) -> None:
        self.assertIn("B", format_bytes(900))
        self.assertRegex(format_bytes(12 * 1024), r"KB|KiB")
        self.assertRegex(format_bytes(int(1.5 * 1024 * 1024)), r"MB|MiB")
        self.assertRegex(format_bytes(int(2.4 * 1024**3)), r"GB|GiB")

    def test_update_check_hint_and_game_version_age(self) -> None:
        now = time.time()
        hint = _format_update_check_hint(
            {
                "last_update_check_at": now - 600,
                "auto_update_interval_minutes": 15,
                "update_pending": False,
            }
        )
        self.assertTrue(hint.startswith("Checked "))
        self.assertIn("ago", hint)
        daily = _format_update_check_hint(
            {
                "auto_update_interval_minutes": 1440,
                "auto_update_check_hour": 5,
                "update_pending": False,
            }
        )
        self.assertIn("05:00", daily)
        self.assertIn("local", daily)
        # Installed age lives on the game version card (not a dead formatter).
        _version, build, installed = _format_game_version(
            {
                "install_last_updated_at": now - 86400,
                "local_build_id": "24494683",
                "game_version": "0.33.1",
            }
        )
        self.assertEqual(build, "Steam build 24494683")
        self.assertTrue(installed.startswith("Installed "))
        self.assertIn("ago", installed)

    def test_lifecycle_healthz_and_running_label(self) -> None:
        self.assertTrue(healthz_ok({"lifecycle": "running"}))
        self.assertTrue(healthz_ok({"lifecycle": "installing"}))
        self.assertTrue(healthz_ok({"lifecycle": "updating"}))
        self.assertTrue(healthz_ok({"ok": True}))
        self.assertFalse(healthz_ok({"lifecycle": "failed"}))
        self.assertFalse(healthz_ok({"lifecycle": "stopped"}))
        # Crash-loop used to look "starting"/healthy forever.
        self.assertFalse(healthz_ok({"running": False, "starting": False}))
        label, css = _format_running({"lifecycle": "failed"})
        self.assertEqual(label, "failed")
        self.assertEqual(css, "bad")
        label, css = _format_running({"lifecycle": "updating"})
        self.assertEqual(label, "updating")
        self.assertEqual(css, "accent")
        label, css = _format_running({"lifecycle": "updating", "running": True})
        self.assertEqual(label, "stopping for update")
        label, css = _format_running({"lifecycle": "restoring", "running": True})
        self.assertEqual(label, "stopping for restore")
        label, css = _format_running({"lifecycle": "restoring", "running": False})
        self.assertEqual(label, "restoring world")

    def test_restore_api_accepts_query_when_body_empty(self) -> None:
        """Ingress sometimes omits Content-Length; query-string must still work."""

        import http.client

        from game_server.backup import EMPTY_WORLD
        from game_server.status_http import StatusServer

        seen: list[str] = []

        def restore_cb(name: str) -> dict:
            seen.append(name)
            return {"ok": True, "message": "scheduled", "empty": True}

        old = os.environ.pop("SUPERVISOR_TOKEN", None)
        server = StatusServer(
            "127.0.0.1",
            0,
            lambda: {
                "running": True,
                "lifecycle": "running",
                "monitor": {},
                "log_patterns": {"patterns": []},
                "log_captures": [],
                "backups": {"archive_count": 0, "restorable": []},
            },
            game_name="Necesse",
            restore_callback=restore_cb,
        )
        try:
            server.start()
            assert server._httpd is not None
            port = server._httpd.server_address[1]
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.putrequest("POST", "/api/backups/restore?empty=1&confirm=1")
            conn.putheader("Content-Type", "application/json")
            # Intentionally no Content-Length and no body (Ingress failure mode).
            conn.endheaders()
            resp = conn.getresponse()
            body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(resp.status, 200, body)
            self.assertTrue(body.get("ok"))
            self.assertEqual(seen, [EMPTY_WORLD])
            conn.close()
        finally:
            server.stop()
            if old is not None:
                os.environ["SUPERVISOR_TOKEN"] = old

    def test_seconds_until_daily_steam_check_hour(self) -> None:
        now = datetime(2026, 8, 3, 4, 30, 0)
        seconds = GameServerSupervisor._seconds_until_local_hour(5, now=now)
        self.assertEqual(seconds, 30 * 60)
        later = datetime(2026, 8, 3, 5, 0, 1)
        seconds_next_day = GameServerSupervisor._seconds_until_local_hour(
            5, now=later
        )
        self.assertGreater(seconds_next_day, 23 * 3600)

    def test_force_update_now_schedules_even_with_players(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            logs = root / "logs"
            steamcmd_dir = root / "steamcmd"
            world.mkdir()
            logs.mkdir()
            steamcmd_dir.mkdir()
            cfg = SupervisorConfig(
                drop_privileges=False,
                status_http_enabled=False,
                backup_enabled=False,
                ha_notifications=False,
                state_dir=str(root / "state"),
                install_dir=str(root / "game"),
                backup_dir=str(root / "backups"),
                steamcmd_dir=str(steamcmd_dir),
                update_when_empty_only=True,
                game_options={
                    "data_dir": str(world),
                    "logs_dir": str(logs),
                },
            )
            plugin.log_patterns.player_join = [r"(?P<player>.+) joined"]
            plugin.log_patterns.player_leave = [r"(?P<player>.+) left"]
            supervisor = GameServerSupervisor(plugin, cfg)
            self.assertTrue(supervisor.monitor.player_tracking_enabled)
            supervisor.monitor.state.players_known = True
            supervisor.monitor.state.player_count = 2
            supervisor.monitor.state.players = {"Alice", "Bob"}
            # Without a manual force, a normal pending update must wait.
            supervisor.request_update(reason="steam_build")
            self.assertFalse(supervisor._can_apply_update())
            result = supervisor.force_update_now()
            self.assertTrue(result["ok"])
            self.assertTrue(supervisor._update_pending)
            self.assertTrue(supervisor._update_ignore_players)
            self.assertTrue(supervisor._update_bypass_window)
            self.assertEqual(supervisor._update_reason, "manual")
            self.assertTrue(supervisor._can_apply_update())

    def test_update_empty_max_wait_applies_despite_players(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            logs = root / "logs"
            steamcmd_dir = root / "steamcmd"
            world.mkdir()
            logs.mkdir()
            steamcmd_dir.mkdir()
            cfg = SupervisorConfig(
                drop_privileges=False,
                status_http_enabled=False,
                backup_enabled=False,
                ha_notifications=False,
                state_dir=str(root / "state"),
                install_dir=str(root / "game"),
                backup_dir=str(root / "backups"),
                steamcmd_dir=str(steamcmd_dir),
                update_when_empty_only=True,
                update_empty_max_wait_hours=24,
                game_options={
                    "data_dir": str(world),
                    "logs_dir": str(logs),
                },
            )
            plugin.log_patterns.player_join = [r"(?P<player>.+) joined"]
            plugin.log_patterns.player_leave = [r"(?P<player>.+) left"]
            supervisor = GameServerSupervisor(plugin, cfg)
            supervisor.monitor.state.players_known = True
            supervisor.monitor.state.player_count = 1
            supervisor.monitor.state.players = {"Alice"}
            supervisor.request_update(reason="steam_build")
            self.assertFalse(supervisor._can_apply_update())
            # Still pending but under the cap.
            supervisor._update_pending_since = time.time() - (23 * 3600)
            self.assertFalse(supervisor._can_apply_update())
            # Past the cap: apply even with players online.
            supervisor._update_pending_since = time.time() - (25 * 3600)
            self.assertTrue(supervisor._can_apply_update())
            self.assertTrue(supervisor._update_ignore_players)
            status = supervisor.status()
            self.assertEqual(status["update_empty_max_wait_hours"], 24)
            self.assertIsNotNone(status["update_pending_since"])

    def test_version_mismatch_checks_steam_before_scheduling_stop(
        self,
    ) -> None:
        """Mismatch probes Steam first; only schedules apply when an update exists."""

        from unittest import mock

        from game_server.steamcmd import UpdateCheckResult

        plugin = load_plugin(NECESSE_PLUGIN)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            logs = root / "logs"
            steamcmd_dir = root / "steamcmd"
            world.mkdir()
            logs.mkdir()
            steamcmd_dir.mkdir()
            cfg = SupervisorConfig(
                drop_privileges=False,
                status_http_enabled=False,
                backup_enabled=False,
                ha_notifications=False,
                state_dir=str(root / "state"),
                install_dir=str(root / "game"),
                backup_dir=str(root / "backups"),
                steamcmd_dir=str(steamcmd_dir),
                update_when_empty_only=True,
                update_on_version_mismatch=True,
                update_window_start_hour=2,
                update_window_end_hour=3,
                game_options={
                    "data_dir": str(world),
                    "logs_dir": str(logs),
                },
            )
            supervisor = GameServerSupervisor(plugin, cfg)
            supervisor.monitor.state.players_known = True
            supervisor.monitor.state.player_count = 1
            supervisor.monitor.state.players = {"76561197968471340"}
            supervisor._on_version_mismatch(
                '[2026-08-04 08:45:04] Client "1" had wrong version (1.3.0).'
            )
            # Must not schedule a stop/apply until Steam confirms a newer build.
            self.assertFalse(supervisor._update_pending)
            self.assertTrue(supervisor._urgent_update_check)

            with mock.patch(
                "game_server.supervisor.steamcmd.update_available",
                return_value=UpdateCheckResult(
                    update_available=False,
                    local_build_id="100",
                    remote_build_id="100",
                ),
            ):
                supervisor._run_urgent_update_check()
            self.assertFalse(supervisor._update_pending)
            self.assertFalse(supervisor._urgent_update_check)

            supervisor._on_version_mismatch(
                '[2026-08-04 08:45:05] Client "1" had wrong version (1.3.0).'
            )
            with mock.patch(
                "game_server.supervisor.steamcmd.update_available",
                return_value=UpdateCheckResult(
                    update_available=True,
                    local_build_id="100",
                    remote_build_id="101",
                ),
            ):
                supervisor._run_urgent_update_check()
            self.assertTrue(supervisor._update_pending)
            self.assertEqual(supervisor._update_reason, "version_mismatch")
            self.assertTrue(supervisor._update_bypass_window)
            self.assertFalse(supervisor._update_ignore_players)
            self.assertFalse(supervisor._can_apply_update())
            supervisor.monitor.state.players = set()
            supervisor.monitor.state.player_count = 0
            self.assertTrue(supervisor._can_apply_update())
            self.assertEqual(plugin.stop_timeout_seconds, 240)
            self.assertEqual(plugin.stop_stdin_commands, ["save", "exit"])

    def test_request_empty_world_reset_schedules_clear(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            logs = root / "logs"
            world.mkdir()
            logs.mkdir()
            (world / "save.bin").write_bytes(b"LIVE-WORLD" * 16)
            cfg = SupervisorConfig(
                drop_privileges=False,
                status_http_enabled=False,
                backup_enabled=True,
                ha_notifications=False,
                state_dir=str(root / "state"),
                install_dir=str(root / "game"),
                backup_dir=str(root / "backups"),
                steamcmd_dir=str(root / "steamcmd"),
                game_options={
                    "data_dir": str(world),
                    "logs_dir": str(logs),
                },
            )
            supervisor = GameServerSupervisor(plugin, cfg)
            # Point backup sources at our temp world (plugin defaults are /data/...).
            supervisor.backups.sources = [world]
            supervisor.backups.min_source_bytes = 1
            result = supervisor.request_restore(EMPTY_WORLD)
            self.assertTrue(result["ok"])
            self.assertTrue(result["empty"])
            self.assertEqual(supervisor._restore_pending, EMPTY_WORLD)
            # Avoid launching a real game binary in unit tests.
            supervisor.process.start = lambda reason="boot": None  # type: ignore[method-assign]
            supervisor.process.stop = lambda timeout=None: None  # type: ignore[method-assign]
            supervisor._apply_restore(EMPTY_WORLD)
            self.assertTrue(world.is_dir())
            self.assertFalse(any(world.iterdir()))
            self.assertIsNone(supervisor.last_restore_error)
            safety_copies = list((root / "backups").glob("pre-restore-*"))
            self.assertEqual(len(safety_copies), 1)

    def test_status_read_does_not_mutate_build_id_or_lie_about_starting(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            logs = root / "logs"
            install = root / "game"
            world.mkdir()
            logs.mkdir()
            install.mkdir()
            steamapps = install / "steamapps"
            steamapps.mkdir()
            manifest = steamapps / f"appmanifest_{plugin.steam_app_id}.acf"
            # Minimal Steam ACF so read_local_install_meta finds a build id.
            manifest.write_text(
                f'"AppState"\n{{\n\t"appid"\t\t"{plugin.steam_app_id}"\n'
                '\t"buildid"\t\t"999888777"\n'
                '\t"LastUpdated"\t\t"1700000000"\n}\n',
                encoding="utf-8",
            )
            cfg = SupervisorConfig(
                drop_privileges=False,
                status_http_enabled=False,
                backup_enabled=False,
                ha_notifications=False,
                state_dir=str(root / "state"),
                install_dir=str(install),
                backup_dir=str(root / "backups"),
                steamcmd_dir=str(root / "steamcmd"),
                game_options={"data_dir": str(world), "logs_dir": str(logs)},
            )
            supervisor = GameServerSupervisor(plugin, cfg)
            self.assertIsNone(supervisor.local_build_id)
            status = supervisor.status()
            self.assertEqual(status["local_build_id"], "999888777")
            # status() must remain a read — do not hydrate mutable cache.
            self.assertIsNone(supervisor.local_build_id)
            self.assertEqual(status["lifecycle"], "starting")
            self.assertTrue(status["starting"])
            self.assertEqual(status["player_gating"], status["waits_for_empty_server"])
            health = supervisor.health()
            self.assertTrue(health["ok"])
            self.assertEqual(health["lifecycle"], "starting")

    def test_capture_archive_path_rejects_traversal(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "logs"
            state = root / "state"
            logs.mkdir()
            state.mkdir()
            evil = state / "evil"
            evil.mkdir()
            (evil / "capture.tar.gz").write_bytes(b"pwn")
            good = state / "captures" / "goodid"
            # LogToolbox creates captures under state/captures
            box = LogToolbox(plugin, logs, state, recent_lines_provider=lambda: [])
            box.captures_dir.mkdir(parents=True, exist_ok=True)
            capture_dir = box.captures_dir / "20260803T000000Z"
            capture_dir.mkdir()
            (capture_dir / "capture.tar.gz").write_bytes(b"ok")
            self.assertIsNotNone(box.capture_archive_path("20260803T000000Z"))
            self.assertIsNone(box.capture_archive_path("../evil"))
            self.assertIsNone(box.capture_archive_path(".."))
            self.assertIsNone(box.capture_archive_path("evil/../../etc"))

    def test_uptime_crashes_game_version_and_subtitle(self) -> None:
        uptime, hint = _format_uptime(
            {
                "running": True,
                "game_uptime_seconds": 125,
                "last_start_reason": "boot",
            }
        )
        self.assertEqual(uptime, "2m 5s")
        self.assertEqual(hint, "Since first start")
        self.assertEqual(
            _format_uptime(
                {
                    "running": True,
                    "game_uptime_seconds": 10,
                    "last_start_reason": "crash",
                }
            )[1],
            "Since crash restart",
        )
        self.assertEqual(
            _format_uptime(
                {
                    "running": True,
                    "game_uptime_seconds": 10,
                    "last_start_reason": "update",
                }
            )[1],
            "Since server update",
        )
        self.assertEqual(
            _format_crashes_hint({"supervisor_uptime_seconds": 3600}),
            "Supervisor uptime: 1h 0m",
        )
        version, build, installed = _format_game_version({})
        self.assertEqual(version, "unknown")
        self.assertEqual(build, "")
        self.assertEqual(installed, "")
        self.assertEqual(
            _format_subtitle({"app_version": "2.1.12", "steamcmd_version": "1785186678"}),
            "Dedicated server supervisor v2.1.12 · SteamCMD 1785186678",
        )

    def test_hide_dry_run_when_active_category_exists(self) -> None:
        patterns = [
            {
                "mode": "active",
                "category": "ready",
                "pattern": r"Started server",
                "hits": 2,
                "recent_lines": ["Started server on port 1", "Started server again"],
                "last_line": "Started server again",
            },
            {
                "mode": "dry_run",
                "category": "ready",
                "pattern": r"\bready\b",
                "hits": 5,
                "recent_lines": ["ready"],
                "last_line": "ready",
            },
            {
                "mode": "dry_run",
                "category": "player_count",
                "pattern": r"players online",
                "hits": 1,
                "recent_lines": ["Players online: 2"],
                "last_line": "Players online: 2",
            },
            {
                "mode": "dry_run",
                "category": "player_count",
                "pattern": r"online players",
                "hits": 1,
                "recent_lines": ["Online players: 2"],
                "last_line": "Online players: 2",
            },
        ]
        rows = _format_pattern_rows(patterns)
        # One row per regex; dry-run ready hidden because active ready exists.
        self.assertEqual(rows.count("<tr>"), 3)
        self.assertIn("ready", rows)
        self.assertIn("player_count", rows)
        self.assertIn("Started server", rows)
        self.assertIn("Started server again", rows)
        self.assertIn("Players online: 2", rows)
        self.assertIn("Online players: 2", rows)
        self.assertIn("recent-matches", rows)
        self.assertNotIn(r"\bready\b", rows)
        highlights = _format_highlights(
            [
                {
                    "line": "Started server on port 1",
                    "matches": [
                        {"mode": "active", "category": "ready"},
                        {"mode": "dry_run", "category": "ready"},
                    ],
                }
            ],
            active_categories={"ready"},
        )
        self.assertIn("active:ready", highlights)
        self.assertNotIn("dry_run:ready", highlights)

    def test_debug_mode_controls_log_watch_and_players_card(self) -> None:
        hidden = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "debug_mode": False,
                "waits_for_empty_server": "no_player_tracking",
                "log_patterns": {
                    "player_tracking_enabled": False,
                    "patterns": [
                        {
                            "mode": "dry_run",
                            "category": "player_count",
                            "pattern": r"players online",
                            "hits": 1,
                            "recent_lines": ["Players online: 0"],
                        }
                    ],
                },
                "monitor": {"players_known": False},
            },
            "ExampleGame",
        )
        self.assertTrue(hidden["log_watch_hidden"])
        self.assertTrue(hidden["players_card_hidden"])
        self.assertIn("hidden", hidden["log_watch_class"])
        self.assertIn("hidden", hidden["players_card_class"])

        debug = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "debug_mode": True,
                "waits_for_empty_server": "no_player_tracking",
                "log_patterns": {
                    "player_tracking_enabled": False,
                    "patterns": [
                        {
                            "mode": "dry_run",
                            "category": "player_count",
                            "pattern": r"players online",
                            "hits": 1,
                            "recent_lines": ["Players online: 0"],
                        }
                    ],
                },
                "monitor": {"players_known": False},
            },
            "ExampleGame",
        )
        self.assertFalse(debug["log_watch_hidden"])
        self.assertFalse(debug["players_card_hidden"])
        self.assertEqual(debug["log_watch_class"], "")
        self.assertEqual(debug["players_card_class"], "")

        # Count mode: active join/leave alone is not enough — need player_count.
        join_leave_only = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "debug_mode": False,
                "waits_for_empty_server": "yes",
                "player_tracking_mode": "count",
                "log_patterns": {
                    "player_tracking_enabled": True,
                    "patterns": [
                        {
                            "mode": "active",
                            "category": "player_join",
                            "pattern": r"joined",
                            "hits": 1,
                            "recent_lines": ["Alice joined"],
                        },
                        {
                            "mode": "active",
                            "category": "player_leave",
                            "pattern": r"left",
                            "hits": 1,
                            "recent_lines": ["Alice left"],
                        },
                        {
                            "mode": "dry_run",
                            "category": "player_count",
                            "pattern": r"players online",
                            "hits": 0,
                        },
                    ],
                },
                "monitor": {"players_known": True, "player_count": 1},
            },
            "Necesse",
        )
        self.assertTrue(join_leave_only["log_watch_hidden"])
        self.assertTrue(join_leave_only["players_card_hidden"])

        counted = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "debug_mode": False,
                "waits_for_empty_server": "yes",
                "player_tracking_mode": "count",
                "log_patterns": {
                    "player_tracking_enabled": True,
                    "patterns": [
                        {
                            "mode": "active",
                            "category": "player_count",
                            "pattern": r"Players online:\s*(?P<count>\d+)",
                            "hits": 1,
                            "recent_lines": ["Players online: 1"],
                        }
                    ],
                },
                "monitor": {"players_known": True, "player_count": 1},
            },
            "ExampleGame",
        )
        self.assertTrue(counted["log_watch_hidden"])
        self.assertFalse(counted["players_card_hidden"])
        self.assertEqual(counted["players_label"], "Number of players")
        self.assertEqual(counted["players"], "1")

        presence = _ui_view(
            {
                "running": True,
                "lifecycle": "running",
                "debug_mode": False,
                "waits_for_empty_server": "yes",
                "player_tracking_mode": "presence",
                "log_patterns": {
                    "player_tracking_enabled": True,
                    "patterns": [
                        {
                            "mode": "active",
                            "category": "player_join",
                            "pattern": r"Connected",
                            "hits": 1,
                            "recent_lines": ["Client: Pat connected"],
                        },
                        {
                            "mode": "active",
                            "category": "players_empty",
                            "pattern": r"No clients connected",
                            "hits": 1,
                            "recent_lines": ["No clients connected"],
                        },
                    ],
                },
                "monitor": {
                    "players_known": True,
                    "player_count": 0,
                    "players_present": False,
                },
            },
            "Stationeers",
        )
        self.assertFalse(presence["players_card_hidden"])
        self.assertEqual(presence["players_label"], "Players")
        self.assertEqual(presence["players"], "Idle")


class ProcessCommandBuildTests(unittest.TestCase):
    """Generic argv_prefix / settings_map CLI building (non-Java Steam servers)."""

    def test_argv_prefix_and_settings_block(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.executable = ["./server.x86_64"]
        plugin.arg_map = {}
        plugin.bool_style = "true_false"
        plugin.argv_prefix = [
            "-file",
            "start",
            "{world_name}",
            "{world_type}",
            "{difficulty}",
            "-noclear",
            "-logFile",
            "-",
            "-settingspath",
            "{data_dir}/settings.xml",
        ]
        plugin.settings_flag = "-settings"
        plugin.fixed_settings = {
            "StartLocalHost": "true",
            "SavePath": "{data_dir}",
        }
        plugin.settings_map = {
            "server_name": "ServerName",
            "server_port": "GamePort",
            "server_password": "ServerPassword",
            "server_slots": "ServerMaxPlayers",
            "auto_save": "AutoSave",
        }
        cfg = SupervisorConfig(
            drop_privileges=False,
            status_http_enabled=False,
            backup_enabled=False,
            ha_notifications=False,
            game_options={
                "world_name": "MyStation",
                "world_type": "Lunar",
                "difficulty": "",
                "server_name": "Family Station",
                "server_port": 27016,
                "server_password": "",
                "server_slots": 8,
                "auto_save": True,
                "data_dir": "/data/world",
                "logs_dir": "/data/logs",
            },
        )
        plugin.data_dir = "/data/world"
        plugin.logs_dir = "/data/logs"
        cmd = ProcessManager(plugin, cfg).build_command()
        self.assertEqual(
            cmd,
            [
                "./server.x86_64",
                "-file",
                "start",
                "MyStation",
                "Lunar",
                "-noclear",
                "-logFile",
                "-",
                "-settingspath",
                "/data/world/settings.xml",
                "-settings",
                "StartLocalHost",
                "true",
                "SavePath",
                "/data/world",
                "ServerName",
                "Family Station",
                "GamePort",
                "27016",
                "ServerMaxPlayers",
                "8",
                "AutoSave",
                "true",
            ],
        )
        # Empty optional password must not appear as a settings pair.
        self.assertNotIn("ServerPassword", cmd)

    def test_arg_map_still_works_for_simple_flags(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.executable = ["java", "-jar", "Server.jar", "-nogui"]
        plugin.argv_prefix = []
        plugin.settings_flag = ""
        plugin.settings_map = {}
        plugin.fixed_settings = {}
        plugin.arg_map = {"world_name": "-world", "server_port": "-port"}
        plugin.bool_style = "one_zero"
        cfg = SupervisorConfig(
            drop_privileges=False,
            status_http_enabled=False,
            backup_enabled=False,
            ha_notifications=False,
            game_options={
                "world_name": "FamilyWorld",
                "server_port": 14159,
                "java_opts": "-Xmx1G",
            },
        )
        cmd = ProcessManager(plugin, cfg).build_command()
        self.assertEqual(
            cmd,
            [
                "java",
                "-Xmx1G",
                "-jar",
                "Server.jar",
                "-nogui",
                "-world",
                "FamilyWorld",
                "-port",
                "14159",
            ],
        )


class ProcessStopTests(unittest.TestCase):
    def test_stop_uses_plugin_timeout_when_config_unset(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.stop_timeout_seconds = 240
        plugin.stop_stdin_commands = ["save", "exit"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = SupervisorConfig(
                drop_privileges=False,
                status_http_enabled=False,
                backup_enabled=False,
                ha_notifications=False,
                stop_timeout_seconds=0,
                state_dir=str(root / "state"),
                install_dir=str(root / "game"),
                backup_dir=str(root / "backups"),
                steamcmd_dir=str(root / "steamcmd"),
                game_options={
                    "data_dir": str(root / "world"),
                    "logs_dir": str(root / "logs"),
                },
            )
            (root / "world").mkdir()
            (root / "logs").mkdir()
            plugin.data_dir = str(root / "world")
            plugin.logs_dir = str(root / "logs")
            plugin.working_dir = str(root / "game")
            (root / "game").mkdir()
            # Cooperative "game": exit when stdin closes / receives a line.
            plugin.executable = [
                sys.executable,
                "-c",
                (
                    "import sys\n"
                    "for line in sys.stdin:\n"
                    "    line=line.strip()\n"
                    "    if line == 'exit':\n"
                    "        raise SystemExit(0)\n"
                ),
            ]
            mgr = ProcessManager(plugin, cfg)
            mgr.start(reason="boot")
            self.assertTrue(mgr.running)
            started = time.time()
            mgr.stop()
            elapsed = time.time() - started
            self.assertFalse(mgr.running)
            self.assertTrue(mgr.intentional_stop)
            # Should finish via stdin exit well under the 240s budget.
            self.assertLess(elapsed, 20)

    def test_stop_escalates_when_process_ignores_stdin(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.stop_timeout_seconds = 8
        plugin.stop_stdin_commands = ["save", "exit"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = SupervisorConfig(
                drop_privileges=False,
                status_http_enabled=False,
                backup_enabled=False,
                ha_notifications=False,
                stop_timeout_seconds=0,
                state_dir=str(root / "state"),
                install_dir=str(root / "game"),
                backup_dir=str(root / "backups"),
                steamcmd_dir=str(root / "steamcmd"),
                game_options={
                    "data_dir": str(root / "world"),
                    "logs_dir": str(root / "logs"),
                },
            )
            (root / "world").mkdir()
            (root / "logs").mkdir()
            plugin.data_dir = str(root / "world")
            plugin.logs_dir = str(root / "logs")
            plugin.working_dir = str(root / "game")
            (root / "game").mkdir()
            # Ignore SIGTERM briefly so escalation is observable; exit on SIGKILL.
            plugin.executable = [
                sys.executable,
                "-c",
                (
                    "import signal, time\n"
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    "time.sleep(60)\n"
                ),
            ]
            mgr = ProcessManager(plugin, cfg)
            mgr.start(reason="boot")
            self.assertTrue(mgr.running)
            mgr.stop()
            self.assertFalse(mgr.running)
            self.assertTrue(mgr.intentional_stop)


class LogBridgeTests(unittest.TestCase):
    def test_recent_line_deduper(self) -> None:
        deduper = RecentLineDeduper(maxlen=8, ttl_seconds=30)
        self.assertTrue(deduper.remember_if_new("Player joined"))
        self.assertFalse(deduper.remember_if_new("  Player joined  "))
        self.assertTrue(deduper.remember_if_new("Player left"))
        self.assertFalse(deduper.remember_if_new(""))

    def test_strip_ansi(self) -> None:
        raw = "\x1b[34m[2026-08-03 12:59:33] Started server using port 14159\x1b[39m"
        self.assertEqual(
            strip_ansi(raw),
            "[2026-08-03 12:59:33] Started server using port 14159",
        )

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
    def test_remember_steamcmd_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steamcmd_version.txt"
            configure_steamcmd_version_path(path)
            try:
                remembered = remember_steamcmd_version(
                    "Steam Console Client (c) Valve Corporation - version 1785186678"
                )
                self.assertEqual(remembered, "1785186678")
                self.assertEqual(steamcmd_client_version(), "1785186678")
                self.assertEqual(path.read_text(encoding="utf-8").strip(), "1785186678")
            finally:
                configure_steamcmd_version_path(None)

    def test_missing_configuration_detection(self) -> None:
        self.assertTrue(
            looks_missing_configuration(
                "ERROR! Failed to install app '1169370' (Missing configuration)"
            )
        )
        self.assertFalse(looks_missing_configuration("Success! App '1' fully installed"))
        self.assertTrue(
            looks_missing_file_permissions(
                "ERROR! Failed to install app '1169370' (Missing file permissions)"
            )
        )

    def test_server_installed_ignores_steamapps_scaffolding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            (root / "steamapps").mkdir(parents=True)
            self.assertFalse(server_installed(root, "Server.jar"))
            self.assertFalse(server_installed(root))
            (root / "Server.jar").write_bytes(b"x")
            self.assertTrue(server_installed(root, "Server.jar"))

    def test_app_info_cmd_pins_platform(self) -> None:
        plugin = load_plugin(FIXTURE)
        plugin.steam_platform = "linux"
        with tempfile.TemporaryDirectory() as tmp:
            steamcmd_dir = Path(tmp) / "steamcmd"
            steamcmd_dir.mkdir()
            (steamcmd_dir / "steamcmd.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            cmd = _app_info_cmd(steamcmd_dir, plugin)
            joined = " ".join(cmd)
            self.assertIn("+@sSteamCmdForcePlatformType linux", joined)
            self.assertIn("+app_info_print", joined)

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

        def fake_run(  # noqa: ANN001
            cmd,
            *,
            timeout,
            prefix="[steamcmd]",
            env=None,
            run_uid=None,
            run_gid=None,
            stop_event=None,
        ):
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

    def test_read_local_install_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "game"
            steamapps = install_dir / "steamapps"
            steamapps.mkdir(parents=True)
            (steamapps / "appmanifest_1.acf").write_text(
                '"AppState"\n{\n\t"buildid"\t\t"24494683"\n'
                '\t"LastUpdated"\t\t"1722686400"\n}\n',
                encoding="utf-8",
            )
            meta = read_local_install_meta(install_dir, 1)
            self.assertEqual(meta["build_id"], "24494683")
            self.assertEqual(meta["last_updated"], 1722686400)

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

    def test_update_check_error_is_not_up_to_date(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "game"
            install_dir.mkdir()
            steamcmd_dir = Path(tmp) / "steamcmd"
            steamcmd_dir.mkdir()
            (steamcmd_dir / "steamcmd.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            import game_server.steamcmd as steamcmd_mod

            def boom(*_a, **_k):  # noqa: ANN001
                raise steamcmd_mod.SteamCMDError("steam unavailable")

            original = steamcmd_mod.fetch_remote_build_id
            steamcmd_mod.fetch_remote_build_id = boom  # type: ignore[assignment]
            try:
                result = update_available(steamcmd_dir, install_dir, plugin)
            finally:
                steamcmd_mod.fetch_remote_build_id = original  # type: ignore[assignment]
            self.assertIsInstance(result, UpdateCheckResult)
            self.assertFalse(result.check_ok)
            self.assertFalse(result.update_available)
            self.assertIn("steam unavailable", result.error or "")


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
