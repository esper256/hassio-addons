"""Core Keeper-only helpers for Home Assistant / Docker defaults.

Kept outside the shared ``game_server`` package so title-specific naming
never leaks into ``game-server-base``.

Core Keeper clients join with a **Game ID** (Steam Datagram Relay) and,
when Direct Connect is on (this app's default), also by IP:port + password.
An empty or invalid ``-gameid`` makes the dedicated server mint a new ID on
start, which would change the join code and strand players. An omitted
``-password`` under Direct Connect would mint a new IP-join password. This
helper pins stable per-install values so friends can keep using the same codes.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

INSTANCE_SALT_NAME = "instance_salt"
# Official ARGUMENTS.txt: 15–28 alphanumeric characters; may not include
# Y, y, x, 0, or O. Generated IDs also skip lookalikes I/l/o so the code
# stays readable; user-pinned IDs only have to satisfy the official rules.
_OFFICIAL_FORBIDDEN = frozenset("Yyx0O")
_GAME_ID_ALPHABET = "abcdefghijkmnpqrstuvwzABCDEFGHJKLMNPQRSTUVWXZ123456789"
_GAME_ID_LENGTH = 20
_GAME_ID_MIN = 15
_GAME_ID_MAX = 28
_PASSWORD_LENGTH = 16
_PASSWORD_MAX = 28


def is_valid_game_id(value: object) -> bool:
    """True when ``value`` is a Game ID the dedicated server will accept."""

    text = str(value or "").strip()
    if not (_GAME_ID_MIN <= len(text) <= _GAME_ID_MAX):
        return False
    if not text.isalnum():
        return False
    return not (set(text) & _OFFICIAL_FORBIDDEN)


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


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def _read_gameid_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("gameid:"):
            return stripped.split(":", 1)[1].strip()
    return text.splitlines()[0].strip()


def _read_server_config_game_id(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("gameId") or "").strip()


def resolve_game_id(
    *,
    options_file: str | Path | None = None,
    state_dir: str | Path | None = None,
    install_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """Prefer an explicit Game ID; otherwise reuse a persisted one; else generate.

    Order: valid env ``GAME_ID``, valid HA ``game_id``, ``GameID.txt`` /
    ``GameInfo.txt`` next to the binary, ``ServerConfig.json`` ``gameId``, then
    the salt-derived default. Invalid values are skipped so the dedicated
    server never sees a code it would replace with a random one.
    """

    env = environ if environ is not None else os.environ
    candidates: list[tuple[str, str]] = []

    from_env = str(env.get("GAME_ID") or "").strip()
    if from_env:
        candidates.append(("GAME_ID", from_env))

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
                candidates.append(("options.game_id", from_options))

    game_root = Path(
        install_dir or env.get("INSTALL_DIR") or "/data/game"
    )
    candidates.append(("GameID.txt", _read_gameid_file(game_root / "GameID.txt")))
    candidates.append(("GameInfo.txt", _read_gameid_file(game_root / "GameInfo.txt")))

    world_root = Path(data_dir or env.get("DATA_DIR") or "/data/world")
    candidates.append(
        (
            "ServerConfig.json",
            _read_server_config_game_id(world_root / "ServerConfig.json"),
        )
    )

    for source, value in candidates:
        if not value:
            continue
        if is_valid_game_id(value):
            return value
        _warn(
            f"Ignoring invalid Core Keeper Game ID from {source} "
            f"({len(value)} chars); the dedicated server would mint a new "
            "random code if this were passed through."
        )

    return default_game_id(state_dir=state_dir)


def is_valid_server_password(value: object) -> bool:
    """True when Direct Connect ``-password`` is within Pugstorm's 1–28 limit."""

    text = str(value or "").strip()
    return 1 <= len(text) <= _PASSWORD_MAX


def default_server_password(
    *,
    state_dir: str | Path | None = None,
) -> str:
    """Stable per-install Direct Connect password from the same install salt."""

    root = Path(state_dir or os.environ.get("STATE_DIR") or "/data/supervisor")
    salt = ensure_instance_salt(root / INSTANCE_SALT_NAME)
    digest = hashlib.sha256(f"core-keeper-password|{salt}".encode("utf-8")).digest()
    alphabet = _GAME_ID_ALPHABET
    chars: list[str] = []
    material = digest
    n = 0
    while len(chars) < _PASSWORD_LENGTH:
        if n >= len(material):
            material += hashlib.sha256(digest + n.to_bytes(4, "big")).digest()
        chars.append(alphabet[material[n] % len(alphabet)])
        n += 1
    return "".join(chars)


def resolve_server_password(
    *,
    options_file: str | Path | None = None,
    state_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """Prefer an explicit Direct Connect password; otherwise generate a stable one."""

    env = environ if environ is not None else os.environ
    from_env = str(env.get("SERVER_PASSWORD") or "").strip()
    if from_env:
        if is_valid_server_password(from_env):
            return from_env
        _warn(
            "Ignoring invalid Core Keeper join password from SERVER_PASSWORD "
            f"({len(from_env)} chars; max {_PASSWORD_MAX})."
        )

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
            from_options = str(data.get("server_password") or "").strip()
            if from_options:
                if is_valid_server_password(from_options):
                    return from_options
                _warn(
                    "Ignoring invalid Core Keeper join password from "
                    f"options.server_password ({len(from_options)} chars; "
                    f"max {_PASSWORD_MAX})."
                )

    return default_server_password(state_dir=state_dir)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    what = (args[0] if args else "game-id").strip().lower().replace("_", "-")
    if what in {"password", "server-password"}:
        print(resolve_server_password())
    else:
        print(resolve_game_id())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
