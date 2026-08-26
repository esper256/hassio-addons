"""Resolve the packaged Home Assistant app / image version."""

from __future__ import annotations

import os
from pathlib import Path

_VERSION_FILES = (
    Path("/etc/hassio_app_version"),
    Path("/APP_VERSION"),
)


def app_version() -> str:
    """Return the baked app version string (best effort)."""

    env = (os.environ.get("APP_VERSION") or os.environ.get("BUILD_VERSION") or "").strip()
    if env and env.lower() != "dev":
        return env

    for path in _VERSION_FILES:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text

    if env:
        return env
    return "unknown"
