"""World data backup helpers."""

from __future__ import annotations

import logging
import tarfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("game_server.backup")


class BackupManager:
    def __init__(
        self,
        backup_dir: str | Path,
        sources: list[str | Path],
        *,
        retain: int = 10,
        interval_minutes: int = 180,
        enabled: bool = True,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.sources = [Path(s) for s in sources]
        self.retain = max(1, retain)
        self.interval_seconds = max(0, interval_minutes) * 60
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_backup_at: float | None = None
        self.last_backup_path: str | None = None
        self.last_error: str | None = None
        self.backup_count = 0

    def start(self) -> None:
        if not self.enabled or self.interval_seconds <= 0:
            LOG.info("Periodic backups disabled")
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="backup", daemon=True)
        self._thread.start()
        LOG.info(
            "Periodic backups every %s minutes into %s",
            self.interval_seconds // 60,
            self.backup_dir,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        # First backup after one interval, not immediately on boot
        while not self._stop.wait(self.interval_seconds):
            try:
                self.create_backup(reason="schedule")
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                LOG.exception("Scheduled backup failed")

    def create_backup(self, reason: str = "manual") -> Path | None:
        if not self.enabled:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = self.backup_dir / f"backup-{stamp}-{reason}.tar.gz"
        existing = [s for s in self.sources if s.exists()]
        if not existing:
            LOG.warning("No backup sources exist yet: %s", self.sources)
            return None

        LOG.info("Creating backup %s from %s", archive.name, existing)
        with tarfile.open(archive, "w:gz") as tar:
            for source in existing:
                arcname = source.name
                tar.add(source, arcname=arcname)

        self.last_backup_at = time.time()
        self.last_backup_path = str(archive)
        self.backup_count += 1
        self.last_error = None
        self._prune()
        return archive

    def _prune(self) -> None:
        archives = sorted(
            self.backup_dir.glob("backup-*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in archives[self.retain :]:
            try:
                stale.unlink()
                LOG.info("Pruned old backup %s", stale.name)
            except OSError:
                LOG.warning("Failed to prune %s", stale)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "backup_dir": str(self.backup_dir),
            "retain": self.retain,
            "interval_minutes": self.interval_seconds // 60,
            "last_backup_at": self.last_backup_at,
            "last_backup_path": self.last_backup_path,
            "last_error": self.last_error,
            "backup_count": self.backup_count,
            "sources": [str(s) for s in self.sources],
        }
