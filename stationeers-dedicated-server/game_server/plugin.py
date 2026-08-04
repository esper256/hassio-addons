"""Game plugin definitions loaded from YAML/JSON files."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .world_save import WorldSaveSpec


@dataclass
class LogPatterns:
    """Regex patterns used to interpret game server log output."""

    player_join: list[str] = field(default_factory=list)
    player_leave: list[str] = field(default_factory=list)
    version_mismatch: list[str] = field(default_factory=list)
    player_count: list[str] = field(default_factory=list)
    ready: list[str] = field(default_factory=list)
    # Human-readable game/server version (e.g. "1.3.1"), not Steam build ids.
    game_version: list[str] = field(default_factory=list)

    def compiled(self, key: str) -> list[re.Pattern[str]]:
        return [re.compile(p, re.IGNORECASE) for p in getattr(self, key)]


@dataclass
class GamePlugin:
    """Describes how to install and run one Steam dedicated server."""

    name: str
    steam_app_id: int
    working_dir: str
    executable: list[str]
    data_dir: str
    logs_dir: str
    install_marker: str
    backup_paths: list[str] = field(default_factory=list)
    steam_branch: str = "public"
    steam_login: str = "anonymous"
    steam_password: str = ""
    # Optional SteamCMD platform pin (e.g. "linux"). Empty = host-native depots.
    steam_platform: str = ""
    validate_on_update: bool = True
    env: dict[str, str] = field(default_factory=dict)
    # Simple option_key → CLI flag pairs (``-flag value`` or ``-flag=value``).
    arg_map: dict[str, str] = field(default_factory=dict)
    # Ordered argv tokens after the executable. Supports ``{option_key}``
    # templates; empty renderings are omitted (handy for optional tokens).
    argv_prefix: list[str] = field(default_factory=list)
    # Optional ``-settings Key Value Key Value …`` style block (Unity / etc.).
    # When settings_flag is set, fixed_settings then settings_map are appended.
    settings_flag: str = ""
    # SettingName → literal/template value (always attempted).
    fixed_settings: dict[str, str] = field(default_factory=dict)
    # option_key → SettingName (skip when the option is empty).
    settings_map: dict[str, str] = field(default_factory=dict)
    bool_style: str = "true_false"  # or "one_zero"
    log_patterns: LogPatterns = field(default_factory=LogPatterns)
    # Optional extra dry-run candidates merged with generic defaults.
    log_pattern_candidates: dict[str, list[str]] = field(default_factory=dict)
    ready_timeout_seconds: int = 180
    java_opts_env: str = "JAVA_OPTS"
    stop_timeout_seconds: int = 60
    stop_stdin_commands: list[str] = field(default_factory=list)
    min_backup_bytes: int = 1024
    # Optional runtime packages hint for image authors (documentation only).
    runtime_notes: str = ""
    # How to find the active world artifact for status UI (not backup roots).
    world_save: WorldSaveSpec | None = None
    # Optional Ingress status page CSS color overrides (see status_http.DEFAULT_UI_THEME).
    ui_theme: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GamePlugin":
        patterns = data.get("log_patterns") or {}
        raw_candidates = data.get("log_pattern_candidates") or {}
        candidates: dict[str, list[str]] = {}
        if isinstance(raw_candidates, dict):
            for key, values in raw_candidates.items():
                candidates[str(key)] = [str(v) for v in (values or [])]
        install_marker = data.get("install_marker")
        if not install_marker:
            raise ValueError("Game plugin requires install_marker")
        return cls(
            name=data["name"],
            steam_app_id=int(data["steam_app_id"]),
            working_dir=data.get("working_dir", "/data/game"),
            executable=list(data["executable"]),
            data_dir=data.get("data_dir", "/data/world"),
            logs_dir=data.get("logs_dir", "/data/logs"),
            install_marker=str(install_marker),
            backup_paths=list(
                data.get("backup_paths") or [data.get("data_dir", "/data/world")]
            ),
            steam_branch=data.get("steam_branch", "public"),
            steam_login=data.get("steam_login", "anonymous"),
            steam_password=data.get("steam_password", ""),
            steam_platform=str(data.get("steam_platform") or "").strip().lower(),
            validate_on_update=bool(data.get("validate_on_update", True)),
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
            arg_map={str(k): str(v) for k, v in (data.get("arg_map") or {}).items()},
            argv_prefix=[str(x) for x in (data.get("argv_prefix") or [])],
            settings_flag=str(data.get("settings_flag") or "").strip(),
            fixed_settings={
                str(k): str(v)
                for k, v in (data.get("fixed_settings") or {}).items()
            },
            settings_map={
                str(k): str(v) for k, v in (data.get("settings_map") or {}).items()
            },
            bool_style=data.get("bool_style", "true_false"),
            log_patterns=LogPatterns(
                player_join=list(patterns.get("player_join") or []),
                player_leave=list(patterns.get("player_leave") or []),
                version_mismatch=list(patterns.get("version_mismatch") or []),
                player_count=list(patterns.get("player_count") or []),
                ready=list(patterns.get("ready") or []),
                game_version=list(patterns.get("game_version") or []),
            ),
            log_pattern_candidates=candidates,
            ready_timeout_seconds=int(data.get("ready_timeout_seconds", 180)),
            java_opts_env=data.get("java_opts_env", "JAVA_OPTS"),
            stop_timeout_seconds=int(data.get("stop_timeout_seconds", 60)),
            stop_stdin_commands=[
                str(x) for x in (data.get("stop_stdin_commands") or [])
            ],
            min_backup_bytes=int(data.get("min_backup_bytes", 1024)),
            runtime_notes=str(data.get("runtime_notes") or ""),
            world_save=WorldSaveSpec.from_dict(data.get("world_save")),
            ui_theme=_coerce_ui_theme(data.get("ui_theme")),
        )


def _coerce_ui_theme(raw: Any) -> dict[str, str]:
    """Keep only non-empty string color values from game.yaml ``ui_theme``."""

    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip().lower()
        if not name or not isinstance(value, str):
            continue
        color = value.strip()
        if color:
            out[name] = color
    return out


def _parse_plugin_text(text: str, suffix: str) -> dict[str, Any]:
    stripped = text.lstrip()
    if suffix == ".json" or stripped.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise RuntimeError("Plugin JSON root must be an object")
        return data

    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyYAML is required for .yaml game plugins. Install python3-yaml."
        ) from exc

    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise RuntimeError("Plugin YAML root must be a mapping")
    return loaded


def load_plugin(path: str | Path) -> GamePlugin:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Game plugin not found: {path}")

    text = path.read_text(encoding="utf-8")
    data = _parse_plugin_text(text, path.suffix.lower())
    return GamePlugin.from_dict(data)


def resolve_plugin_path(explicit: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("GAME_PLUGIN")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path("/opt/games/game.yaml"),
            Path("/opt/games/game.json"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "No game plugin found. Set GAME_PLUGIN to a plugin YAML/JSON path "
        "(for example /opt/games/game.yaml)."
    )
