"""Load settings from Home Assistant options.json and/or environment variables."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


OPTIONS_CANDIDATES = (
    Path("/data/options.json"),
    Path("/home/necesse/options.json"),  # legacy broken mapping support
)


@dataclass
class SupervisorConfig:
    """Runtime knobs for the generic supervisor."""

    # Update behaviour
    update_on_start: bool = True
    auto_update_interval_minutes: int = 30
    update_when_empty_only: bool = True
    update_on_version_mismatch: bool = True
    update_window_start_hour: int | None = None  # local hour 0-23, inclusive
    update_window_end_hour: int | None = None
    steamcmd_retries: int = 5
    steamcmd_retry_delay_seconds: int = 30

    # Process supervision
    restart_on_crash: bool = True
    crash_restart_delay_seconds: int = 5
    max_crash_restarts_per_hour: int = 10

    # Status HTTP
    status_http_enabled: bool = True
    status_http_host: str = "0.0.0.0"
    status_http_port: int = 8080

    # Backups
    backup_enabled: bool = True
    backup_interval_minutes: int = 180
    backup_retain: int = 10
    backup_dir: str = "/data/backups"
    backup_on_update: bool = True

    # Paths
    steamcmd_dir: str = "/opt/steamcmd"
    install_dir: str = "/opt/game"
    state_dir: str = "/data/supervisor"

    # Passthrough game options (everything else from options.json / env)
    game_options: dict[str, Any] = field(default_factory=dict)

    raw_options: dict[str, Any] = field(default_factory=dict)


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return default


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_options_file() -> Path | None:
    env_path = os.environ.get("OPTIONS_FILE") or os.environ.get("HASSIO_OPTIONS_FILE")
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    for candidate in OPTIONS_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def load_options_json(path: Path | None = None) -> dict[str, Any]:
    path = path or find_options_file()
    if path is None:
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except Exception as exc:  # noqa: BLE001 - surface parse problems clearly
        raise RuntimeError(f"Failed to parse options JSON at {path}: {exc}") from exc
    return {}


def _env_overrides() -> dict[str, Any]:
    """Allow plain Docker/Portainer env vars to override HA options."""

    keys = [
        "UPDATE_ON_START",
        "AUTO_UPDATE_INTERVAL_MINUTES",
        "UPDATE_WHEN_EMPTY_ONLY",
        "UPDATE_ON_VERSION_MISMATCH",
        "UPDATE_WINDOW_START_HOUR",
        "UPDATE_WINDOW_END_HOUR",
        "STEAMCMD_RETRIES",
        "STEAMCMD_RETRY_DELAY_SECONDS",
        "RESTART_ON_CRASH",
        "CRASH_RESTART_DELAY_SECONDS",
        "MAX_CRASH_RESTARTS_PER_HOUR",
        "STATUS_HTTP_ENABLED",
        "STATUS_HTTP_HOST",
        "STATUS_HTTP_PORT",
        "BACKUP_ENABLED",
        "BACKUP_INTERVAL_MINUTES",
        "BACKUP_RETAIN",
        "BACKUP_DIR",
        "BACKUP_ON_UPDATE",
        "STEAMCMD_DIR",
        "INSTALL_DIR",
        "STATE_DIR",
        # Common game options
        "WORLD_NAME",
        "SERVER_PASSWORD",
        "SERVER_SLOTS",
        "SERVER_PORT",
        "SERVER_OWNER",
        "SERVER_MOTD",
        "PAUSE_WHEN_EMPTY",
        "GIVE_CLIENTS_POWER",
        "ENABLE_LOGGING",
        "ZIP_SAVES",
        "SERVER_LANGUAGE",
        "BIND_IP",
        "MAX_CLIENT_LATENCY",
        "JAVA_OPTS",
        "SETTINGS_FILE",
        "DATA_DIR",
        "LOGS_DIR",
    ]
    out: dict[str, Any] = {}
    for key in keys:
        if key in os.environ:
            out[key.lower()] = os.environ[key]
    return out


def load_config() -> SupervisorConfig:
    options = load_options_json()
    # Normalize keys to snake_case lower
    normalized: dict[str, Any] = {}
    for key, value in options.items():
        norm = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
        normalized[norm] = value

    # Env wins over options.json for Portainer workflows
    normalized.update(_env_overrides())

    supervisor_keys = {
        "update_on_start",
        "auto_update_interval_minutes",
        "update_when_empty_only",
        "update_on_version_mismatch",
        "update_window_start_hour",
        "update_window_end_hour",
        "steamcmd_retries",
        "steamcmd_retry_delay_seconds",
        "restart_on_crash",
        "crash_restart_delay_seconds",
        "max_crash_restarts_per_hour",
        "status_http_enabled",
        "status_http_host",
        "status_http_port",
        "backup_enabled",
        "backup_interval_minutes",
        "backup_retain",
        "backup_dir",
        "backup_on_update",
        "steamcmd_dir",
        "install_dir",
        "state_dir",
    }

    game_options = {k: v for k, v in normalized.items() if k not in supervisor_keys}

    return SupervisorConfig(
        update_on_start=_as_bool(normalized.get("update_on_start"), True),
        auto_update_interval_minutes=_as_int(
            normalized.get("auto_update_interval_minutes"), 30
        ),
        update_when_empty_only=_as_bool(
            normalized.get("update_when_empty_only"), True
        ),
        update_on_version_mismatch=_as_bool(
            normalized.get("update_on_version_mismatch"), True
        ),
        update_window_start_hour=_as_optional_int(
            normalized.get("update_window_start_hour")
        ),
        update_window_end_hour=_as_optional_int(
            normalized.get("update_window_end_hour")
        ),
        steamcmd_retries=_as_int(normalized.get("steamcmd_retries"), 5),
        steamcmd_retry_delay_seconds=_as_int(
            normalized.get("steamcmd_retry_delay_seconds"), 30
        ),
        restart_on_crash=_as_bool(normalized.get("restart_on_crash"), True),
        crash_restart_delay_seconds=_as_int(
            normalized.get("crash_restart_delay_seconds"), 5
        ),
        max_crash_restarts_per_hour=_as_int(
            normalized.get("max_crash_restarts_per_hour"), 10
        ),
        status_http_enabled=_as_bool(normalized.get("status_http_enabled"), True),
        status_http_host=str(normalized.get("status_http_host") or "0.0.0.0"),
        status_http_port=_as_int(normalized.get("status_http_port"), 8080),
        backup_enabled=_as_bool(normalized.get("backup_enabled"), True),
        backup_interval_minutes=_as_int(
            normalized.get("backup_interval_minutes"), 180
        ),
        backup_retain=_as_int(normalized.get("backup_retain"), 10),
        backup_dir=str(normalized.get("backup_dir") or "/data/backups"),
        backup_on_update=_as_bool(normalized.get("backup_on_update"), True),
        steamcmd_dir=str(normalized.get("steamcmd_dir") or "/opt/steamcmd"),
        install_dir=str(normalized.get("install_dir") or "/opt/game"),
        state_dir=str(normalized.get("state_dir") or "/data/supervisor"),
        game_options=game_options,
        raw_options=normalized,
    )


def format_bool(value: Any, style: str) -> str:
    truthy = _as_bool(value, False)
    if style == "one_zero":
        return "1" if truthy else "0"
    return "true" if truthy else "false"
