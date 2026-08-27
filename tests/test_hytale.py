#!/usr/bin/env python3
"""Hytale game-layer checks (plugin, names, device-code scrape, config merge)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "hytale-dedicated-server" / "games" / "game.yaml"
DEFAULTS = ROOT / "hytale-dedicated-server" / "haos_defaults.py"
CONFIG = ROOT / "hytale-dedicated-server" / "config.yaml"
WRAPPER = ROOT / "hytale-dedicated-server" / "launch_wrapper.sh"
RUNSH = ROOT / "hytale-dedicated-server" / "run.sh"
BASE = ROOT / "game-server-base"

sys.path.insert(0, str(BASE))
from game_server.plugin import load_plugin  # noqa: E402
from game_server.process_manager import ProcessManager  # noqa: E402
from game_server.config import SupervisorConfig  # noqa: E402
from game_server.world_save import locate_active_world  # noqa: E402


def _load_defaults():
    spec = importlib.util.spec_from_file_location("hytale_haos_defaults", DEFAULTS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HytalePluginTests(unittest.TestCase):
    def test_plugin_is_command_package_install(self) -> None:
        plugin = load_plugin(PLUGIN)
        self.assertEqual(plugin.name, "Hytale")
        self.assertIsNone(plugin.steam_app_id)
        self.assertTrue(plugin.uses_package_install)
        assert plugin.package_install is not None
        self.assertEqual(plugin.package_install.kind, "command")
        self.assertEqual(
            plugin.package_install.version_argv,
            ["python3", "/opt/haos_defaults.py", "print-version"],
        )
        self.assertEqual(
            plugin.package_install.install_argv,
            ["python3", "/opt/haos_defaults.py", "install"],
        )
        self.assertEqual(plugin.install_marker, "Assets.zip")
        self.assertEqual(plugin.executable, ["/opt/launch_wrapper.sh"])
        self.assertEqual(plugin.log_patterns.ready, [])
        self.assertEqual(plugin.log_patterns.player_join, [])
        self.assertEqual(plugin.log_patterns.player_leave, [])
        self.assertIn("ready", plugin.log_pattern_candidates)
        self.assertEqual(plugin.player_tracking_mode, "presence")
        self.assertEqual(plugin.ui_theme.get("accent"), "#8ee04a")
        self.assertEqual(plugin.env.get("HYTALE_DISABLE_UPDATES"), "1")
        self.assertEqual(plugin.env_options, ["JAVA_OPTS"])
        self.assertEqual(plugin.stop_stdin_commands, ["/stop"])
        self.assertIn("--bind", plugin.argv_prefix)
        self.assertIn("0.0.0.0:{server_port}", plugin.argv_prefix)
        self.assertEqual(plugin.arg_map, {})

    def test_cli_binds_all_interfaces_on_container_port(self) -> None:
        plugin = load_plugin(PLUGIN)
        cfg = SupervisorConfig(
            drop_privileges=False,
            status_http_enabled=False,
            backup_enabled=False,
            ha_notifications=False,
            game_options={
                "server_port": "5520",
                "data_dir": "/data/world",
                "logs_dir": "/data/logs",
                "java_opts": "-Xms2G -Xmx4G",
            },
        )
        cmd = ProcessManager(plugin, cfg).build_command()
        self.assertEqual(cmd[0], "/opt/launch_wrapper.sh")
        self.assertIn("--bind", cmd)
        self.assertEqual(cmd[cmd.index("--bind") + 1], "0.0.0.0:5520")
        self.assertNotIn("-Xmx4G", cmd)

    def test_world_save_is_universe_folder(self) -> None:
        plugin = load_plugin(PLUGIN)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "world"
            universe = data_dir / "universe"
            universe.mkdir(parents=True)
            (universe / "players").mkdir()
            (universe / "players" / "one.dat").write_bytes(b"player" * 200)
            active = locate_active_world(
                plugin,
                {"data_dir": str(data_dir)},
                data_dir=str(data_dir),
            )
            self.assertEqual(active.path, str(universe))
            self.assertEqual(active.kind, "directory")
            self.assertEqual(active.label, "universe")

    def test_ha_config_publishes_quic_udp_port(self) -> None:
        import yaml

        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(data["ports"], {"5520/udp": 5520})
        self.assertFalse(data.get("host_network"))
        self.assertEqual(data["timeout"], 300)
        self.assertEqual(data["slug"], "hytale_dedicated_server")
        self.assertEqual(data["arch"], ["amd64"])
        self.assertTrue(str(data["version"]).startswith("3.2."))
        self.assertEqual(data["schema"]["release_channel"], "list(release|pre-release)")
        self.assertEqual(data["schema"]["server_password"], "password")

    def test_launch_wrapper_and_run_sh(self) -> None:
        self.assertTrue(WRAPPER.is_file())
        self.assertTrue(os.access(WRAPPER, os.X_OK), f"{WRAPPER} must be chmod +x")
        self.assertTrue(os.access(RUNSH, os.X_OK), f"{RUNSH} must be chmod +x")
        wrapper = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("haos_defaults.py run", wrapper)
        runsh = RUNSH.read_text(encoding="utf-8")
        self.assertIn("export SERVER_PORT=5520", runsh)
        self.assertIn("print-name", runsh)
        self.assertIn("do not use host_network", runsh.lower())

    def test_docker_env_keys_include_java_and_port(self) -> None:
        plugin = load_plugin(PLUGIN)
        keys = plugin.docker_env_keys()
        self.assertIn("JAVA_OPTS", keys)
        self.assertIn("SERVER_PORT", keys)
        self.assertIn("RELEASE_CHANNEL", keys)


class HytaleHaosDefaultsTests(unittest.TestCase):
    def test_default_server_name_stable_per_install(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = mod.default_server_name(state_dir=state)
            second = mod.default_server_name(state_dir=state)
            self.assertEqual(first, second)
            self.assertRegex(first, r"^HAOS Hytale \d{4}$")
            self.assertTrue((state / "instance_salt").is_file())

    def test_different_installs_get_different_digits(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            name_a = mod.default_server_name(state_dir=a)
            name_b = mod.default_server_name(state_dir=b)
            if name_a == name_b:
                (Path(b) / "instance_salt").unlink()
                name_b = mod.default_server_name(state_dir=b)
            self.assertNotEqual(name_a, name_b)

    def test_resolve_prefers_options_then_env(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            options = root / "options.json"
            options.write_text('{"server_name": "Family Hytale"}', encoding="utf-8")
            self.assertEqual(
                mod.resolve_server_name(
                    options_file=options,
                    state_dir=root / "state",
                    environ={},
                ),
                "Family Hytale",
            )
            self.assertEqual(
                mod.resolve_server_name(
                    options_file=options,
                    state_dir=root / "state",
                    environ={"SERVER_NAME": "From Env"},
                ),
                "From Env",
            )
            options.write_text('{"server_name": ""}', encoding="utf-8")
            generated = mod.resolve_server_name(
                options_file=options,
                state_dir=root / "state",
                environ={},
            )
            self.assertRegex(generated, r"^HAOS Hytale \d{4}$")

    def test_scrape_official_device_login_lines(self) -> None:
        mod = _load_defaults()
        url, code = mod.scrape_device_login("Visit: https://accounts.hytale.com/device")
        self.assertEqual(url, "https://accounts.hytale.com/device")
        self.assertEqual(code, "")
        url, code = mod.scrape_device_login("Enter code: ABCD-1234")
        self.assertEqual(code, "ABCD-1234")
        url, code = mod.scrape_device_login(
            "Or visit: https://accounts.hytale.com/device?user_code=ABCD-1234"
        )
        self.assertEqual(
            url, "https://accounts.hytale.com/device?user_code=ABCD-1234"
        )
        self.assertEqual(code, "ABCD-1234")
        url, code = mod.scrape_device_login("no login here")
        self.assertEqual((url, code), ("", ""))
        url, code = mod.scrape_device_login("javascript:alert(1)")
        self.assertEqual((url, code), ("", ""))

    def test_coalesce_keeps_complete_url_from_official_downloader_block(self) -> None:
        """Official CLI prints verification_uri_complete, then a bare fallback URL.

        Last-URL-wins used to keep the bare page, so Ingress told people to paste
        the device code even after the complete link already carried it. Mixing
        that device code with Hytale's emailed login OTP then fails as invalid.
        """

        mod = _load_defaults()
        lines = [
            "Please visit the following URL to authenticate:",
            "https://oauth.accounts.hytale.com/oauth2/device/verify?user_code=GLrYHNyp",
            "Or visit the following URL and enter the code:",
            "https://oauth.accounts.hytale.com/oauth2/device/verify",
            "Authorization code: GLrYHNyp",
        ]
        url, code = "", ""
        last_url = ""
        for line in lines:
            new_url, new_code = mod.scrape_device_login(line)
            if new_url:
                last_url = new_url
            url, code = mod.coalesce_device_login(url, code, new_url, new_code)
        complete = (
            "https://oauth.accounts.hytale.com/oauth2/device/verify?user_code=GLrYHNyp"
        )
        self.assertEqual(
            last_url,
            "https://oauth.accounts.hytale.com/oauth2/device/verify",
            "naive last-URL-wins still sees the bare fallback last",
        )
        self.assertEqual(url, complete)
        self.assertEqual(code, "GLrYHNyp")
        self.assertTrue(mod._url_has_user_code(url))

    def test_url_with_code_attaches_when_cli_omits_query(self) -> None:
        mod = _load_defaults()
        attached = mod._url_with_code(
            "https://oauth.accounts.hytale.com/oauth2/device/verify",
            "GLrYHNyp",
        )
        self.assertEqual(
            attached,
            "https://oauth.accounts.hytale.com/oauth2/device/verify?user_code=GLrYHNyp",
        )
        already = (
            "https://oauth.accounts.hytale.com/oauth2/device/verify?user_code=GLrYHNyp"
        )
        self.assertEqual(mod._url_with_code(already, "GLrYHNyp"), already)

    def test_signin_detail_separates_device_code_from_email_otp(self) -> None:
        mod = _load_defaults()
        for text in (
            mod.SIGNIN_DETAIL,
            mod.DOWNLOAD_SIGNIN_DETAIL,
            mod.SERVER_SIGNIN_DETAIL,
            mod.TIMEOUT_RETRY_DETAIL,
        ):
            self.assertLessEqual(len(text), 400)
            lowered = text.lower()
            self.assertIn("device", lowered)
            self.assertIn("10 minutes", lowered)
            self.assertNotIn("enter the code", lowered)
        self.assertIn("email", mod.SIGNIN_DETAIL.lower())
        self.assertIn("authorize a device", mod.SIGNIN_DETAIL.lower())

    def test_token_wait_timeout_line_matches_official_downloader(self) -> None:
        mod = _load_defaults()
        line = "2026/08/27 14:16:41 error obtaining token: context deadline exceeded"
        self.assertTrue(mod.token_wait_timed_out_line(line))
        self.assertFalse(mod.token_wait_timed_out_line("Authorization code: GLrYHNyp"))
        self.assertFalse(
            mod.token_wait_timed_out_line("authentication successful! Mode: OAUTH_DEVICE")
        )

    def test_merge_server_config_keeps_unknown_keys(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "ServerName": "old",
                        "CustomModKey": 3,
                        "Defaults": {"World": "oldworld", "Keep": True},
                        "Update": {"Enabled": True, "Channel": "release"},
                    }
                ),
                encoding="utf-8",
            )
            mod.merge_server_config(
                path,
                server_name="HAOS Hytale 0001",
                motd="hi",
                password="secret",
                max_players=12,
                world_name="family",
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["ServerName"], "HAOS Hytale 0001")
            self.assertEqual(data["MOTD"], "hi")
            self.assertEqual(data["Password"], "secret")
            self.assertEqual(data["MaxPlayers"], 12)
            self.assertEqual(data["CustomModKey"], 3)
            self.assertEqual(data["Defaults"]["World"], "family")
            self.assertTrue(data["Defaults"]["Keep"])
            self.assertFalse(data["Update"]["Enabled"])
            self.assertEqual(data["Update"]["Channel"], "release")

    def test_write_and_clear_operator_action(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            mod.write_operator_action(
                title="Sign in required",
                url="https://accounts.hytale.com/device?user_code=WXYZ-9999",
                code="WXYZ-9999",
                detail="Open a new tab",
                steps=[{"label": "Download files", "state": "active"}],
                state_dir=state,
            )
            payload = json.loads((state / "operator_action.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["code"], "WXYZ-9999")
            self.assertEqual(payload["url"].startswith("https://"), True)
            mod.clear_operator_action(state_dir=state)
            self.assertFalse((state / "operator_action.json").exists())

    def test_channel_and_patchline(self) -> None:
        mod = _load_defaults()
        self.assertEqual(mod._channel({"RELEASE_CHANNEL": "pre-release"}), "pre-release")
        self.assertEqual(mod._channel({"RELEASE_CHANNEL": "preview"}), "pre-release")
        self.assertEqual(mod._channel({}), "release")
        self.assertEqual(mod._patchline_args("pre-release"), ["-patchline", "pre-release"])
        self.assertEqual(mod._patchline_args("release"), [])

    def test_extract_zip_strips_single_wrapper_dir(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "game.zip"
            dest = root / "install"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("wrapper/Assets.zip", b"assets")
                zf.writestr("wrapper/Server/HytaleServer.jar", b"jar")
            mod._extract_zip(archive, dest)
            self.assertTrue((dest / "Assets.zip").is_file())
            self.assertTrue((dest / "Server" / "HytaleServer.jar").is_file())

    def test_build_java_command_uses_assets_and_optional_aot(self) -> None:
        mod = _load_defaults()
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "game"
            server = install / "Server"
            server.mkdir(parents=True)
            (server / "HytaleServer.jar").write_bytes(b"jar")
            (install / "Assets.zip").write_bytes(b"assets")
            (server / "HytaleServer.aot").write_bytes(b"aot")
            env_old = os.environ.get("INSTALL_DIR")
            opts_old = os.environ.get("JAVA_OPTS")
            try:
                os.environ["INSTALL_DIR"] = str(install)
                os.environ["JAVA_OPTS"] = "-Xms2G -Xmx4G"
                cmd = mod.build_java_command(["--bind", "0.0.0.0:5520"])
            finally:
                if env_old is None:
                    os.environ.pop("INSTALL_DIR", None)
                else:
                    os.environ["INSTALL_DIR"] = env_old
                if opts_old is None:
                    os.environ.pop("JAVA_OPTS", None)
                else:
                    os.environ["JAVA_OPTS"] = opts_old
            self.assertEqual(cmd[0], "java")
            self.assertIn("-Xms2G", cmd)
            self.assertIn("-Xmx4G", cmd)
            self.assertTrue(any(part.startswith("-XX:AOTCache=") for part in cmd))
            self.assertIn("-jar", cmd)
            self.assertIn("--assets", cmd)
            self.assertEqual(cmd[cmd.index("--bind") + 1], "0.0.0.0:5520")


class HytaleIdentityIsolationTests(unittest.TestCase):
    def test_game_server_base_has_no_hytale_nouns(self) -> None:
        hits: list[str] = []
        for path in BASE.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".png"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "hytale" in text.lower():
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [], f"Hytale leaked into game-server-base: {hits}")


if __name__ == "__main__":
    unittest.main()
