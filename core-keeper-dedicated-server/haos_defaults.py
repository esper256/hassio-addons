"""Core Keeper-only helpers for Home Assistant / Docker defaults.

Kept outside the shared ``game_server`` package so title-specific naming
never leaks into ``game-server-base``.

Core Keeper clients join with a **Game ID** (Steam Datagram Relay), not an
IP:port. An empty ``-gameid`` makes the dedicated server mint a new ID on
start, which would change the join code after every restart. This helper
pins a stable per-install ID (or an explicit HA option) so friends can
keep using the same code.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

INSTANCE_SALT_NAME = "instance_salt"
# Official dedicated-server README: 15–28 alphanumeric characters. Older notes
# also excluded lookalikes (0/O/o/I/l) and x/y; stay inside that alphabet so
# both current and older builds accept the ID.
_GAME_ID_ALPHABET = "abcdefghijkmnpqrstuvwzABCDEFGHJKLMNPQRSTUVWXYZ123456789"
_GAME_ID_LENGTH = 20


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


def default_game_id(
    *,
    state_dir: str | Path | None = None,
) -> str:
    """Build a stable 20-character Game ID from the persisted install salt."""

    root = Path(state_dir or os.environ.get("STATE_DIR") or "/data/supervisor")
    salt = ensure_instance_salt(root / INSTANCE_SALT_NAME)
    digest = hashlib.sha256(f"core-keeper-game-id|{salt}".encode("utf-8")).digest()
    alphabet = _GAME_ID_ALPHABET
    chars: list[str] = []
    # Consume digest bytes, then a counter stream, until we have 20 symbols.
    material = digest
    n = 0
    while len(chars) < _GAME_ID_LENGTH:
        if n >= len(material):
            material += hashlib.sha256(digest + n.to_bytes(4, "big")).digest()
        chars.append(alphabet[material[n] % len(alphabet)])
        n += 1
    return "".join(chars)


def resolve_game_id(
    *,
    options_file: str | Path | None = None,
    state_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """Prefer an explicit Game ID; otherwise generate a stable default."""

    env = environ if environ is not None else os.environ
    from_env = str(env.get("GAME_ID") or "").strip()
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
            from_options = str(data.get("game_id") or "").strip()
            if from_options:
                return from_options

    return default_game_id(state_dir=state_dir)


def main() -> int:
    print(resolve_game_id())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
