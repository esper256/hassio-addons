#!/usr/bin/env python3
"""Stationeers HA defaults (stable generated server name)."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "stationeers-dedicated-server" / "haos_defaults.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("haos_defaults", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StationeersHaosDefaultsTests(unittest.TestCase):
    def test_default_server_name_stable_per_install(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = mod.default_server_name(state_dir=state)
            second = mod.default_server_name(state_dir=state)
            self.assertEqual(first, second)
            self.assertRegex(first, r"^HAOS Stationeers \d{4}$")
            self.assertTrue((state / "instance_salt").is_file())

    def test_different_installs_get_different_digits(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            name_a = mod.default_server_name(state_dir=a)
            name_b = mod.default_server_name(state_dir=b)
            # Extremely unlikely collision across fresh salts; retry once if needed.
            if name_a == name_b:
                (Path(b) / "instance_salt").unlink()
                name_b = mod.default_server_name(state_dir=b)
            self.assertNotEqual(name_a, name_b)

    def test_resolve_prefers_options_then_env(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            options = root / "options.json"
            options.write_text('{"server_name": "Custom Base"}', encoding="utf-8")
            self.assertEqual(
                mod.resolve_server_name(
                    options_file=options,
                    state_dir=root / "state",
                    environ={},
                ),
                "Custom Base",
            )
            self.assertEqual(
                mod.resolve_server_name(
                    options_file=options,
                    state_dir=root / "state",
                    environ={"SERVER_NAME": "From Env"},
                ),
                "From Env",
            )
            options.write_text('{"server_name": ""}', encoding="utf-8")
            generated = mod.resolve_server_name(
                options_file=options,
                state_dir=root / "state",
                environ={},
            )
            self.assertRegex(generated, r"^HAOS Stationeers \d{4}$")


if __name__ == "__main__":
    unittest.main()
