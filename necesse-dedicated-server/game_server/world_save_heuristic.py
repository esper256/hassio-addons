"""DIRTY HACK: cross-game world-path guessing.

This module is intentionally separate from the happy-path locator in
``world_save.py``. Do not call it unless a game plugin explicitly sets:

- ``world_save.strategy: heuristic``, or
- ``world_save.allow_heuristic_fallback: true``

Prefer declaring ``world_save.paths`` templates in the game plugin instead.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .disk import path_total_bytes
from .world_save import SCOPE_HEURISTIC, ActiveWorld

LOG = logging.getLogger("game_server.world_save_heuristic")


def heuristic_locate_world(
    data_dir: str | Path,
    world_name: str | None = None,
    *,
    fallback_paths: list[str | Path] | None = None,
) -> ActiveWorld | None:
    """Guess common dedicated-server world layouts. Returns None if nothing matches.

    When guessing fails, the caller should fall back to honest backup_sources /
    missing scopes — this function does not quietly sum the data dir and claim
    it is a named world file.
    """

    data_root = Path(data_dir)
    name = (world_name or "").strip()
    if not name:
        LOG.warning(
            "Heuristic world locate invoked without world_name under %s", data_root
        )
        return None

    stem = name[:-4] if name.lower().endswith(".zip") else name
    # Ordered guesses seen across a few Steam dedicated servers. Not a contract.
    candidates = [
        data_root / "saves" / "worlds" / f"{stem}.zip",
        data_root / "saves" / "worlds" / stem,
        data_root / "saves" / f"{stem}.zip",
        data_root / "saves" / stem,
        data_root / "worlds" / f"{stem}.zip",
        data_root / "worlds" / stem,
        data_root / f"{stem}.zip",
        data_root / stem,
    ]
    # fallback_paths are intentionally unused for a positive "named file" hit;
    # callers own the backup_sources fallback. Kept in the signature so opt-in
    # call sites can pass the same roots they use elsewhere.
    _ = fallback_paths

    for path in candidates:
        if path.is_file() or path.is_dir():
            LOG.warning(
                "Heuristic world locate matched %s (plugin should declare world_save.paths)",
                path,
            )
            return ActiveWorld(
                bytes=path_total_bytes(path),
                path=str(path),
                label=path.name,
                scope=SCOPE_HEURISTIC,
                sources=[str(path)],
                expected_paths=[str(p) for p in candidates],
            )
    return None
