#!/usr/bin/env python3
"""Validate Home Assistant app config.yaml files against Supervisor rules.

Catches silent store failures where Supervisor skips an app during reload
because config validation failed (for example timeout > 300).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

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


class HaAppConfigTests(unittest.TestCase):
    def test_game_server_base_is_not_an_ha_app(self) -> None:
        base_configs = [
            p for p in discover_configs(ROOT) if "game-server-base" in p.parts
        ]
        self.assertEqual(
            base_configs,
            [],
            "game-server-base must not contain config.yaml "
            f"(found: {base_configs})",
        )

    def test_installable_app_configs_pass_supervisor_rules(self) -> None:
        configs = [
            p for p in discover_configs(ROOT) if "game-server-base" not in p.parts
        ]
        self.assertTrue(configs, "expected at least one installable HA app config.yaml")
        errors: list[str] = []
        for path in configs:
            errors.extend(validate_config(path))
        self.assertEqual(errors, [], "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
