"""Main supervisor loop: install, run, monitor, update, backup, status."""

from __future__ import annotations

import logging
import signal
import tarfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import steamcmd
from .backup import BackupManager, EMPTY_WORLD
from .config import SupervisorConfig, load_config
from .disk import ensure_free_mb
from .log_bridge import configure_logging
from .log_tools import LogToolbox
from .monitor import LogMonitor
from .notify import Notifier
from .plugin import GamePlugin, load_plugin, resolve_plugin_path
from .privileges import prepare_owned_paths
from .process_manager import ProcessManager
from .status_http import StatusServer
from .steam_gate import configure_gate
from .steamcmd import SteamCMDError
from .version import app_version
from .world_save import backup_sources_for, locate_active_world

LOG = logging.getLogger("game_server.supervisor")

# Explicit supervisor/game phases for status + HA watchdog (/healthz).
# Prefer this over the old boolean "starting" (= anything not stopped).
LIFECYCLE_HEALTHY = frozenset(
    {"running", "installing", "updating", "restoring", "starting", "waiting"}
)


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
        # Manual UI force: apply even when players are online.
        self._update_ignore_players = False
        self._update_not_before = 0.0
        self._apply_failures = 0
        self._update_lock = threading.Lock()
        self._restore_pending: str | None = None
        self._restore_lock = threading.Lock()
        self.last_restore_error: str | None = None
        self.last_restore_at: float | None = None
        # Short-lived activity while a long operation holds the main loop.
        self._activity: str | None = None
        self.local_build_id: str | None = None
        self.remote_build_id: str | None = None
        self.last_update_check_at: float | None = None
        self.last_update_applied_at: float | None = None
        self.last_update_error: str | None = None
        self.update_check_count = 0
        self.update_apply_count = 0
        self.steam_gate = configure_gate(config.state_dir)
        steamcmd.configure_steamcmd_version_path(
            Path(config.state_dir) / "steamcmd_version.txt"
        )

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
            self.run_ids = prepare_owned_paths(
                config.run_as_user,
                [
                    config.install_dir,
                    data_dir,
                    logs_dir,
                    config.backup_dir,
                    config.state_dir,
                    config.steamcmd_dir,
                    steamcmd.steam_home_dir(),
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
        # Backups archive explicit plugin roots (usually the whole data dir).
        # Active-world size for the UI is resolved separately via world_save.
        backup_sources = backup_sources_for(plugin, data_dir)
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
        self.backups.set_failure_callback(self._on_backup_failure)
        self.status_server: StatusServer | None = None
        self._update_thread: threading.Thread | None = None
        self._status_thread: threading.Thread | None = None

    def capture_logs(self, reason: str = "manual") -> dict[str, Any]:
        return self.log_tools.capture(reason=reason, status=self.status())

    def _on_backup_failure(self, reason: str) -> None:
        self.notifier.notify(
            "backup_failed",
            f"{self.plugin.name}: backup failed",
            (
                f"{reason}\n"
                f"Consecutive failures: {self.backups.consecutive_failures}. "
                "The next attempt backs off automatically."
            ),
        )

    def request_restore(self, archive_name: str) -> dict[str, Any]:
        """Schedule a world restore or empty-world reset from Ingress."""

        empty = str(archive_name or "").strip() == EMPTY_WORLD
        archive_path: Path | None = None
        if not empty:
            archive_path = self.backups.resolve_archive(archive_name)
            if archive_path is None:
                return {
                    "ok": False,
                    "error": f"Backup not found or invalid name: {archive_name}",
                }
        with self._restore_lock:
            if self._restore_pending:
                return {
                    "ok": False,
                    "error": f"A restore is already pending ({self._restore_pending})",
                }
            if self._update_pending:
                return {
                    "ok": False,
                    "error": "An update is already pending; wait for it to finish",
                }
            self._restore_pending = EMPTY_WORLD if empty else archive_path.name
        if empty:
            LOG.warning("Empty-world reset scheduled (wipe live world)")
            return {
                "ok": True,
                "message": (
                    "Empty-world reset scheduled. The server will stop, save the "
                    "current world as a pre-restore safety copy when there is data "
                    "to keep, clear the world files, and restart so the game can "
                    "create a fresh world."
                ),
                "archive": None,
                "empty": True,
                "restore_pending": True,
            }
        assert archive_path is not None
        LOG.warning("World restore scheduled from archive %s", archive_path.name)
        return {
            "ok": True,
            "message": (
                f"Restore of {archive_path.name} scheduled. The server will stop, "
                "save the current world as a pre-restore safety copy (kept outside "
                "normal backup rotation), replace the world from the archive, "
                "and restart."
            ),
            "archive": archive_path.name,
            "empty": False,
            "restore_pending": True,
        }

    def _create_pre_restore_safety(self) -> Path | None:
        """Safety-copy the live world when there is data worth keeping."""

        valid, reason = self.backups.validate_sources()
        if not valid:
            LOG.info("Skipping pre-restore safety copy: %s", reason)
            return None
        safety = self.backups.create_backup(reason="safety", outside_rotation=True)
        if safety is None:
            raise RuntimeError(
                self.backups.last_error
                or self.backups.last_skip_reason
                or "could not create pre-restore safety backup"
            )
        LOG.info("Pre-restore safety copy saved as %s", safety.name)
        return safety

    def _apply_restore(self, archive_name: str) -> None:
        empty = archive_name == EMPTY_WORLD
        archive = None if empty else self.backups.resolve_archive(archive_name)
        if not empty and archive is None:
            raise FileNotFoundError(f"backup archive not found: {archive_name}")

        if empty:
            LOG.info("Applying empty-world reset (clear live world files)")
        else:
            assert archive is not None
            LOG.info("Applying world restore from %s", archive.name)
        self._activity = "restoring"
        try:
            if self.process.running:
                self.process.stop()

            try:
                safety = self._create_pre_restore_safety()
                if empty:
                    result = self.backups.clear_world_sources()
                else:
                    assert archive is not None
                    result = self.backups.restore_archive(archive)
                self.last_restore_at = time.time()
                self.last_restore_error = None
            except Exception as exc:
                self.last_restore_error = str(exc)
                LOG.exception("World restore failed")
                self.notifier.notify(
                    "restore_failed",
                    f"{self.plugin.name}: world restore failed",
                    str(exc),
                    force=True,
                )
                if not self.process.running and not self._stop.is_set():
                    try:
                        self.monitor.reset_session()
                        self.process.start(reason="restore_failed")
                    except OSError:
                        LOG.exception("Failed restarting server after restore failure")
                raise

            self.monitor.reset_session()
            self.process.start(reason="restore")
            if empty:
                safety_note = (
                    f"Previous world kept as {safety.name}."
                    if safety is not None
                    else "No prior world data to keep."
                )
                self.notifier.notify(
                    "restored",
                    f"{self.plugin.name}: empty world reset",
                    f"Live world cleared for a fresh start. {safety_note}",
                    force=True,
                )
            else:
                assert archive is not None
                safety_note = (
                    f"Previous world kept as {safety.name} outside normal rotation."
                    if safety is not None
                    else "No prior world data to keep."
                )
                self.notifier.notify(
                    "restored",
                    f"{self.plugin.name}: world restored",
                    f"Restored {archive.name}. {safety_note}",
                    force=True,
                )
            LOG.info("World restore complete: %s", result)
        finally:
            self._activity = None

    def lifecycle(self) -> str:
        """Return a single phase a person can reason about.

        Values: stopping, stopped, restoring, installing, updating, running,
        waiting (update queued), failed (crash loop / left down), starting.
        """

        if self._stop.is_set():
            return "stopping" if self.process.running else "stopped"
        if self._activity in ("installing", "updating", "restoring"):
            return self._activity
        if self._restore_pending:
            return "restoring"
        if self.process.running:
            return "running"
        if self._update_pending:
            return "waiting"
        if (
            self.process.start_count > 0
            and not self.process.intentional_stop
            and not self.process.can_restart_after_crash()
        ):
            return "failed"
        if self.process.intentional_stop and self.process.start_count > 0:
            return "stopped"
        return "starting"

    def health(self) -> dict[str, Any]:
        """Cheap snapshot for /healthz (no disk/manifest scans)."""

        phase = self.lifecycle()
        return {
            "lifecycle": phase,
            "running": self.process.running,
            "ok": phase in LIFECYCLE_HEALTHY,
        }

    def status(self) -> dict[str, Any]:
        monitor = self.monitor.state.to_dict()
        monitor["recent_lines"] = list(self.monitor.state.recent_lines)
        pattern_report = self.monitor.pattern_report()
        disk_ok, free = ensure_free_mb(self.config.backup_dir, self.config.min_free_disk_mb)
        waits_for_empty_server = (
            "yes"
            if self.monitor.player_tracking_enabled
            else "no_player_tracking"
        )
        install_meta = steamcmd.read_local_install_meta(
            self.config.install_dir, self.plugin.steam_app_id
        )
        # Prefer on-disk build id for display; do not mutate self on a status read.
        local_build = install_meta.get("build_id") or self.local_build_id
        world_size = locate_active_world(
            self.plugin,
            self.config.game_options,
            data_dir=self.plugin.data_dir,
        ).to_dict()
        phase = self.lifecycle()
        return {
            "game": self.plugin.name,
            "app_version": app_version(),
            "steam_app_id": self.plugin.steam_app_id,
            "running": self.process.running,
            "lifecycle": phase,
            # Narrower than the old "not stopped" meaning; prefer ``lifecycle``.
            "starting": phase == "starting",
            "supervisor_uptime_seconds": int(time.time() - self.started_at),
            "game_uptime_seconds": (
                int(time.time() - self.process.last_started_at)
                if self.process.running and self.process.last_started_at
                else 0
            ),
            "restart_count": self.process.restart_count,
            "last_start_reason": self.process.last_start_reason,
            "crash_count": self.process.crash_count,
            "local_build_id": str(local_build) if local_build else None,
            "steamcmd_version": steamcmd.steamcmd_client_version(),
            "game_version": self.monitor.state.game_version,
            "remote_build_id": self.remote_build_id,
            "install_last_updated_at": install_meta.get("last_updated"),
            "world_save": world_size,
            "update_pending": self._update_pending,
            "update_reason": self._update_reason,
            "last_update_check_at": self.last_update_check_at,
            "last_update_applied_at": self.last_update_applied_at,
            "last_update_error": self.last_update_error,
            "update_check_count": self.update_check_count,
            "update_apply_count": self.update_apply_count,
            "update_apply_failures": self._apply_failures,
            "update_not_before": self._update_not_before or None,
            "auto_update_interval_minutes": self.config.auto_update_interval_minutes,
            "auto_update_check_hour": self.config.auto_update_check_hour,
            "install_dir": self.config.install_dir,
            "restore_pending": self._restore_pending,
            "last_restore_at": self.last_restore_at,
            "last_restore_error": self.last_restore_error,
            # Plain-language status for the UI (avoid "gating" jargon).
            "waits_for_empty_server": waits_for_empty_server,
            # Same values as waits_for_empty_server (legacy field name).
            "player_gating": waits_for_empty_server,
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
            except OSError:
                LOG.exception("Failed writing status.json")
            # Other exceptions are supervisor bugs — let the status thread die
            # so the failure is obvious in logs rather than hidden every 15s.

    def _on_version_mismatch(self, line: str) -> None:
        # Only invoked for active patterns (dry-run candidates never call this).
        try:
            self.capture_logs("version_mismatch")
        except OSError:
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

    def request_update(
        self,
        reason: str,
        bypass_window: bool = False,
        *,
        ignore_players: bool = False,
    ) -> None:
        with self._update_lock:
            self._update_pending = True
            self._update_reason = reason
            self._update_bypass_window = self._update_bypass_window or bypass_window
            self._update_ignore_players = (
                self._update_ignore_players or ignore_players
            )
        LOG.info(
            "Update requested (%s)%s%s",
            reason,
            " [bypass window]" if bypass_window else "",
            " [may interrupt players]" if ignore_players else "",
        )

    def force_update_now(self) -> dict[str, Any]:
        """Schedule a Steam update from the web UI, even if players are online.

        Respects a long Steam cooldown (rate-limit style) so a button mash cannot
        hammer Valve. Short spacing between SteamCMD calls still applies when the
        main loop runs the update.
        """

        cooldown = self.steam_gate.cooldown_remaining()
        if cooldown >= 600:
            return {
                "ok": False,
                "error": (
                    f"Steam is cooling down for about {int(cooldown)}s after a "
                    "recent failure or rate limit. Try again later."
                ),
                "cooldown_seconds": int(cooldown),
            }
        # Clear soft "try later" from a previous apply failure; the Steam gate
        # still enforces spacing / hard cooldowns.
        self._update_not_before = 0.0
        self.request_update(
            reason="manual",
            bypass_window=True,
            ignore_players=True,
        )
        online = self._players_online()
        return {
            "ok": True,
            "message": (
                "Update scheduled. The game server will stop, update from Steam, "
                "and restart. Anyone playing will be disconnected."
            ),
            "update_pending": True,
            "players_online": online,
        }

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
        if self.config.update_when_empty_only and not self._update_ignore_players:
            online = self._players_online()
            if online is None:
                # Do not block Steam updates forever when player tracking is not
                # available yet. Status explains that restarts may interrupt players.
                LOG.debug(
                    "Player tracking unavailable; allowing update without empty check"
                )
            elif online > 0:
                return False
        ok, _free = ensure_free_mb(self.config.install_dir, self.config.min_free_disk_mb)
        return ok

    def _steamcmd_identity(self) -> tuple[int | None, int | None]:
        """UID/GID SteamCMD should run as (same owner as /data/game)."""

        if self.run_ids:
            return self.run_ids[0], self.run_ids[1]
        return None, None

    def ensure_installed(self) -> None:
        steamcmd.ensure_steamcmd(self.config.steamcmd_dir)
        # Re-apply ownership after SteamCMD bootstrap files appear.
        if self.config.drop_privileges:
            self.run_ids = prepare_owned_paths(
                self.config.run_as_user,
                [
                    self.config.steamcmd_dir,
                    self.config.install_dir,
                    steamcmd.steam_home_dir(),
                ],
            ) or self.run_ids
        had_install = steamcmd.server_installed(
            self.config.install_dir, self.plugin.install_marker
        )
        if not had_install or self.config.update_on_start:
            LOG.info(
                "Installing/updating game server via SteamCMD into %s",
                self.config.install_dir,
            )
            self._activity = "installing"
            run_uid, run_gid = self._steamcmd_identity()
            try:
                self.local_build_id = steamcmd.install_or_update(
                    self.config.steamcmd_dir,
                    self.config.install_dir,
                    self.plugin,
                    retries=self.config.steamcmd_retries,
                    retry_delay_seconds=self.config.steamcmd_retry_delay_seconds,
                    stop_event=self._stop,
                    run_uid=run_uid,
                    run_gid=run_gid,
                )
                self.last_update_applied_at = time.time()
                self.last_update_check_at = self.last_update_applied_at
                self.update_apply_count += 1
                self.last_update_error = None
                self._apply_failures = 0
            except SteamCMDError as exc:
                self.last_update_error = str(exc)
                self.last_update_check_at = time.time()
                self.notifier.notify(
                    "steamcmd_failed",
                    f"{self.plugin.name}: SteamCMD failed",
                    str(exc),
                    force=True,
                )
                if had_install:
                    # Steam/backend problem on restart: keep serving the existing
                    # build instead of refusing to start the whole app.
                    self.local_build_id = steamcmd.read_local_build_id(
                        self.config.install_dir, self.plugin.steam_app_id
                    )
                    LOG.error(
                        "SteamCMD update-on-start failed; continuing with existing "
                        "install (buildid=%s): %s",
                        self.local_build_id or "unknown",
                        exc,
                    )
                else:
                    raise
            finally:
                self._activity = None
            if self.config.drop_privileges:
                prepare_owned_paths(
                    self.config.run_as_user,
                    [
                        self.config.install_dir,
                        self.config.steamcmd_dir,
                        steamcmd.steam_home_dir(),
                    ],
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

    def _restart_existing_after_update_failure(self) -> None:
        """Bring the current install back up after a failed update attempt."""

        if self.process.running or self._stop.is_set():
            return
        try:
            self.monitor.reset_session()
            self.process.start(reason="update_failed")
        except OSError:
            LOG.exception("Failed restarting server after update failure")

    def _apply_update(self) -> None:
        reason = self._update_reason or "requested"
        LOG.info("Applying update (%s)", reason)
        self._activity = "updating"
        try:
            if self.config.backup_on_update:
                # Graceful stop first so the world flush happens before backup.
                if self.process.running:
                    self.process.stop()
                try:
                    self.backups.create_backup(reason="pre-update")
                except (OSError, tarfile.TarError) as exc:
                    # Do not mutate the install when we could not snapshot the world.
                    LOG.exception("Pre-update backup failed; aborting update")
                    self.notifier.notify(
                        "backup_failed",
                        f"{self.plugin.name}: pre-update backup failed",
                        f"Update aborted until a world backup succeeds.\n{exc}",
                        force=True,
                    )
                    self._schedule_update_retry(exc)
                    self._restart_existing_after_update_failure()
                    raise

            if self.process.running:
                self.process.stop()

            run_uid, run_gid = self._steamcmd_identity()
            try:
                self.local_build_id = steamcmd.install_or_update(
                    self.config.steamcmd_dir,
                    self.config.install_dir,
                    self.plugin,
                    retries=self.config.steamcmd_retries,
                    retry_delay_seconds=self.config.steamcmd_retry_delay_seconds,
                    stop_event=self._stop,
                    run_uid=run_uid,
                    run_gid=run_gid,
                )
                if self.config.drop_privileges:
                    self.run_ids = prepare_owned_paths(
                        self.config.run_as_user,
                        [
                            self.config.install_dir,
                            self.config.steamcmd_dir,
                            steamcmd.steam_home_dir(),
                        ],
                    ) or self.run_ids
                self.last_update_applied_at = time.time()
                self.update_apply_count += 1
                self.last_update_error = None
                self._apply_failures = 0
                self._update_not_before = 0.0
            except SteamCMDError as exc:
                try:
                    self.capture_logs("update_failed")
                except OSError:
                    LOG.exception("Failed capturing logs after update failure")
                self._schedule_update_retry(exc)
                self._restart_existing_after_update_failure()
                raise
            except Exception as exc:
                # Unexpected supervisor bug after stopping the game: still try to
                # recover the server, schedule backoff so we don't tight-loop, then
                # propagate so the failure is visible.
                self._schedule_update_retry(exc)
                self._restart_existing_after_update_failure()
                raise

            with self._update_lock:
                self._update_pending = False
                self._update_reason = None
                self._update_bypass_window = False
                self._update_ignore_players = False
            self.monitor.reset_session()
            self.process.start(reason="update")
            self.notifier.notify(
                "updated",
                f"{self.plugin.name}: updated",
                f"Now running build {self.local_build_id or 'unknown'} (reason: {reason})",
                force=True,
            )
        finally:
            self._activity = None

    @staticmethod
    def _seconds_until_local_hour(hour: int, *, now: datetime | None = None) -> float:
        """Seconds until the next local ``hour:00:00`` (always in the future)."""

        current = now or datetime.now()
        target_hour = max(0, min(23, int(hour)))
        target = current.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if target <= current:
            target = target + timedelta(days=1)
        return max(1.0, (target - current).total_seconds())

    def _seconds_until_next_update_check(self) -> float:
        """How long to sleep before the next Steam "newer build?" probe."""

        minutes = self.steam_gate.clamp_check_interval_minutes(
            self.config.auto_update_interval_minutes
        )
        if minutes <= 0:
            return 0.0
        check_hour = self.config.auto_update_check_hour
        if check_hour is not None:
            # Prefer a once-daily wall-clock check (default 05:00 local) so we do
            # not poll Steam every few minutes as an anonymous client.
            return self._seconds_until_local_hour(check_hour)
        return float(max(0, minutes) * 60)

    def _update_checker_loop(self) -> None:
        minutes = self.steam_gate.clamp_check_interval_minutes(
            self.config.auto_update_interval_minutes
        )
        if minutes <= 0:
            LOG.info("Periodic Steam update checks disabled")
            return
        check_hour = self.config.auto_update_check_hour
        if check_hour is not None:
            LOG.info(
                "Checking Steam for updates once daily at local %02d:00 "
                "(Steam spacing %.0fs, max retries %s)",
                check_hour,
                self.steam_gate.policy.min_interval_seconds,
                self.steam_gate.policy.max_retries,
            )
        else:
            LOG.info(
                "Checking Steam for updates every %s minutes "
                "(Steam spacing %.0fs, max retries %s)",
                minutes,
                self.steam_gate.policy.min_interval_seconds,
                self.steam_gate.policy.max_retries,
            )
        while True:
            wait_for = self._seconds_until_next_update_check()
            if wait_for <= 0:
                return
            if check_hour is not None:
                LOG.info(
                    "Next Steam update check in %.0fs (daily at local %02d:00)",
                    wait_for,
                    check_hour,
                )
            if self._stop.wait(wait_for):
                return
            cooldown = self.steam_gate.seconds_until_next_call()
            if cooldown > 0:
                LOG.info(
                    "Skipping Steam update check; Steam cooldown %.0fs remaining",
                    cooldown,
                )
                continue
            self.update_check_count += 1
            self.last_update_check_at = time.time()
            run_uid, run_gid = self._steamcmd_identity()
            result = steamcmd.update_available(
                self.config.steamcmd_dir,
                self.config.install_dir,
                self.plugin,
                stop_event=self._stop,
                run_uid=run_uid,
                run_gid=run_gid,
            )
            self.local_build_id = result.local_build_id or self.local_build_id
            self.remote_build_id = result.remote_build_id
            if not result.check_ok:
                self.last_update_error = result.error
                LOG.warning(
                    "Steam update check unavailable (local=%s): %s",
                    result.local_build_id or "unknown",
                    result.error,
                )
                self.notifier.notify(
                    "update_check_failed",
                    f"{self.plugin.name}: update check failed",
                    str(result.error),
                )
                continue
            if result.update_available:
                LOG.info(
                    "Remote update available (local=%s remote=%s)",
                    result.local_build_id,
                    result.remote_build_id,
                )
                self.request_update(reason="steam_build", bypass_window=False)
            else:
                LOG.info(
                    "Game is up to date (buildid=%s)",
                    result.local_build_id
                    or result.remote_build_id
                    or "unknown",
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
                health_provider=self.health,
                game_name=self.plugin.name,
                log_toolbox=self.log_tools,
                capture_callback=self.capture_logs,
                update_callback=self.force_update_now,
                restore_callback=self.request_restore,
                backups_provider=lambda: self.backups.list_restorable_archives(),
            )
            self.status_server.start()

        self._status_thread = threading.Thread(
            target=self._status_loop, name="status-writer", daemon=True
        )
        self._status_thread.start()

        self.ensure_installed()
        self.monitor.start()
        self.backups.start()
        self.process.start(reason="boot")
        self._publish_status()

        self._update_thread = threading.Thread(
            target=self._update_checker_loop, name="update-checker", daemon=True
        )
        self._update_thread.start()

        while not self._stop.is_set():
            if self._restore_pending:
                archive_name = self._restore_pending
                try:
                    self._apply_restore(archive_name)
                except Exception:
                    LOG.exception("World restore from %s failed", archive_name)
                finally:
                    with self._restore_lock:
                        if self._restore_pending == archive_name:
                            self._restore_pending = None

            if self._update_pending and self._can_apply_update():
                try:
                    self._apply_update()
                except SteamCMDError:
                    LOG.exception("Steam update failed; backing off")
                    # Backoff + server recovery already handled in _apply_update.
                except Exception:
                    LOG.exception(
                        "Unexpected error applying update; backing off. "
                        "This is likely a supervisor bug."
                    )
                    # _apply_update schedules backoff for unexpected errors too.

            code = self.process.wait(timeout=2)
            if code is None:
                continue
            if self._stop.is_set():
                break
            if self._update_pending or self._restore_pending:
                continue
            if self.process.intentional_stop:
                break
            try:
                self.capture_logs("crash")
            except OSError:
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
                self.process.start(reason="crash")
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

    version = app_version()
    LOG.info("============================================================")
    LOG.info("Home Assistant app version: %s", version)
    LOG.info("============================================================")

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
        "Ingress status UI listens on port %s (HA OPEN WEB UI; host port not required)",
        config.status_http_port,
    )
    LOG.info(
        "Starting supervisor for %s (appid=%s, app_version=%s, install_dir=%s)",
        plugin.name,
        plugin.steam_app_id,
        version,
        config.install_dir,
    )
    supervisor = GameServerSupervisor(plugin, config)
    return supervisor.run()
