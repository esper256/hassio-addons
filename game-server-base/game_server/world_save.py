"""Locate the active world save and backup roots from the game plugin.

Happy path: the plugin declares ``world_save.paths`` templates (named_path).
Backups use explicit ``backup_paths`` and are a separate concern from the
active-world artifact shown in the status UI.

Heuristic cross-game guessing lives in ``world_save_heuristic`` and is only
used when a plugin explicitly opts in.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .disk import path_total_bytes

LOG = logging.getLogger("game_server.world_save")

_TEMPLATE_KEY_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Strategies the plugin may declare.
STRATEGY_NAMED_PATH = "named_path"
STRATEGY_BACKUP_SOURCES = "backup_sources"
STRATEGY_HEURISTIC = "heuristic"

# Result scopes returned to status/UI.
SCOPE_NAMED_PATH = "named_path"
SCOPE_HEURISTIC = "heuristic"
SCOPE_BACKUP_SOURCES = "backup_sources"
SCOPE_MISSING = "missing"


@dataclass(frozen=True)
class WorldSaveSpec:
    """Plugin-owned description of how to find the active world save."""

    strategy: str = STRATEGY_NAMED_PATH
    # Path templates expanded with {data_dir}, {world_name}, and option keys.
    paths: list[str] = field(default_factory=list)
    world_name_option: str = "world_name"
    # Opt-in only. Never enable by default — see world_save_heuristic.py.
    allow_heuristic_fallback: bool = False

    @classmethod
    def from_dict(cls, data: Any) -> "WorldSaveSpec | None":
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValueError("world_save must be a mapping when provided")
        strategy = str(data.get("strategy") or STRATEGY_NAMED_PATH).strip().lower()
        if strategy not in {
            STRATEGY_NAMED_PATH,
            STRATEGY_BACKUP_SOURCES,
            STRATEGY_HEURISTIC,
        }:
            raise ValueError(
                f"Unsupported world_save.strategy {strategy!r}; "
                f"expected named_path, backup_sources, or heuristic"
            )
        paths = [str(p) for p in (data.get("paths") or []) if str(p).strip()]
        return cls(
            strategy=strategy,
            paths=paths,
            world_name_option=str(
                data.get("world_name_option") or "world_name"
            ).strip()
            or "world_name",
            allow_heuristic_fallback=bool(data.get("allow_heuristic_fallback", False)),
        )


@dataclass(frozen=True)
class ActiveWorld:
    """Resolved active world artifact (for size UI) — not the backup root list."""

    bytes: int
    path: str | None
    label: str | None
    scope: str
    sources: list[str] = field(default_factory=list)
    expected_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "bytes": self.bytes,
            "path": self.path,
            "label": self.label,
            "scope": self.scope,
            "sources": list(self.sources),
            "expected_paths": list(self.expected_paths),
        }
        return payload


def backup_sources_for(plugin: Any, data_dir: str | None = None) -> list[str]:
    """Explicit backup roots from the plugin (no guessing)."""

    root = str(data_dir or getattr(plugin, "data_dir", "") or "/data/world")
    configured = list(getattr(plugin, "backup_paths", None) or [])
    if configured:
        return [str(p) for p in configured]
    return [root]


def locate_active_world(
    plugin: Any,
    game_options: Mapping[str, Any] | None = None,
    *,
    data_dir: str | None = None,
) -> ActiveWorld:
    """Resolve the active world save using the plugin strategy.

    Order of preference inside this function:
    1. ``named_path`` templates from the plugin
    2. explicit ``heuristic`` strategy / opt-in heuristic fallback
    3. honest ``backup_sources`` sum (not presented as a named world file)
    """

    options = dict(game_options or {})
    root = str(data_dir or options.get("data_dir") or plugin.data_dir)
    sources = backup_sources_for(plugin, root)
    spec = getattr(plugin, "world_save", None)
    if spec is None:
        # No plugin declaration: do not guess paths. Sum backup roots only.
        return _from_backup_sources(sources)

    strategy = spec.strategy
    if strategy == STRATEGY_NAMED_PATH:
        found = _locate_named_path(spec, root, options)
        if found is not None:
            return found
        if spec.allow_heuristic_fallback:
            hack = _try_heuristic(root, _world_name(spec, options), sources)
            if hack is not None:
                return hack
        return _missing_named(spec, root, options, sources)

    if strategy == STRATEGY_HEURISTIC:
        hack = _try_heuristic(root, _world_name(spec, options), sources)
        if hack is not None:
            return hack
        return _from_backup_sources(sources) if _any_exists(sources) else ActiveWorld(
            bytes=0,
            path=None,
            label=None,
            scope=SCOPE_MISSING,
            sources=[],
            expected_paths=[],
        )

    # strategy == backup_sources (or unknown handled at parse time)
    return _from_backup_sources(sources)


def expand_world_path_template(
    template: str,
    *,
    data_dir: str,
    world_name: str,
    options: Mapping[str, Any],
) -> str | None:
    """Expand ``{data_dir}`` / ``{world_name}`` / option keys. None if a key is empty."""

    values: dict[str, str] = {
        str(k): _stringify_option(v) for k, v in options.items()
    }
    values["data_dir"] = data_dir
    values["world_name"] = world_name

    keys = _TEMPLATE_KEY_RE.findall(template)
    for key in keys:
        value = values.get(key)
        if value is None or value == "":
            return None

    def repl(match: re.Match[str]) -> str:
        return values[match.group(1)]

    return _TEMPLATE_KEY_RE.sub(repl, template)


def _stringify_option(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _world_name(spec: WorldSaveSpec, options: Mapping[str, Any]) -> str:
    return _stringify_option(options.get(spec.world_name_option))


def _locate_named_path(
    spec: WorldSaveSpec,
    data_dir: str,
    options: Mapping[str, Any],
) -> ActiveWorld | None:
    world_name = _world_name(spec, options)
    expected: list[str] = []
    for template in spec.paths:
        expanded = expand_world_path_template(
            template,
            data_dir=data_dir,
            world_name=world_name,
            options=options,
        )
        if not expanded:
            continue
        expected.append(expanded)
        path = Path(expanded)
        if path.is_file() or path.is_dir():
            return ActiveWorld(
                bytes=path_total_bytes(path),
                path=str(path),
                label=path.name,
                scope=SCOPE_NAMED_PATH,
                sources=[str(path)],
                expected_paths=expected,
            )
    return None


def _missing_named(
    spec: WorldSaveSpec,
    data_dir: str,
    options: Mapping[str, Any],
    backup_sources: list[str],
) -> ActiveWorld:
    world_name = _world_name(spec, options)
    expected: list[str] = []
    for template in spec.paths:
        expanded = expand_world_path_template(
            template,
            data_dir=data_dir,
            world_name=world_name,
            options=options,
        )
        if expanded:
            expected.append(expanded)
    label = Path(expected[0]).name if expected else (world_name or None)
    # Prefer reporting the intended artifact as missing over silently summing
    # the whole data dir (that would hide a misconfigured template).
    if expected:
        return ActiveWorld(
            bytes=0,
            path=expected[0],
            label=label,
            scope=SCOPE_MISSING,
            sources=[],
            expected_paths=expected,
        )
    if _any_exists(backup_sources):
        LOG.debug(
            "world_save named_path templates unresolved; using backup_sources for size"
        )
        return _from_backup_sources(backup_sources)
    return ActiveWorld(
        bytes=0,
        path=None,
        label=None,
        scope=SCOPE_MISSING,
        sources=[],
        expected_paths=[],
    )


def _from_backup_sources(sources: list[str]) -> ActiveWorld:
    total = 0
    existing: list[str] = []
    for raw in sources:
        path = Path(raw)
        if path.exists():
            total += path_total_bytes(path)
            existing.append(str(path))
    if not existing:
        return ActiveWorld(
            bytes=0,
            path=None,
            label=None,
            scope=SCOPE_MISSING,
            sources=[],
            expected_paths=[],
        )
    return ActiveWorld(
        bytes=total,
        path=existing[0] if len(existing) == 1 else None,
        label="world data",
        scope=SCOPE_BACKUP_SOURCES,
        sources=existing,
        expected_paths=[],
    )


def _any_exists(sources: list[str]) -> bool:
    return any(Path(p).exists() for p in sources)


def _try_heuristic(
    data_dir: str,
    world_name: str,
    backup_sources: list[str],
) -> ActiveWorld | None:
    # Imported lazily so happy-path callers never need this module.
    from . import world_save_heuristic

    return world_save_heuristic.heuristic_locate_world(
        data_dir,
        world_name,
        fallback_paths=backup_sources,
    )
