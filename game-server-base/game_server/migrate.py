"""Generic one-time path migrations declared by game plugins."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .plugin import GamePlugin, PathMigration

LOG = logging.getLogger("game_server.migrate")


def apply_path_migrations(plugin: GamePlugin) -> list[str]:
    applied: list[str] = []
    for migration in plugin.path_migrations:
        if _apply_one(migration):
            applied.append(f"{migration.source} -> {migration.destination}")
    return applied


def _apply_one(migration: PathMigration) -> bool:
    source = Path(migration.source)
    destination = Path(migration.destination)
    marker = migration.marker

    if not source.exists():
        return False

    dest_marker = destination / marker if marker else destination
    source_marker = source / marker if marker else source

    if marker:
        if dest_marker.exists():
            return False
        if not source_marker.exists():
            return False
    elif destination.exists() and any(destination.iterdir()):
        return False

    destination.mkdir(parents=True, exist_ok=True)
    LOG.info(
        "Applying path migration %s -> %s",
        source,
        destination,
    )
    if source.is_dir():
        # Copy contents into destination.
        for item in source.iterdir():
            target = destination / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    else:
        shutil.copy2(source, destination)
    return True
