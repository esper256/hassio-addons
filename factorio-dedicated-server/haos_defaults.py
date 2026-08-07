"""Factorio-only helpers for Home Assistant / Docker defaults.

Kept outside the shared ``game_server`` package so title-specific naming
never leaks into ``game-server-base``.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

INSTANCE_SALT_NAME = "instance_salt"
SERVER_NAME_PREFIX = "HAOS Factorio"


def ensure_instance_salt(path: Path) -> str:
    """Return a stable per-install salt; create one if missing.

    Stored on the persistent data volume so the same add-on instance keeps the
    same value across restarts, without hashing host hardware identifiers.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    salt = secrets.token_hex(16)
    path.write_text(salt + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return salt


def default_server_name(
    *,
    state_dir: str | Path | None = None,
    prefix: str = SERVER_NAME_PREFIX,
) -> str:
    """Build ``HAOS Factorio ####`` from a persisted install salt."""

    root = Path(state_dir or os.environ.get("STATE_DIR") or "/data/supervisor")
    salt = ensure_instance_salt(root / INSTANCE_SALT_NAME)
    digest = hashlib.sha256(f"factorio-server-name|{salt}".encode("utf-8")).hexdigest()
    digits = int(digest[:8], 16) % 10000
    return f"{prefix} {digits:04d}"


def resolve_server_name(
    *,
    options_file: str | Path | None = None,
    state_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """Prefer an explicit name; otherwise generate a stable default."""

    env = environ if environ is not None else os.environ
    from_env = str(env.get("SERVER_NAME") or "").strip()
    if from_env:
        return from_env

    path = Path(
        options_file
        or env.get("OPTIONS_FILE")
        or env.get("HASSIO_OPTIONS_FILE")
        or "/data/options.json"
    )
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            from_options = str(data.get("server_name") or "").strip()
            if from_options:
                return from_options

    return default_server_name(state_dir=state_dir)


def main() -> int:
    print(resolve_server_name())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
