"""Game plugin definitions loaded from YAML-like JSON/YAML files."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LogPatterns:
    """Regex patterns used to interpret game server log output."""

    player_join: list[str] = field(default_factory=list)
    player_leave: list[str] = field(default_factory=list)
    version_mismatch: list[str] = field(default_factory=list)
    player_count: list[str] = field(default_factory=list)
    ready: list[str] = field(default_factory=list)

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
    install_marker: str = "Server.jar"
    backup_paths: list[str] = field(default_factory=list)
    steam_branch: str = "public"
    steam_login: str = "anonymous"
    steam_password: str = ""
    validate_on_update: bool = True
    env: dict[str, str] = field(default_factory=dict)
    arg_map: dict[str, str] = field(default_factory=dict)
    bool_style: str = "true_false"  # or "one_zero"
    log_patterns: LogPatterns = field(default_factory=LogPatterns)
    ready_timeout_seconds: int = 180
    java_opts_env: str = "JAVA_OPTS"
    stop_timeout_seconds: int = 60
    stop_stdin_commands: list[str] = field(default_factory=list)
    min_backup_bytes: int = 1024

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GamePlugin":
        patterns = data.get("log_patterns") or {}
        return cls(
            name=data["name"],
            steam_app_id=int(data["steam_app_id"]),
            working_dir=data.get("working_dir", "/data/game"),
            executable=list(data["executable"]),
            data_dir=data.get("data_dir", "/data/world"),
            logs_dir=data.get("logs_dir", "/data/logs"),
            install_marker=data.get("install_marker", "Server.jar"),
            backup_paths=list(data.get("backup_paths") or [data.get("data_dir", "/data/world")]),
            steam_branch=data.get("steam_branch", "public"),
            steam_login=data.get("steam_login", "anonymous"),
            steam_password=data.get("steam_password", ""),
            validate_on_update=bool(data.get("validate_on_update", True)),
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
            arg_map={str(k): str(v) for k, v in (data.get("arg_map") or {}).items()},
            bool_style=data.get("bool_style", "true_false"),
            log_patterns=LogPatterns(
                player_join=list(patterns.get("player_join") or []),
                player_leave=list(patterns.get("player_leave") or []),
                version_mismatch=list(patterns.get("version_mismatch") or []),
                player_count=list(patterns.get("player_count") or []),
                ready=list(patterns.get("ready") or []),
            ),
            ready_timeout_seconds=int(data.get("ready_timeout_seconds", 180)),
            java_opts_env=data.get("java_opts_env", "JAVA_OPTS"),
            stop_timeout_seconds=int(data.get("stop_timeout_seconds", 60)),
            stop_stdin_commands=[str(x) for x in (data.get("stop_stdin_commands") or [])],
            min_backup_bytes=int(data.get("min_backup_bytes", 1024)),
        )


def _parse_plugin_text(text: str, suffix: str) -> dict[str, Any]:
    stripped = text.lstrip()
    if suffix == ".json" or stripped.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise RuntimeError("Plugin JSON root must be an object")
        return data

    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - image always installs PyYAML
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
            Path("/opt/games/necesse.yaml"),
            Path(__file__).resolve().parent.parent / "games" / "necesse.yaml",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "No game plugin found. Set GAME_PLUGIN or place a file in /opt/games/."
    )
