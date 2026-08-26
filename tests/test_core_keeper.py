#!/usr/bin/env python3
"""Core Keeper game-layer checks (plugin + stable Game ID)."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "core-keeper-dedicated-server" / "games" / "game.yaml"
DEFAULTS = ROOT / "core-keeper-dedicated-server" / "haos_defaults.py"
CONFIG = ROOT / "core-keeper-dedicated-server" / "config.yaml"
WRAPPER = ROOT / "core-keeper-dedicated-server" / "launch_wrapper.sh"

sys.path.insert(0, str(ROOT / "game-server-base"))
from game_server.plugin import load_plugin  # noqa: E402
from game_server.process_manager import ProcessManager  # noqa: E402
from game_server.config import SupervisorConfig  # noqa: E402
from game_server.world_save import locate_active_world  # noqa: E402


def _load_defaults():
    spec = importlib.util.spec_from_file_location("ck_haos_defaults", DEFAULTS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreKeeperPluginTests(unittest.TestCase):
    def test_plugin_is_steamcmd_core_keeper(self) -> None:
        plugin = load_plugin(PLUGIN)
        self.assertEqual(plugin.name, "Core Keeper")
        self.assertEqual(plugin.steam_app_id, 1963720)
        self.assertEqual(plugin.install_marker, "CoreKeeperServer_Data")
        self.assertEqual(plugin.executable, ["/opt/launch_wrapper.sh"])
        self.assertEqual(plugin.log_patterns.ready, ["Started session with info:"])
        self.assertEqual(plugin.log_patterns.player_join, [])
        self.assertEqual(
            plugin.log_patterns.game_version,
            [r"Game version:\s+(?P<version>\S+)"],
        )
        self.assertIn("ready", plugin.log_pattern_candidates)
        self.assertNotIn("server_port", plugin.arg_map)
        self.assertIn("-datapath", plugin.argv_prefix)
        self.assertIn("{data_dir}", plugin.argv_prefix)

    def test_world_save_slot_zero(self) -> None:
        plugin = load_plugin(PLUGIN)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "world"
            worlds = data_dir / "worlds"
            worlds.mkdir(parents=True)
            save = worlds / "0.world.gzip"
            save.write_bytes(b"fake-world" * 200)
            other = worlds / "3.world.gzip"
            other.write_bytes(b"other-world" * 200)
            active = locate_active_world(
                plugin,
                {"world_index": 0, "data_dir": str(data_dir)},
                data_dir=str(data_dir),
            )
            self.assertEqual(active.path, str(save))
            self.assertEqual(active.kind, "file")
            self.assertEqual(active.label, "0.world.gzip")
            slotted = locate_active_world(
                plugin,
                {"world_index": 3, "data_dir": str(data_dir)},
                data_dir=str(data_dir),
            )
            self.assertEqual(slotted.path, str(other))
            self.assertEqual(slotted.label, "3.world.gzip")

    def test_cli_keeps_numeric_zero_from_env_strings(self) -> None:
        plugin = load_plugin(PLUGIN)
        cfg = SupervisorConfig(
            drop_privileges=False,
            status_http_enabled=False,
            backup_enabled=False,
            ha_notifications=False,
            game_options={
                "world_name": "FamilyCore",
                "world_index": "0",
                "world_mode": "0",
                "world_seed": "",
                "game_id": "abcdeFGHIJ12345KLMN",
                "server_slots": "8",
                "data_dir": "/data/world",
                "logs_dir": "/data/logs",
            },
        )
        cmd = ProcessManager(plugin, cfg).build_command()
        self.assertEqual(cmd[0], "/opt/launch_wrapper.sh")
        self.assertIn("-world", cmd)
        self.assertEqual(cmd[cmd.index("-world") + 1], "0")
        self.assertEqual(cmd[cmd.index("-worldmode") + 1], "0")
        self.assertEqual(cmd[cmd.index("-gameid") + 1], "abcdeFGHIJ12345KLMN")
        self.assertEqual(cmd[cmd.index("-maxplayers") + 1], "8")
        self.assertNotIn("-port", cmd)

    def test_ha_config_does_not_publish_a_game_port(self) -> None:
        import yaml

        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.assertNotIn("ports", data)
        self.assertFalse(data.get("host_network"))
        self.assertEqual(data["schema"]["world_index"], "int(0,29)")
        self.assertEqual(data["slug"], "core_keeper_dedicated_server")
        self.assertEqual(data["arch"], ["amd64"])

    def test_launch_wrapper_is_executable(self) -> None:
        self.assertTrue(WRAPPER.is_file())
        self.assertTrue(os.access(WRAPPER, os.X_OK), f"{WRAPPER} must be chmod +x")
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("GameInfo.txt", text)
        self.assertIn("Xvfb", text)
        self.assertIn("steamclient.so", text)


class CoreKeeperHaosDefaultsTests(unittest.TestCase):
    def test_default_game_id_stable_per_install(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = mod.default_game_id(state_dir=state)
            second = mod.default_game_id(state_dir=state)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 20)
            self.assertTrue(set(first) <= set(mod._GAME_ID_ALPHABET))
            # Official ARGUMENTS.txt: Game ID may not include Y, y, x, 0, or O.
            self.assertTrue(set(mod._GAME_ID_ALPHABET).isdisjoint(set("Yyx0O")))
            self.assertTrue((state / "instance_salt").is_file())

    def test_different_installs_get_different_ids(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            id_a = mod.default_game_id(state_dir=a)
            id_b = mod.default_game_id(state_dir=b)
            if id_a == id_b:
                (Path(b) / "instance_salt").unlink()
                id_b = mod.default_game_id(state_dir=b)
            self.assertNotEqual(id_a, id_b)

    def test_resolve_prefers_options_then_env(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            options = root / "options.json"
            options.write_text('{"game_id": "PinnedJoinCode12345"}', encoding="utf-8")
            self.assertEqual(
                mod.resolve_game_id(
                    options_file=options,
                    state_dir=root / "state",
                    install_dir=root / "game",
                    data_dir=root / "world",
                    environ={},
                ),
                "PinnedJoinCode12345",
            )
            self.assertEqual(
                mod.resolve_game_id(
                    options_file=options,
                    state_dir=root / "state",
                    install_dir=root / "game",
                    data_dir=root / "world",
                    environ={"GAME_ID": "FromEnvJoinCode1234"},
                ),
                "FromEnvJoinCode1234",
            )
            options.write_text('{"game_id": ""}', encoding="utf-8")
            generated = mod.resolve_game_id(
                options_file=options,
                state_dir=root / "state",
                install_dir=root / "game",
                data_dir=root / "world",
                environ={},
            )
            self.assertEqual(len(generated), 20)

    def test_invalid_pinned_id_does_not_pass_through(self) -> None:
        mod = _load_defaults()
        self.assertTrue(mod.is_valid_game_id("abcdeFGHIJ12345KLMN"))
        self.assertFalse(mod.is_valid_game_id("short"))
        self.assertFalse(mod.is_valid_game_id("YYYYYYYYYYYYYYY"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            options = root / "options.json"
            options.write_text('{"game_id": "not-valid"}', encoding="utf-8")
            game = root / "game"
            game.mkdir()
            (game / "GameID.txt").write_text("PersistedJoinCode123", encoding="utf-8")
            resolved = mod.resolve_game_id(
                options_file=options,
                state_dir=root / "state",
                install_dir=game,
                data_dir=root / "world",
                environ={},
            )
            self.assertEqual(resolved, "PersistedJoinCode123")

    def test_recovers_id_from_server_config_if_salt_missing(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            world.mkdir()
            (world / "ServerConfig.json").write_text(
                '{"gameId": "FromConfigJoinCode1"}',
                encoding="utf-8",
            )
            resolved = mod.resolve_game_id(
                options_file=root / "missing.json",
                state_dir=root / "state",
                install_dir=root / "game",
                data_dir=world,
                environ={},
            )
            self.assertEqual(resolved, "FromConfigJoinCode1")


if __name__ == "__main__":
    unittest.main()
