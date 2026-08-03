#!/usr/bin/env python3
"""Validate Home Assistant app (add-on) config.yaml files against Supervisor rules.

Catches the class of silent failures where Supervisor skips an app during store
reload because config validation failed (for example timeout > 300).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML required: apt/pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
RE_SLUG = re.compile(r"^(?!-)[a-z0-9_-]+(?<!-)$")
RE_WATCHDOG = re.compile(
    r"^(?:https?|\[PROTO:\w+\]|tcp):\/\/\[HOST\]:(\[PORT:\d+\]|\d+).*$"
)
ALLOWED_ARCH = {"aarch64", "amd64", "armhf", "armv7", "i386"}
CURRENT_ARCH = {"aarch64", "amd64"}
# Supervisor SCHEMA_APP_CONFIG: vol.Range(min=10, max=300)
TIMEOUT_MIN = 10
TIMEOUT_MAX = 300


def discover_configs(root: Path) -> list[Path]:
    configs: list[Path] = []
    for path in root.glob("**/config.yaml"):
        parts = path.parts
        if any(part.startswith(".") for part in parts):
            continue
        if "rootfs" in parts:
            continue
        configs.append(path)
    return sorted(configs)


def validate_config(path: Path) -> list[str]:
    errors: list[str] = []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return [f"{path}: root must be a mapping"]

    for key in ("name", "version", "slug", "description", "arch"):
        if key not in data:
            errors.append(f"{path}: missing required key '{key}'")

    slug = data.get("slug")
    if isinstance(slug, str) and not RE_SLUG.match(slug):
        errors.append(f"{path}: slug {slug!r} is not URI-friendly")

    arch = data.get("arch")
    if not isinstance(arch, list) or not arch:
        errors.append(f"{path}: arch must be a non-empty list")
    else:
        bad = [a for a in arch if a not in ALLOWED_ARCH]
        if bad:
            errors.append(f"{path}: unknown arch values: {bad}")
        deprecated = [a for a in arch if a not in CURRENT_ARCH]
        if deprecated:
            errors.append(
                f"{path}: deprecated arch values (recent HAOS may warn): {deprecated}"
            )

    if "timeout" in data:
        try:
            timeout = int(data["timeout"])
        except (TypeError, ValueError):
            errors.append(f"{path}: timeout must be an int")
        else:
            if timeout < TIMEOUT_MIN or timeout > TIMEOUT_MAX:
                errors.append(
                    f"{path}: timeout={timeout} outside Supervisor allowed "
                    f"range {TIMEOUT_MIN}-{TIMEOUT_MAX} (app would be hidden from store)"
                )

    watchdog = data.get("watchdog")
    if watchdog is not None and not RE_WATCHDOG.match(str(watchdog)):
        errors.append(f"{path}: watchdog URL does not match Supervisor pattern")

    options = data.get("options") or {}
    schema = data.get("schema") or {}
    if options and not isinstance(options, dict):
        errors.append(f"{path}: options must be a mapping")
    if schema not in (False, None) and not isinstance(schema, dict):
        errors.append(f"{path}: schema must be a mapping or false")
    if isinstance(options, dict) and isinstance(schema, dict):
        missing = sorted(set(options) - set(schema))
        if missing:
            errors.append(f"{path}: options missing from schema: {missing}")

    return errors


def main() -> int:
    configs = discover_configs(ROOT)
    # game-server-base must never present as an HA app.
    base_configs = [p for p in configs if "game-server-base" in p.parts]
    if base_configs:
        print("ERROR: game-server-base must not contain config.yaml:", file=sys.stderr)
        for path in base_configs:
            print(f"  {path}", file=sys.stderr)
        return 1

    if not configs:
        print("ERROR: no app config.yaml found", file=sys.stderr)
        return 1

    errors: list[str] = []
    for path in configs:
        errors.extend(validate_config(path))
        print(f"checked {path.relative_to(ROOT)}")

    if errors:
        print("\nValidation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"OK: {len(configs)} HA app config(s) valid; game-server-base not advertised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
