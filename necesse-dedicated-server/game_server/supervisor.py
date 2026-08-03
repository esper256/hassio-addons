"""Main supervisor loop: install, run, monitor, update, backup, status."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .backup import BackupManager
from .config import SupervisorConfig, load_config
from .monitor import LogMonitor
from .plugin import GamePlugin, load_plugin, resolve_plugin_path
from .process_manager import ProcessManager
from .status_http import StatusServer
from . import steamcmd

LOG = logging.getLogger("game_server.supervisor")


class GameServerSupervisor:
    def __init__(
        self,
        plugin: GamePlugin,
        config: SupervisorConfig,
    ) -> None:
        self.plugin = plugin
        self.config = config
        self.started_at = time.time()
        self._stop = threading.Event()
        self._update_pending = False
        self._update_reason: str | None = None
        self._update_bypass_window = False
        self._update_lock = threading.Lock()
        self.local_build_id: str | None = None
        self.remote_build_id: str | None = None
        self.last_update_check_at: float | None = None
        self.last_update_applied_at: float | None = None
        self.update_check_count = 0
        self.update_apply_count = 0

        # Allow options to override plugin paths
        data_dir = str(config.game_options.get("data_dir") or plugin.data_dir)
        logs_dir = str(config.game_options.get("logs_dir") or plugin.logs_dir)
        self.plugin.data_dir = data_dir
        self.plugin.logs_dir = logs_dir
        if "working_dir" not in config.game_options:
            config.install_dir = config.install_dir or plugin.working_dir

        self.monitor = LogMonitor(
            plugin,
            logs_dir,
            on_version_mismatch=self._on_version_mismatch,
        )
        self.process = ProcessManager(
            plugin,
            config,
            on_line=self.monitor.ingest_stdout_line,
        )
        backup_sources = list(plugin.backup_paths) or [data_dir]
        self.backups = BackupManager(
            config.backup_dir,
            backup_sources,
            retain=config.backup_retain,
            interval_minutes=config.backup_interval_minutes,
            enabled=config.backup_enabled,
        )
        self.status_server: StatusServer | None = None
        self._update_thread: threading.Thread | None = None

        Path(config.state_dir).mkdir(parents=True, exist_ok=True)
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        Path(logs_dir).mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        monitor = self.monitor.state.to_dict()
        monitor["recent_lines"] = list(self.monitor.state.recent_lines)
        return {
            "game": self.plugin.name,
            "steam_app_id": self.plugin.steam_app_id,
            "running": self.process.running,
            "starting": not self.process.running and not self._stop.is_set(),
            "supervisor_uptime_seconds": int(time.time() - self.started_at),
            "restart_count": self.process.restart_count,
            "crash_count": self.process.crash_count,
            "local_build_id": self.local_build_id,
            "remote_build_id": self.remote_build_id,
            "update_pending": self._update_pending,
            "update_reason": self._update_reason,
            "last_update_check_at": self.last_update_check_at,
            "last_update_applied_at": self.last_update_applied_at,
            "update_check_count": self.update_check_count,
            "update_apply_count": self.update_apply_count,
            "monitor": monitor,
            "process": self.process.to_dict(),
            "backups": self.backups.to_dict(),
        }

    def _on_version_mismatch(self, line: str) -> None:
        if not self.config.update_on_version_mismatch:
            return
        LOG.warning("Scheduling update due to version mismatch: %s", line)
        # Bypass quiet hours — kids cannot play until the server catches up.
        self.request_update(reason="version_mismatch", bypass_window=True)

    def request_update(self, reason: str, bypass_window: bool = False) -> None:
        with self._update_lock:
            self._update_pending = True
            self._update_reason = reason
            self._update_bypass_window = self._update_bypass_window or bypass_window
        LOG.info("Update requested (%s)%s", reason, " [bypass window]" if bypass_window else "")

    def _within_update_window(self) -> bool:
        start = self.config.update_window_start_hour
        end = self.config.update_window_end_hour
        if start is None or end is None:
            return True
        hour = datetime.now().hour
        if start <= end:
            return start <= hour < end
        # Window wraps midnight, e.g. 22 -> 6
        return hour >= start or hour < end

    def _players_online(self) -> int:
        state = self.monitor.state
        if state.players:
            return len(state.players)
        return state.player_count

    def _can_apply_update(self) -> bool:
        if not self._update_bypass_window and not self._within_update_window():
            return False
        if self.config.update_when_empty_only and self._players_online() > 0:
            # Version mismatch usually means nobody can stay connected; still
            # avoid kicking any session that did manage to join.
            return False
        return True

    def ensure_installed(self) -> None:
        steamcmd.ensure_steamcmd(self.config.steamcmd_dir)
        installed = steamcmd.server_installed(
            self.config.install_dir, "Server.jar"
        ) or steamcmd.server_installed(self.config.install_dir)
        if not installed or self.config.update_on_start:
            LOG.info("Installing/updating game server via SteamCMD")
            self.local_build_id = steamcmd.install_or_update(
                self.config.steamcmd_dir,
                self.config.install_dir,
                self.plugin,
                retries=self.config.steamcmd_retries,
                retry_delay_seconds=self.config.steamcmd_retry_delay_seconds,
            )
            self.last_update_applied_at = time.time()
            self.update_apply_count += 1
        else:
            self.local_build_id = steamcmd.read_local_build_id(
                self.config.install_dir, self.plugin.steam_app_id
            )

    def _apply_update(self) -> None:
        reason = self._update_reason or "requested"
        LOG.info("Applying update (%s)", reason)
        if self.config.backup_on_update:
            try:
                self.backups.create_backup(reason="pre-update")
            except Exception:  # noqa: BLE001
                LOG.exception("Pre-update backup failed; continuing with update")

        self.process.stop()
        self.local_build_id = steamcmd.install_or_update(
            self.config.steamcmd_dir,
            self.config.install_dir,
            self.plugin,
            retries=self.config.steamcmd_retries,
            retry_delay_seconds=self.config.steamcmd_retry_delay_seconds,
        )
        self.last_update_applied_at = time.time()
        self.update_apply_count += 1
        with self._update_lock:
            self._update_pending = False
            self._update_reason = None
            self._update_bypass_window = False
        self.monitor.reset_session()
        self.process.start()

    def _update_checker_loop(self) -> None:
        interval = max(0, self.config.auto_update_interval_minutes) * 60
        if interval <= 0:
            LOG.info("Periodic Steam update checks disabled")
            return
        LOG.info("Checking Steam for updates every %s minutes", interval // 60)
        while not self._stop.wait(interval):
            try:
                self.update_check_count += 1
                self.last_update_check_at = time.time()
                available, local, remote = steamcmd.update_available(
                    self.config.steamcmd_dir,
                    self.config.install_dir,
                    self.plugin,
                )
                self.local_build_id = local or self.local_build_id
                self.remote_build_id = remote
                if available:
                    LOG.info(
                        "Remote update available (local=%s remote=%s)",
                        local,
                        remote,
                    )
                    self.request_update(reason="steam_build", bypass_window=False)
                else:
                    LOG.info(
                        "Game is up to date (buildid=%s)", local or remote or "unknown"
                    )
            except Exception:  # noqa: BLE001
                LOG.exception("Update check failed")

    def run(self) -> int:
        def _signal_handler(signum: int, _frame: Any) -> None:
            LOG.info("Received signal %s; shutting down", signum)
            self._stop.set()
            self.process.stop()

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        if self.config.status_http_enabled:
            self.status_server = StatusServer(
                self.config.status_http_host,
                self.config.status_http_port,
                self.status,
                game_name=self.plugin.name,
            )
            self.status_server.start()

        self.ensure_installed()
        self.monitor.start()
        self.backups.start()
        self.process.start()

        self._update_thread = threading.Thread(
            target=self._update_checker_loop, name="update-checker", daemon=True
        )
        self._update_thread.start()

        while not self._stop.is_set():
            # Apply pending updates when safe
            if self._update_pending and self._can_apply_update():
                try:
                    self._apply_update()
                except Exception:  # noqa: BLE001
                    LOG.exception("Failed to apply update")
                    with self._update_lock:
                        # Keep pending so we retry later
                        pass
                    time.sleep(30)

            code = self.process.wait(timeout=2)
            if code is None:
                continue
            if self._stop.is_set():
                break
            if self._update_pending:
                # Process was stopped for update; loop will apply
                continue
            if self.process.intentional_stop:
                break
            # Crash restart
            if self.process.can_restart_after_crash():
                delay = self.config.crash_restart_delay_seconds
                LOG.warning("Restarting after crash in %ss", delay)
                time.sleep(delay)
                if self._stop.is_set():
                    break
                self.monitor.reset_session()
                self.process.start()
            else:
                LOG.error("Not restarting after crash (limit reached or disabled)")
                break

        self.monitor.stop()
        self.backups.stop()
        if self.status_server:
            self.status_server.stop()
        self.process.stop()
        return self.process.last_exit_code or 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generic Steam game server supervisor")
    parser.add_argument(
        "--plugin",
        default=None,
        help="Path to game plugin YAML/JSON (or set GAME_PLUGIN)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Logging level (default INFO, or LOG_LEVEL env)",
    )
    args = parser.parse_args(argv)

    level_name = (args.log_level or __import__("os").environ.get("LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    plugin_path = resolve_plugin_path(args.plugin)
    LOG.info("Loading game plugin from %s", plugin_path)
    plugin = load_plugin(plugin_path)
    config = load_config()

    # Keep install/working dirs consistent
    if not config.install_dir:
        config.install_dir = plugin.working_dir

    LOG.info(
        "Starting supervisor for %s (appid=%s)",
        plugin.name,
        plugin.steam_app_id,
    )
    supervisor = GameServerSupervisor(plugin, config)
    return supervisor.run()
