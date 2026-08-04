"""World data backups with generational retention and failure backoff."""

from __future__ import annotations

import logging
import re
import shutil
import tarfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .disk import ensure_free_mb, path_total_bytes

LOG = logging.getLogger("game_server.backup")

# Two archive families under backup_dir. Both are only deleted by the configured
# generational retention plan (never by an ad-hoc "keep N" cap).
ROTATION_GLOB = "backup-*.tar.gz"
PRE_RESTORE_GLOB = "pre-restore-*.tar.gz"
_ARCHIVE_NAME_RE = re.compile(r"^(backup|pre-restore)-[A-Za-z0-9._-]+\.tar\.gz$")

# Pending-restore token: wipe world sources and let the game create a fresh world.
EMPTY_WORLD = "__empty__"


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
        self._on_failure: Callable[[str], None] | None = None
        self._lock = threading.Lock()

    def set_failure_callback(self, callback: Callable[[str], None] | None) -> None:
        """Optional hook for HA notifications / status when backups fail."""

        self._on_failure = callback

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
            except (OSError, tarfile.TarError) as exc:
                # Disk/tar problems are environmental; back off and keep trying.
                self.last_error = str(exc)
                self._register_failure(str(exc))
                LOG.exception("Scheduled backup failed")
            # Other exceptions are backup-code bugs — let the backup thread die
            # so they are not hidden behind endless "scheduled backup failed".
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
        if self._on_failure is not None:
            try:
                self._on_failure(reason)
            except Exception:  # noqa: BLE001
                LOG.exception("Backup failure callback failed")

    def source_bytes(self) -> int:
        return sum(path_total_bytes(source) for source in self.sources)

    def sources_have_any_data(self) -> bool:
        """True if any non-empty file exists under configured backup sources.

        Used before destructive world ops. Unlike ``validate_sources``, this does
        not apply ``min_source_bytes`` — a small save is still a save.
        """

        for source in self.sources:
            if not source.exists():
                continue
            if source.is_file():
                try:
                    if source.stat().st_size > 0:
                        return True
                except OSError:
                    continue
                continue
            if not source.is_dir():
                continue
            try:
                for path in source.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        try:
                            if path.stat().st_size > 0:
                                return True
                        except OSError:
                            continue
            except OSError:
                continue
        return False

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

    def create_backup(
        self,
        reason: str = "manual",
        *,
        outside_rotation: bool = False,
        allow_tiny: bool = False,
        prune_after: bool = True,
    ) -> Path | None:
        """Create a world archive under backup_dir.

        ``outside_rotation=True`` writes a ``pre-restore-*.tar.gz`` safety copy
        (separate filename family; still pruned only via the retention plan).

        ``allow_tiny=True`` skips ``min_source_bytes`` (required for pre-wipe
        safety copies — a small world is still worth keeping).

        ``prune_after=False`` defers retention pruning (used while a live-world
        wipe still depends on the archive that was just created).
        """

        if not self.enabled and not outside_rotation:
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

        if allow_tiny:
            if not self.sources_have_any_data():
                self.last_skip_reason = "no world data to back up"
                self.last_error = self.last_skip_reason
                LOG.warning("Skipping backup: %s", self.last_skip_reason)
                return None
        else:
            valid, reason_text = self.validate_sources()
            if not valid:
                self.last_skip_reason = reason_text
                self.last_error = reason_text
                LOG.warning("Skipping backup: %s", reason_text)
                return None

        existing = [s for s in self.sources if s.exists()]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_reason = re.sub(r"[^A-Za-z0-9._-]+", "-", reason).strip("-") or "manual"
        if outside_rotation:
            archive = self.backup_dir / f"pre-restore-{stamp}-{safe_reason}.tar.gz"
        else:
            archive = self.backup_dir / f"backup-{stamp}-{safe_reason}.tar.gz"
        LOG.info("Creating backup %s from %s", archive.name, existing)
        with tarfile.open(archive, "w:gz") as tar:
            for source in existing:
                tar.add(source, arcname=source.name)

        # Reject accidental empty archives (never keep a useless file).
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
        if prune_after:
            self.apply_retention()
        return archive

    def create_safety_backup(self, reason: str = "safety") -> Path | None:
        """Pre-wipe safety copy: any non-empty world data, no immediate prune."""

        return self.create_backup(
            reason=reason,
            outside_rotation=True,
            allow_tiny=True,
            prune_after=False,
        )

    def apply_retention(self) -> None:
        """Delete archives that fall outside the configured retention plan.

        This is the only intentional bulk-delete of backup archives.
        """

        self._prune_glob(ROTATION_GLOB)
        self._prune_glob(PRE_RESTORE_GLOB)

    def _prune_glob(self, pattern: str) -> None:
        archives = sorted(
            self.backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        keep = select_generational_keepers(archives, self.retention)
        for stale in archives:
            if stale in keep:
                continue
            try:
                stale.unlink()
                LOG.info("Pruned old backup %s (retention)", stale.name)
            except OSError:
                LOG.warning("Failed to prune %s", stale)

    def _prune(self) -> None:
        """Backward-compatible alias for tests / callers."""

        self.apply_retention()

    def list_archives(self) -> list[Path]:
        """Return rotatable backup archives oldest → newest."""

        if not self.backup_dir.exists():
            return []
        return sorted(
            self.backup_dir.glob(ROTATION_GLOB),
            key=lambda p: p.stat().st_mtime,
        )

    def list_pre_restore_archives(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(
            self.backup_dir.glob(PRE_RESTORE_GLOB),
            key=lambda p: p.stat().st_mtime,
        )

    def list_restorable_archives(self) -> list[dict[str, Any]]:
        """Archives the UI may offer for restore (rotation + recent pre-restore)."""

        items: list[dict[str, Any]] = []
        for path in list(self.list_archives()) + list(self.list_pre_restore_archives()):
            try:
                st = path.stat()
            except OSError:
                continue
            kind = "pre-restore" if path.name.startswith("pre-restore-") else "backup"
            items.append(
                {
                    "name": path.name,
                    "kind": kind,
                    "bytes": st.st_size,
                    "mtime": st.st_mtime,
                }
            )
        items.sort(key=lambda item: float(item["mtime"]), reverse=True)
        return items

    def resolve_archive(self, name: str) -> Path | None:
        """Resolve a backup basename under backup_dir; reject traversal."""

        raw = str(name or "").strip()
        if not raw or not _ARCHIVE_NAME_RE.fullmatch(raw):
            return None
        root = self.backup_dir.resolve()
        path = (self.backup_dir / raw).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        return path if path.is_file() else None

    def _require_safety_backup_before_wipe(self, prior_safety_backup: Path | None) -> None:
        """Hard gate: never delete live world data without a real safety archive."""

        if not self.sources_have_any_data():
            return
        if prior_safety_backup is None:
            raise RuntimeError(
                "refusing to delete live world data without a successful safety backup"
            )
        path = Path(prior_safety_backup)
        if not path.is_file():
            raise RuntimeError(
                f"refusing to delete live world data; safety backup missing: {path.name}"
            )
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise RuntimeError(
                f"refusing to delete live world data; cannot stat safety backup: {exc}"
            ) from exc
        if size < 64:
            raise RuntimeError(
                f"refusing to delete live world data; safety backup is empty: {path.name}"
            )
        # Must live under backup_dir (no arbitrary path as a "safety" token).
        root = self.backup_dir.resolve()
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                "refusing to delete live world data; safety backup is outside backup_dir"
            ) from exc

    def _clear_source_contents(self) -> list[str]:
        """Remove world *data* while keeping existing directory inodes.

        Why not delete + recreate the source directory? Backup roots such as
        ``/data/world`` are prepared once for the non-root game user
        (``gameserver``). If the supervisor (often root) ``rmtree``s that path
        and ``mkdir``s a replacement, the new inode is root-owned and the game
        child can fail with permission errors on the next start. Emptying
        children in place keeps the original ownership and mode.

        File sources are unlinked (parent directory is left alone). Missing
        sources are left missing — do not recreate them here.

        Callers must pass the wipe-gate in ``clear_world_sources`` /
        ``restore_archive`` first.
        """

        cleared: list[str] = []
        for source in self.sources:
            if not source.exists():
                continue
            if source.is_file():
                LOG.info("Removing current world file: %s", source)
                source.unlink()
                cleared.append(str(source))
                continue
            if not source.is_dir():
                continue
            LOG.info("Clearing world data in place (keep dir ownership): %s", source)
            for child in list(source.iterdir()):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            cleared.append(str(source))
        return cleared

    def clear_world_sources(
        self, *, prior_safety_backup: Path | None
    ) -> dict[str, Any]:
        """Wipe configured world data so the next start is a fresh world.

        Does not stop/start the game process — caller owns lifecycle.
        If any world data exists, ``prior_safety_backup`` must be a successful
        archive under backup_dir (refuse otherwise).
        """

        with self._lock:
            self._require_safety_backup_before_wipe(prior_safety_backup)
            removed = self._clear_source_contents()
        return {
            "ok": True,
            "empty": True,
            "cleared": removed,
            "sources": [str(s) for s in self.sources],
            "safety_backup": (
                prior_safety_backup.name if prior_safety_backup is not None else None
            ),
        }

    def restore_archive(
        self,
        archive: str | Path,
        *,
        prior_safety_backup: Path | None,
    ) -> dict[str, Any]:
        """Extract a backup over configured world sources.

        Does not stop/start the game process — caller owns lifecycle.
        If any world data exists, ``prior_safety_backup`` must be a successful
        archive under backup_dir (refuse otherwise).
        """

        path = self.resolve_archive(str(archive)) if not isinstance(archive, Path) else archive
        if path is None or not path.is_file():
            raise FileNotFoundError(f"backup archive not found: {archive}")
        path = path.resolve()
        root = self.backup_dir.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"archive outside backup dir: {archive}") from exc

        # Archives store each source under arcname=source.name (e.g. "world/...").
        # Extract into each source's parent so "world/" lands on the real world root.
        parents = {source.parent.resolve() for source in self.sources}
        if len(parents) != 1:
            raise RuntimeError(
                f"restore requires a single parent for backup sources; got {parents}"
            )
        extract_root = next(iter(parents))

        with self._lock:
            self._require_safety_backup_before_wipe(prior_safety_backup)
            # Clear contents in place when the source is a directory so we do not
            # replace a gameserver-owned inode with a root-owned one before extract.
            self._clear_source_contents()

            LOG.info("Restoring %s into %s", path.name, extract_root)
            with tarfile.open(path, "r:gz") as tar:
                # Python 3.12+: filter='data' blocks unsafe paths when available.
                try:
                    tar.extractall(extract_root, filter="data")  # type: ignore[call-arg]
                except TypeError:
                    self._extract_safe(tar, extract_root)

        return {
            "ok": True,
            "archive": path.name,
            "extract_root": str(extract_root),
            "sources": [str(s) for s in self.sources],
            "safety_backup": (
                prior_safety_backup.name if prior_safety_backup is not None else None
            ),
        }

    @staticmethod
    def _extract_safe(tar: tarfile.TarFile, extract_root: Path) -> None:
        """Fallback extractor that rejects path traversal members."""

        root = extract_root.resolve()
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"refusing unsafe tar member: {name}")
            target = (extract_root / name).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"refusing tar member outside root: {name}") from exc
            tar.extract(member, extract_root)

    def archive_summary(self) -> dict[str, object]:
        """Count + oldest/newest timestamps for status UI (rotation set only)."""

        archives = self.list_archives()
        if not archives:
            return {
                "count": 0,
                "oldest_at": None,
                "newest_at": None,
                "oldest_name": None,
                "newest_name": None,
            }
        oldest = archives[0]
        newest = archives[-1]
        return {
            "count": len(archives),
            "oldest_at": oldest.stat().st_mtime,
            "newest_at": newest.stat().st_mtime,
            "oldest_name": oldest.name,
            "newest_name": newest.name,
        }

    def to_dict(self) -> dict:
        summary = self.archive_summary()
        archives = self.list_archives()
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
            "archive_count": summary["count"],
            "oldest_backup_at": summary["oldest_at"],
            "newest_backup_at": summary["newest_at"],
            "oldest_backup_name": summary["oldest_name"],
            "newest_backup_name": summary["newest_name"],
            "consecutive_failures": self.consecutive_failures,
            "next_delay_minutes": self._current_delay_seconds() // 60,
            "source_bytes": self.source_bytes(),
            "sources": [str(s) for s in self.sources],
            "archives": [p.name for p in archives],
            "restorable": self.list_restorable_archives(),
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
