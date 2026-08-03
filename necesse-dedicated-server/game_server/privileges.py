"""Optional privilege drop for running game/SteamCMD as a non-root user."""

from __future__ import annotations

import logging
import os
import pwd
from pathlib import Path

LOG = logging.getLogger("game_server.privileges")


def resolve_user(username: str) -> tuple[int, int, str]:
    record = pwd.getpwnam(username)
    return record.pw_uid, record.pw_gid, record.pw_dir


def chown_paths(uid: int, gid: int, paths: list[str | Path]) -> None:
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        try:
            for root, dirs, files in os.walk(path):
                os.chown(root, uid, gid)
                for name in dirs + files:
                    try:
                        os.chown(os.path.join(root, name), uid, gid)
                    except OSError:
                        pass
            os.chown(path, uid, gid)
        except OSError as exc:
            LOG.warning("chown failed for %s: %s", path, exc)


def prepare_drop(
    username: str,
    paths: list[str | Path],
) -> tuple[int, int] | None:
    """Ensure target user owns key paths. Returns (uid, gid) or None if unavailable."""

    if os.geteuid() != 0:
        LOG.info("Not root; skipping privilege preparation")
        return None
    try:
        uid, gid, _home = resolve_user(username)
    except KeyError:
        LOG.warning("User %s not found; continuing as root", username)
        return None
    for path in paths:
        Path(path).mkdir(parents=True, exist_ok=True)
    chown_paths(uid, gid, paths)
    LOG.info("Prepared paths for user %s (%s:%s)", username, uid, gid)
    return uid, gid


def drop_to(uid: int, gid: int) -> None:
    """Permanently drop supervisor privileges (best-effort)."""

    if os.geteuid() != 0:
        return
    os.setgid(gid)
    os.setuid(uid)
    LOG.info("Dropped privileges to %s:%s", uid, gid)
