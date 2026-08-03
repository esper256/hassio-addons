"""World data backups with generational retention and failure backoff."""

from __future__ import annotations

import logging
import tarfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .disk import ensure_free_mb, path_total_bytes

LOG = logging.getLogger("game_server.backup")


@dataclass
class RetentionPolicy:
    """Cascading retention: daily → weekly → monthly (optional yearly)."""

    keep_recent: int = 0
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 12
    keep_yearly: int = 0
    profile: str = "standard"

    def describe(self) -> str:
        parts = [
            f"{self.keep_daily} daily",
            f"{self.keep_weekly} weekly",
            f"{self.keep_monthly} monthly",
        ]
        if self.keep_yearly:
            parts.append(f"{self.keep_yearly} yearly")
        return f"{self.profile} ({', '.join(parts)})"


# Simple UX: one named profile instead of tuning each tier.
# Standard matches the common NAS pattern: dailies for a week, weeklies for a
# month, then monthlies for about a year.
RETENTION_PROFILES: dict[str, RetentionPolicy] = {
    "minimal": RetentionPolicy(
        keep_daily=3,
        keep_weekly=2,
        keep_monthly=3,
        keep_yearly=0,
        profile="minimal",
    ),
    "standard": RetentionPolicy(
        keep_daily=7,
        keep_weekly=4,
        keep_monthly=12,
        keep_yearly=0,
        profile="standard",
    ),
    "extended": RetentionPolicy(
        keep_daily=7,
        keep_weekly=8,
        keep_monthly=24,
        keep_yearly=2,
        profile="extended",
    ),
}


def retention_from_profile(name: str | None) -> RetentionPolicy:
    key = (name or "standard").strip().lower()
    if key not in RETENTION_PROFILES:
        LOG.warning("Unknown backup_retention %r; using standard", name)
        key = "standard"
    return RETENTION_PROFILES[key]


class BackupManager:
    def __init__(
        self,
        backup_dir: str | Path,
        sources: list[str | Path],
        *,
        interval_minutes: int = 180,
        enabled: bool = True,
        retention: RetentionPolicy | None = None,
        min_source_bytes: int = 1024,
        min_free_disk_mb: int = 512,
        max_backoff_minutes: int = 1440,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.sources = [Path(s) for s in sources]
        self.interval_seconds = max(0, interval_minutes) * 60
        self.enabled = enabled
        self.retention = retention or RetentionPolicy()
        self.min_source_bytes = max(0, min_source_bytes)
        self.min_free_disk_mb = max(0, min_free_disk_mb)
        self.max_backoff_seconds = max(self.interval_seconds, max_backoff_minutes * 60)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_backup_at: float | None = None
        self.last_backup_path: str | None = None
        self.last_error: str | None = None
        self.last_skip_reason: str | None = None
        self.backup_count = 0
        self.consecutive_failures = 0
        self.next_eligible_at: float = 0.0

    def start(self) -> None:
        if not self.enabled or self.interval_seconds <= 0:
            LOG.info("Periodic backups disabled")
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="backup", daemon=True)
        self._thread.start()
        LOG.info(
            "Periodic backups every %s minutes into %s (generational retention)",
            self.interval_seconds // 60,
            self.backup_dir,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _current_delay_seconds(self) -> int:
        if self.consecutive_failures <= 0:
            return self.interval_seconds
        # Exponential backoff: interval * 2^failures, capped.
        delay = self.interval_seconds * (2 ** min(self.consecutive_failures, 8))
        return int(min(self.max_backoff_seconds, delay))

    def _loop(self) -> None:
        # First backup after one base interval, not immediately on boot.
        delay = self.interval_seconds
        while not self._stop.wait(delay):
            try:
                result = self.create_backup(reason="schedule")
                if result is None and self.last_skip_reason:
                    self._register_failure(self.last_skip_reason)
                elif result is None and self.last_error:
                    self._register_failure(self.last_error)
                else:
                    self.consecutive_failures = 0
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                self._register_failure(str(exc))
                LOG.exception("Scheduled backup failed")
            delay = self._current_delay_seconds()
            LOG.info("Next backup attempt in %s minutes", max(1, delay // 60))

    def _register_failure(self, reason: str) -> None:
        self.consecutive_failures += 1
        self.next_eligible_at = time.time() + self._current_delay_seconds()
        LOG.warning(
            "Backup issue (%s). consecutive_failures=%s; backing off",
            reason,
            self.consecutive_failures,
        )

    def source_bytes(self) -> int:
        return sum(path_total_bytes(source) for source in self.sources)

    def validate_sources(self) -> tuple[bool, str | None]:
        existing = [s for s in self.sources if s.exists()]
        if not existing:
            return False, f"no backup sources exist yet: {self.sources}"
        total = sum(path_total_bytes(source) for source in existing)
        if self.min_source_bytes and total < self.min_source_bytes:
            return (
                False,
                f"backup sources only {total} bytes (< {self.min_source_bytes}); refusing empty/tiny world",
            )
        return True, None

    def create_backup(self, reason: str = "manual") -> Path | None:
        if not self.enabled:
            return None
        self.last_skip_reason = None
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        ok, available = ensure_free_mb(self.backup_dir, self.min_free_disk_mb)
        if not ok:
            self.last_error = (
                f"insufficient disk space ({available:.1f} MiB free)"
                if available is not None
                else "insufficient disk space"
            )
            return None

        valid, reason_text = self.validate_sources()
        if not valid:
            self.last_skip_reason = reason_text
            self.last_error = reason_text
            LOG.warning("Skipping backup: %s", reason_text)
            return None

        existing = [s for s in self.sources if s.exists()]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = self.backup_dir / f"backup-{stamp}-{reason}.tar.gz"
        LOG.info("Creating backup %s from %s", archive.name, existing)
        with tarfile.open(archive, "w:gz") as tar:
            for source in existing:
                tar.add(source, arcname=source.name)

        # Reject accidental empty archives.
        if archive.stat().st_size < 64:
            archive.unlink(missing_ok=True)
            self.last_skip_reason = "archive was empty/tiny after creation"
            self.last_error = self.last_skip_reason
            return None

        self.last_backup_at = time.time()
        self.last_backup_path = str(archive)
        self.backup_count += 1
        self.last_error = None
        self.last_skip_reason = None
        self._prune()
        return archive

    def _prune(self) -> None:
        archives = sorted(
            self.backup_dir.glob("backup-*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        keep = select_generational_keepers(archives, self.retention)
        for stale in archives:
            if stale in keep:
                continue
            try:
                stale.unlink()
                LOG.info("Pruned old backup %s", stale.name)
            except OSError:
                LOG.warning("Failed to prune %s", stale)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "backup_dir": str(self.backup_dir),
            "interval_minutes": self.interval_seconds // 60,
            "retention": {
                "profile": self.retention.profile,
                "description": self.retention.describe(),
                "keep_daily": self.retention.keep_daily,
                "keep_weekly": self.retention.keep_weekly,
                "keep_monthly": self.retention.keep_monthly,
                "keep_yearly": self.retention.keep_yearly,
            },
            "min_source_bytes": self.min_source_bytes,
            "min_free_disk_mb": self.min_free_disk_mb,
            "last_backup_at": self.last_backup_at,
            "last_backup_path": self.last_backup_path,
            "last_error": self.last_error,
            "last_skip_reason": self.last_skip_reason,
            "backup_count": self.backup_count,
            "consecutive_failures": self.consecutive_failures,
            "next_delay_minutes": self._current_delay_seconds() // 60,
            "source_bytes": self.source_bytes(),
            "sources": [str(s) for s in self.sources],
            "archives": [p.name for p in sorted(self.backup_dir.glob("backup-*.tar.gz"))]
            if self.backup_dir.exists()
            else [],
        }


def select_generational_keepers(
    archives: list[Path],
    policy: RetentionPolicy,
) -> set[Path]:
    """Keep newest recent + one per day/week/month/year slot."""

    keep: set[Path] = set()
    if not archives:
        return keep

    for archive in archives[: max(0, policy.keep_recent)]:
        keep.add(archive)

    def _add_period(fmt: str, limit: int) -> None:
        seen: list[str] = []
        for archive in archives:
            dt = datetime.fromtimestamp(archive.stat().st_mtime, tz=timezone.utc)
            key = dt.strftime(fmt)
            if key in seen:
                continue
            seen.append(key)
            keep.add(archive)
            if len(seen) >= limit:
                break

    _add_period("%Y-%m-%d", policy.keep_daily)
    _add_period("%G-W%V", policy.keep_weekly)
    _add_period("%Y-%m", policy.keep_monthly)
    _add_period("%Y", policy.keep_yearly)
    return keep
