"""Disk free-space helpers."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

LOG = logging.getLogger("game_server.disk")


def free_bytes(path: str | Path) -> int | None:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(path).free
    except OSError as exc:
        LOG.warning("Unable to check free space for %s: %s", path, exc)
        return None


def free_mb(path: str | Path) -> float | None:
    value = free_bytes(path)
    return None if value is None else value / (1024 * 1024)


def ensure_free_mb(path: str | Path, minimum_mb: int) -> tuple[bool, float | None]:
    """Return (ok, free_mb). ok is True when check is disabled or space is sufficient."""

    if minimum_mb <= 0:
        return True, free_mb(path)
    available = free_mb(path)
    if available is None:
        # Fail open if we cannot measure — better than blocking forever.
        return True, None
    if available < minimum_mb:
        LOG.error(
            "Insufficient disk space under %s: %.1f MiB free < %s MiB required",
            path,
            available,
            minimum_mb,
        )
        return False, available
    return True, available


def path_total_bytes(path: str | Path) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    if root.is_file():
        return root.stat().st_size
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def format_bytes(num_bytes: int | float | None) -> str:
    """Human-readable size for status UI (KB / MB / GB, one decimal when useful)."""

    if num_bytes is None:
        return "unknown"
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return "unknown"
    if value < 0:
        return "unknown"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = value
    unit = units[0]
    for candidate in units:
        unit = candidate
        if size < 1024 or candidate == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} B"
    if size >= 100 or unit == "KB":
        return f"{size:.0f} {unit}"
    return f"{size:.1f} {unit}"


def world_save_size(
    data_dir: str | Path,
    world_name: str | None = None,
    *,
    fallback_paths: list[str | Path] | None = None,
) -> dict[str, object]:
    """Best-effort size of the active world save.

    Prefers a concrete world file when ``world_name`` is known; otherwise sums
    fallback paths (typically plugin backup_paths / data_dir).
    """

    data_root = Path(data_dir)
    name = (world_name or "").strip()
    if name:
        # Common dedicated-server layouts (zipped or directory worlds).
        stem = name if name.endswith(".zip") else name
        candidates = [
            data_root / "saves" / "worlds" / f"{stem}.zip",
            data_root / "saves" / "worlds" / stem,
            data_root / "saves" / f"{stem}.zip",
            data_root / "saves" / stem,
            data_root / f"{stem}.zip",
            data_root / stem,
        ]
        for path in candidates:
            if path.is_file() or path.is_dir():
                return {
                    "bytes": path_total_bytes(path),
                    "path": str(path),
                    "label": path.name,
                    "scope": "world_file",
                }

    total = 0
    sources: list[str] = []
    for raw in fallback_paths or [data_root]:
        path = Path(raw)
        if path.exists():
            total += path_total_bytes(path)
            sources.append(str(path))
    return {
        "bytes": total,
        "path": sources[0] if len(sources) == 1 else None,
        "label": "world data" if sources else None,
        "scope": "data_dir" if sources else "missing",
        "sources": sources,
    }
