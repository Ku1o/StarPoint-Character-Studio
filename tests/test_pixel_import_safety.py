"""Regression for source identity and atomic author pixel intake."""
import base64
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pixel_import import import_images, source_identity
from studio_core import ProjectStore, StudioError, png_bytes


class PixelImportSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pixel-safety-")
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.project = self.store.create("Source identity")
        image = Image.new("RGBA", (4, 4), (40, 70, 90, 255))
        self.image = base64.b64encode(png_bytes(image)).decode("ascii")

    def tearDown(self):
        self.temp.cleanup()

    def item(self, path, target=""):
        return {"name": Path(path).name, "path": path, "target": target, "data": self.image}

    def import_batch(self, files, **options):
        p = self.store.load(self.project["id"])
        return import_images(self.store, p["id"], {"revision": p["revision"], "files": files, **options})

    def test_source_groups_pair_only_with_same_path_action_and_number(self):
        plain = source_identity("author/walk_front/walk_001.png")
        composite = source_identity("author/walk_front/walk_001_sp.png")
        other = source_identity("author/walk_back/walk_001_sp.png")
        self.assertEqual("plain", plain["variant"])
        self.assertEqual("composite", composite["variant"])
        self.assertEqual(plain["pairKey"], composite["pairKey"])
        self.assertNotEqual(plain["pairKey"], other["pairKey"])
        self.assertEqual("unknown", source_identity("author/unlabeled.png")["variant"])

    def test_equal_pixels_in_different_sources_never_merge_metadata(self):
        result = self.import_batch([
            self.item("author/neutral/idle_001.png"),
            self.item("author/neutral/idle_001_sp.png"),
        ])
        self.assertEqual({"plain": 1, "composite": 1, "unknown": 0}, result["variantCounts"])
        self.assertEqual(1, result["companionNotice"]["pairs"])
        assets = result["project"]["assets"]
        self.assertEqual(2, len(assets))
        self.assertEqual(1, len({a["sha256"] for a in assets.values()}))
        self.assertEqual({"plain", "composite"}, {a["variant"] for a in assets.values()})
        self.assertEqual(2, len({a["sourceName"] for a in assets.values()}))

    def test_filter_applies_to_actual_persisted_assets(self):
        result = self.import_batch([
            self.item("author/neutral/idle_001.png"),
            self.item("author/neutral/idle_001_sp.png"),
        ], filter="plain")
        self.assertEqual(1, result["frames"])
        self.assertEqual(1, result["excludedFiles"])
        self.assertEqual({"plain"}, {a["variant"] for a in result["project"]["assets"].values()})

    def test_base_composite_requires_group_note_and_does_not_partially_write(self):
        files = [self.item("author/neutral/idle_001.png", "preset:neutral"),
                 self.item("author/neutral/idle_001_sp.png", "preset:neutral")]
        before = self.store.load(self.project["id"])
        with self.assertRaisesRegex(StudioError, "基础状态"):
            self.import_batch(files)
        self.assertEqual(before, self.store.load(self.project["id"]))
        result = self.import_batch(files, companionConfirmations={"preset:neutral": "全程带附属物"})
        self.assertEqual(2, result["frames"])
        animation = next(a for a in result["project"]["animations"] if a["slot"] == "neutral")
        self.assertIs(True, animation["includesCompanion"])
        self.assertEqual("全程带附属物", animation["companionNote"])
        self.assertEqual({"plain", "composite"}, {result["project"]["assets"][c["asset"]]["variant"]
                                                  for c in animation["clips"]})

    def test_rejects_native_directory_and_path_traversal(self):
        for path in ("author/native_effect/flash.png", "../escape.png"):
            with self.subTest(path=path), self.assertRaises(StudioError):
                self.import_batch([self.item(path)])
        self.assertEqual({}, self.store.load(self.project["id"])["assets"])


if __name__ == "__main__":
    unittest.main()
