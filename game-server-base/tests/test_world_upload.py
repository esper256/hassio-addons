#!/usr/bin/env python3
"""Tests for generic world upload restore (file vs directory kind)."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game_server.plugin import load_plugin  # noqa: E402
from game_server.world_save import (  # noqa: E402
    KIND_DIRECTORY,
    KIND_FILE,
    ActiveWorld,
    SCOPE_MISSING,
    SCOPE_NAMED_PATH,
    apply_world_upload,
    infer_world_kind,
    locate_active_world,
    world_upload_accepts,
)

FIXTURE = ROOT / "tests" / "fixtures" / "example.game.yaml"


class WorldUploadTests(unittest.TestCase):
    def test_infer_kind_from_path_name_and_live_path(self) -> None:
        self.assertEqual(infer_world_kind("World.zip"), KIND_FILE)
        self.assertEqual(infer_world_kind("World"), KIND_DIRECTORY)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "save.dat"
            file_path.write_bytes(b"abc")
            dir_path = root / "World"
            dir_path.mkdir()
            self.assertEqual(infer_world_kind(file_path), KIND_FILE)
            self.assertEqual(infer_world_kind(dir_path), KIND_DIRECTORY)

    def test_fixture_missing_prefers_zip_file_kind(self) -> None:
        plugin = load_plugin(FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "world"
            data.mkdir()
            active = locate_active_world(
                plugin,
                {"world_name": "FamilyWorld", "data_dir": str(data)},
                data_dir=str(data),
            )
            self.assertEqual(active.scope, SCOPE_MISSING)
            self.assertTrue(str(active.path).endswith("FamilyWorld.zip"))
            self.assertEqual(active.kind, KIND_FILE)
            meta = world_upload_accepts(active)
            self.assertTrue(meta["uploadable"])
            self.assertEqual(meta["mode"], "replace_file")

    def test_apply_upload_replaces_file_world_as_is(self) -> None:
        """When the game save IS a zip file, the upload replaces that file."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            target = data / "saves" / "worlds" / "FamilyWorld.zip"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"OLD-WORLD-ZIP")
            # Alternate folder sibling that should be removed.
            sibling = data / "saves" / "worlds" / "FamilyWorld"
            sibling.mkdir()
            (sibling / "chunk.bin").write_bytes(b"old")

            upload = root / "incoming.zip"
            upload.write_bytes(b"NEW-WORLD-ZIP-BYTES")

            active = ActiveWorld(
                bytes=target.stat().st_size,
                path=str(target),
                label=target.name,
                scope=SCOPE_NAMED_PATH,
                sources=[str(target)],
                expected_paths=[str(target), str(sibling)],
                kind=KIND_FILE,
            )
            result = apply_world_upload(active, upload, data_dir=data)
            self.assertEqual(result["mode"], "replace_file")
            self.assertEqual(target.read_bytes(), b"NEW-WORLD-ZIP-BYTES")
            self.assertFalse(sibling.exists())

    def test_apply_upload_extracts_into_directory_world(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            target = data / "saves" / "worlds" / "FamilyWorld"
            target.mkdir(parents=True)
            (target / "old.bin").write_bytes(b"OLD")

            upload = root / "folder-world.zip"
            with zipfile.ZipFile(upload, "w") as zf:
                zf.writestr("FamilyWorld/level.dat", b"LEVEL")
                zf.writestr("FamilyWorld/region/a.bin", b"REGION")

            active = ActiveWorld(
                bytes=1,
                path=str(target),
                label="FamilyWorld",
                scope=SCOPE_NAMED_PATH,
                sources=[str(target)],
                expected_paths=[str(target)],
                kind=KIND_DIRECTORY,
            )
            result = apply_world_upload(active, upload, data_dir=data)
            self.assertEqual(result["mode"], "extract_zip_into_directory")
            self.assertFalse((target / "old.bin").exists())
            self.assertEqual((target / "level.dat").read_bytes(), b"LEVEL")
            self.assertEqual((target / "region" / "a.bin").read_bytes(), b"REGION")

    def test_directory_world_rejects_non_zip_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "World"
            target.mkdir()
            upload = root / "not-a-zip.bin"
            upload.write_bytes(b"nope")
            active = ActiveWorld(
                bytes=1,
                path=str(target),
                label="World",
                scope=SCOPE_NAMED_PATH,
                sources=[str(target)],
                expected_paths=[str(target)],
                kind=KIND_DIRECTORY,
            )
            with self.assertRaises(RuntimeError) as ctx:
                apply_world_upload(active, upload, data_dir=root)
            self.assertIn("folder world save", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
