"""Main supervisor loop: install, run, monitor, update, backup, status."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import steamcmd
from .backup import BackupManager
from .config import SupervisorConfig, load_config
from .disk import ensure_free_mb
from .log_bridge import configure_logging
from .log_tools import LogToolbox
from .monitor import LogMonitor
from .notify import Notifier
from .plugin import GamePlugin, load_plugin, resolve_plugin_path
from .privileges import prepare_drop
from .process_manager import ProcessManager
from .status_http import StatusServer
from .steam_gate import configure_gate

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
        self._update_not_before = 0.0
        self._apply_failures = 0
        self._update_lock = threading.Lock()
        self.local_build_id: str | None = None
        self.remote_build_id: str | None = None
        self.last_update_check_at: float | None = None
        self.last_update_applied_at: float | None = None
        self.last_update_error: str | None = None
        self.update_check_count = 0
        self.update_apply_count = 0
        self.steam_gate = configure_gate(config.state_dir)

        data_dir = str(config.game_options.get("data_dir") or plugin.data_dir)
        logs_dir = str(config.game_options.get("logs_dir") or plugin.logs_dir)
        self.plugin.data_dir = data_dir
        self.plugin.logs_dir = logs_dir
        # Persist Steam game files on the data volume by default.
        if not config.install_dir:
            config.install_dir = "/data/game"
        self.plugin.working_dir = str(
            config.game_options.get("working_dir") or config.install_dir
        )

        Path(config.state_dir).mkdir(parents=True, exist_ok=True)
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        Path(logs_dir).mkdir(parents=True, exist_ok=True)
        Path(config.install_dir).mkdir(parents=True, exist_ok=True)
        Path(config.backup_dir).mkdir(parents=True, exist_ok=True)

        self.run_ids = None
        if config.drop_privileges:
            self.run_ids = prepare_drop(
                config.run_as_user,
                [
                    config.install_dir,
                    data_dir,
                    logs_dir,
                    config.backup_dir,
                    config.state_dir,
                    config.steamcmd_dir,
                ],
            )

        self.notifier = Notifier(
            config.state_dir,
            enabled=config.ha_notifications,
            notification_id_prefix=plugin.name.lower().replace(" ", "_"),
        )
        self.monitor = LogMonitor(
            plugin,
            logs_dir,
            on_version_mismatch=self._on_version_mismatch,
        )
        self.log_tools = LogToolbox(
            plugin,
            logs_dir,
            config.state_dir,
            recent_lines_provider=lambda: list(self.monitor.state.recent_lines),
        )
        self.process = ProcessManager(
            plugin,
            config,
            on_line=self.monitor.ingest_stdout_line,
            run_uid=self.run_ids[0] if self.run_ids else None,
            run_gid=self.run_ids[1] if self.run_ids else None,
        )
        backup_sources = list(plugin.backup_paths) or [data_dir]
        self.backups = BackupManager(
            config.backup_dir,
            backup_sources,
            interval_minutes=config.backup_interval_minutes,
            enabled=config.backup_enabled,
            retention=config.retention(),
            min_source_bytes=max(config.backup_min_source_bytes, plugin.min_backup_bytes),
            min_free_disk_mb=config.min_free_disk_mb,
            max_backoff_minutes=config.backup_max_backoff_minutes,
        )
        self.status_server: StatusServer | None = None
        self._update_thread: threading.Thread | None = None
        self._status_thread: threading.Thread | None = None

    def capture_logs(self, reason: str = "manual") -> dict[str, Any]:
        return self.log_tools.capture(reason=reason, status=self.status())

    def status(self) -> dict[str, Any]:
        monitor = self.monitor.state.to_dict()
        monitor["recent_lines"] = list(self.monitor.state.recent_lines)
        pattern_report = self.monitor.pattern_report()
        disk_ok, free = ensure_free_mb(self.config.backup_dir, self.config.min_free_disk_mb)
        player_gating = (
            "active"
            if self.monitor.player_tracking_enabled
            else "inactive_no_active_patterns"
        )
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
            "last_update_error": self.last_update_error,
            "update_check_count": self.update_check_count,
            "update_apply_count": self.update_apply_count,
            "update_apply_failures": self._apply_failures,
            "update_not_before": self._update_not_before or None,
            "install_dir": self.config.install_dir,
            "player_gating": player_gating,
            "steam_gate": self.steam_gate.to_dict(),
            "disk": {
                "ok": disk_ok,
                "free_mb": free,
                "min_free_disk_mb": self.config.min_free_disk_mb,
            },
            "monitor": monitor,
            "log_patterns": pattern_report,
            "process": self.process.to_dict(),
            "backups": self.backups.to_dict(),
            "log_captures": self.log_tools.list_captures(),
        }

    def _publish_status(self) -> None:
        status = self.status()
        self.notifier.write_status(status)

    def _status_loop(self) -> None:
        while not self._stop.wait(15):
            try:
                self._publish_status()
            except Exception:  # noqa: BLE001
                LOG.exception("Failed writing status.json")

    def _on_version_mismatch(self, line: str) -> None:
        # Only invoked for active patterns (dry-run candidates never call this).
        try:
            self.capture_logs("version_mismatch")
        except Exception:  # noqa: BLE001
            LOG.exception("Failed capturing logs on version mismatch")
        self.notifier.notify(
            "version_mismatch",
            f"{self.plugin.name}: client version mismatch",
            f"A client was rejected for a version problem. Scheduling update.\n{line}",
        )
        if not self.config.update_on_version_mismatch:
            return
        LOG.warning("Scheduling update due to version mismatch: %s", line)
        self.request_update(reason="version_mismatch", bypass_window=True)

    def request_update(self, reason: str, bypass_window: bool = False) -> None:
        with self._update_lock:
            self._update_pending = True
            self._update_reason = reason
            self._update_bypass_window = self._update_bypass_window or bypass_window
        LOG.info(
            "Update requested (%s)%s",
            reason,
            " [bypass window]" if bypass_window else "",
        )

    def _within_update_window(self) -> bool:
        start = self.config.update_window_start_hour
        end = self.config.update_window_end_hour
        if start is None or end is None:
            return True
        hour = datetime.now().hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _players_online(self) -> int | None:
        """Return player count when known; None when log tracking cannot tell."""
        if not self.monitor.player_tracking_enabled:
            return None
        state = self.monitor.state
        if not state.players_known and not state.players:
            # Active patterns exist but nothing observed yet — treat as unknown
            # until we see a join/leave/count signal (safer than assuming 0).
            return None
        if state.players:
            return len(state.players)
        if state.player_count is None:
            return None
        return int(state.player_count)

    def _can_apply_update(self) -> bool:
        if time.time() < self._update_not_before:
            return False
        if self.steam_gate.seconds_until_next_call() > 0:
            return False
        if not self._update_bypass_window and not self._within_update_window():
            return False
        if self.config.update_when_empty_only:
            online = self._players_online()
            if online is None:
                # Desirable alpha failure mode: do not block Steam updates forever
                # when player regexes are absent/unproven. Status shows gating inactive.
                LOG.debug(
                    "Player gating unavailable; allowing update without empty check"
                )
            elif online > 0:
                return False
        ok, _free = ensure_free_mb(self.config.install_dir, self.config.min_free_disk_mb)
        return ok

    def ensure_installed(self) -> None:
        steamcmd.ensure_steamcmd(self.config.steamcmd_dir)
        # Re-apply ownership after SteamCMD bootstrap files appear.
        if self.config.drop_privileges:
            prepare_drop(
                self.config.run_as_user,
                [self.config.steamcmd_dir, self.config.install_dir],
            )
        installed = steamcmd.server_installed(
            self.config.install_dir, self.plugin.install_marker
        ) or steamcmd.server_installed(self.config.install_dir)
        if not installed or self.config.update_on_start:
            LOG.info("Installing/updating game server via SteamCMD into %s", self.config.install_dir)
            try:
                self.local_build_id = steamcmd.install_or_update(
                    self.config.steamcmd_dir,
                    self.config.install_dir,
                    self.plugin,
                    retries=self.config.steamcmd_retries,
                    retry_delay_seconds=self.config.steamcmd_retry_delay_seconds,
                    stop_event=self._stop,
                )
                self.last_update_applied_at = time.time()
                self.update_apply_count += 1
                self.last_update_error = None
                self._apply_failures = 0
            except Exception as exc:  # noqa: BLE001
                self.last_update_error = str(exc)
                self.notifier.notify(
                    "steamcmd_failed",
                    f"{self.plugin.name}: SteamCMD failed",
                    str(exc),
                    force=True,
                )
                raise
            if self.config.drop_privileges:
                prepare_drop(
                    self.config.run_as_user,
                    [self.config.install_dir, self.config.steamcmd_dir],
                )
        else:
            self.local_build_id = steamcmd.read_local_build_id(
                self.config.install_dir, self.plugin.steam_app_id
            )

    def _schedule_update_retry(self, exc: Exception) -> None:
        self._apply_failures += 1
        delay = self.steam_gate.apply_failure_delay_seconds(self._apply_failures)
        delay = max(delay, self.steam_gate.cooldown_remaining())
        self._update_not_before = time.time() + delay
        self.last_update_error = str(exc)
        LOG.warning(
            "Update apply failure #%s; next attempt not before %.0fs (error=%s)",
            self._apply_failures,
            delay,
            exc,
        )
        if self._apply_failures >= self.steam_gate.policy.max_apply_failures:
            self.notifier.notify(
                "update_failed",
                f"{self.plugin.name}: update paused (Steam backoff)",
                (
                    f"Failed {self._apply_failures} times. Cooling down "
                    f"{int(delay)}s before trying Steam again.\n{exc}"
                ),
                force=True,
            )

    def _apply_update(self) -> None:
        reason = self._update_reason or "requested"
        LOG.info("Applying update (%s)", reason)
        if self.config.backup_on_update:
            try:
                # Graceful stop first so the world flush happens before backup.
                if self.process.running:
                    self.process.stop()
                self.backups.create_backup(reason="pre-update")
            except Exception:  # noqa: BLE001
                LOG.exception("Pre-update backup failed; continuing with update")

        if self.process.running:
            self.process.stop()

        try:
            self.local_build_id = steamcmd.install_or_update(
                self.config.steamcmd_dir,
                self.config.install_dir,
                self.plugin,
                retries=self.config.steamcmd_retries,
                retry_delay_seconds=self.config.steamcmd_retry_delay_seconds,
                stop_event=self._stop,
            )
            if self.config.drop_privileges:
                prepare_drop(
                    self.config.run_as_user,
                    [self.config.install_dir, self.config.steamcmd_dir],
                )
            self.last_update_applied_at = time.time()
            self.update_apply_count += 1
            self.last_update_error = None
            self._apply_failures = 0
            self._update_not_before = 0.0
        except Exception as exc:  # noqa: BLE001
            self.capture_logs("update_failed")
            self._schedule_update_retry(exc)
            # Restart existing install so the kids can keep playing on current build.
            if not self.process.running and not self._stop.is_set():
                try:
                    self.monitor.reset_session()
                    self.process.start()
                except Exception:  # noqa: BLE001
                    LOG.exception("Failed restarting server after update failure")
            raise

        with self._update_lock:
            self._update_pending = False
            self._update_reason = None
            self._update_bypass_window = False
        self.monitor.reset_session()
        self.process.start()
        self.notifier.notify(
            "updated",
            f"{self.plugin.name}: updated",
            f"Now running build {self.local_build_id or 'unknown'} (reason: {reason})",
            force=True,
        )

    def _update_checker_loop(self) -> None:
        minutes = self.steam_gate.clamp_check_interval_minutes(
            self.config.auto_update_interval_minutes
        )
        interval = max(0, minutes) * 60
        if interval <= 0:
            LOG.info("Periodic Steam update checks disabled")
            return
        LOG.info(
            "Checking Steam for updates every %s minutes "
            "(Steam gate min interval %.0fs, max retries %s)",
            interval // 60,
            self.steam_gate.policy.min_interval_seconds,
            self.steam_gate.policy.max_retries,
        )
        while not self._stop.wait(interval):
            wait_for = self.steam_gate.seconds_until_next_call()
            if wait_for > 0:
                LOG.info(
                    "Skipping Steam update check; gate requires %.0fs more cooldown",
                    wait_for,
                )
                continue
            try:
                self.update_check_count += 1
                self.last_update_check_at = time.time()
                available, local, remote = steamcmd.update_available(
                    self.config.steamcmd_dir,
                    self.config.install_dir,
                    self.plugin,
                    stop_event=self._stop,
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
            except Exception as exc:  # noqa: BLE001
                self.last_update_error = str(exc)
                LOG.exception("Update check failed")
                self.notifier.notify(
                    "update_check_failed",
                    f"{self.plugin.name}: update check failed",
                    str(exc),
                )

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
                log_toolbox=self.log_tools,
                capture_callback=self.capture_logs,
            )
            self.status_server.start()

        self._status_thread = threading.Thread(
            target=self._status_loop, name="status-writer", daemon=True
        )
        self._status_thread.start()

        self.ensure_installed()
        self.monitor.start()
        self.backups.start()
        self.process.start()
        self._publish_status()

        self._update_thread = threading.Thread(
            target=self._update_checker_loop, name="update-checker", daemon=True
        )
        self._update_thread.start()

        while not self._stop.is_set():
            if self._update_pending and self._can_apply_update():
                try:
                    self._apply_update()
                except Exception:  # noqa: BLE001
                    LOG.exception("Failed to apply update; backing off")
                    # Backoff is scheduled inside _schedule_update_retry; never
                    # tight-loop SteamCMD on a 30s timer again.

            code = self.process.wait(timeout=2)
            if code is None:
                continue
            if self._stop.is_set():
                break
            if self._update_pending:
                continue
            if self.process.intentional_stop:
                break
            try:
                self.capture_logs("crash")
            except Exception:  # noqa: BLE001
                LOG.exception("Failed capturing logs after crash")
            self.notifier.notify(
                "crash",
                f"{self.plugin.name}: server crashed",
                f"Exit code {code}. Restarts this hour: {self.process.crashes_in_last_hour()}",
                force=True,
            )
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
                self.notifier.notify(
                    "crash_loop",
                    f"{self.plugin.name}: crash loop",
                    "Restart limit reached; supervisor is leaving the server stopped.",
                    force=True,
                )
                break

        self.monitor.stop()
        self.backups.stop()
        if self.status_server:
            self.status_server.stop()
        self.process.stop()
        self._publish_status()
        return self.process.last_exit_code or 0


def main(argv: list[str] | None = None) -> int:
    import argparse

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

    level_name = (
        args.log_level or __import__("os").environ.get("LOG_LEVEL") or "INFO"
    ).upper()
    configure_logging(getattr(logging, level_name, logging.INFO))

    plugin_path = resolve_plugin_path(args.plugin)
    LOG.info("Loading game plugin from %s", plugin_path)
    plugin = load_plugin(plugin_path)
    config = load_config()
    if not config.install_dir:
        config.install_dir = "/data/game"

    LOG.info(
        "Home Assistant Logs tab = this container's stdout: supervisor events, "
        "[game] process output, [game-log] file-only lines, [steamcmd] updates"
    )
    LOG.info(
        "Starting supervisor for %s (appid=%s, install_dir=%s)",
        plugin.name,
        plugin.steam_app_id,
        config.install_dir,
    )
    supervisor = GameServerSupervisor(plugin, config)
    return supervisor.run()
