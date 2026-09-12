"""Round trips for original action slots, directory batches and sprite sheets."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import ProjectStore, StudioError, fresh_project, png_bytes, image_from
from studio_compile import compiled_preview


class PixelWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-pixel-")
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.p = self.store.create("原创像素测试")

    def tearDown(self):
        self.temp.cleanup()

    def file(self, path, color, target=None, size=(6, 8), **extra):
        return {"name": Path(path).name, "path": path, "target": target,
                "data": base64.b64encode(png_bytes(Image.new("RGBA", size, color))).decode(), **extra}

    def test_new_original_has_honest_slots_and_template_preserves_own_actions(self):
        self.assertEqual(len(self.p["animations"]), 11)
        self.assertEqual(len({a["id"] for a in self.p["animations"]}), 11)
        self.assertTrue(all(not a["clips"] and a["purpose"] for a in self.p["animations"]))
        self.assertFalse(self.p["assets"])
        self.assertEqual(fresh_project(kind="template")["animations"], [])
        p = self.store.create("官方模板", "template")
        official = {"id": "officialextra", "name": "官方额外动作", "slot": "unique", "variant": "normal", "kind": "stop", "fps": 60, "frameScale": 6, "clips": []}
        p["animations"] = [official]
        self.store._write(p)
        result = self.store.add_action_presets(p["id"], p["revision"], ["neutral", "walk_front"])
        self.assertEqual(result["project"]["animations"][0], official)
        again = self.store.add_action_presets(p["id"], result["project"]["revision"], ["neutral", "walk_front"])
        self.assertEqual(again["ids"], [])

    def test_directory_batch_natural_order_export_and_compiled_frames(self):
        files = [self.file("新角色/待机/idle10.png", "blue", "preset:neutral"),
                 self.file("新角色/前进/walk2.png", "yellow", "preset:walk_front"),
                 self.file("新角色/待机/idle2.png", "green", "preset:neutral"),
                 self.file("新角色/待机/idle1.png", "red", "preset:neutral")]
        result = self.store.import_pixel_images(self.p["id"], {"revision": 0, "files": files, "hold": 4})
        self.assertEqual((result["frames"], result["animations"]), (4, 2))
        p = result["project"]
        idle = next(a for a in p["animations"] if a["slot"] == "neutral")
        walk = next(a for a in p["animations"] if a["slot"] == "walk_front")
        self.assertEqual([p["assets"][c["asset"]]["name"] for c in idle["clips"]], ["idle1.png", "idle2.png", "idle10.png"])
        self.assertEqual(walk["runtimeSpeed"], .5)
        restored = ProjectStore(Path(self.temp.name) / "restored")
        imported = restored.import_archive(self.store.export(p["id"]))
        self.assertEqual(imported["animations"], p["animations"])
        result = compiled_preview(restored, imported["id"], "animations", idle["id"])
        self.assertEqual(len(result["frames"]), 12)
        colors = []
        for tick in (0, 4, 8):
            data = result["assets"][result["frames"][tick][0]["asset"]]
            colors.append(image_from(base64.b64decode(data.split(",")[1])).getpixel((0, 0)))
        self.assertEqual(colors, [(255, 0, 0, 255), (0, 128, 0, 255), (0, 0, 255, 255)])

    def test_sheet_margin_gap_column_order_and_blank_frames_roundtrip(self):
        sheet = Image.new("RGBA", (12, 14))
        # 3x4 cells with a one-pixel gutter, starting at (2, 3).
        for xy, color in [((2, 3), "red"), ((6, 3), "green"), ((2, 8), "blue")]:
            sheet.paste(Image.new("RGBA", (3, 4), color), xy)
        item = {"name": "sheet.png", "target": "preset:neutral", "data": base64.b64encode(png_bytes(sheet)).decode(),
                "sheet": {"width": 3, "height": 4, "marginX": 2, "marginY": 3, "gapX": 1, "gapY": 1, "order": "column", "start": 1, "count": 3}}
        result = self.store.import_pixel_images(self.p["id"], {"revision": 0, "files": [item], "hold": 3})
        p = result["project"]
        idle = next(a for a in p["animations"] if a["slot"] == "neutral")
        self.assertEqual(len(idle["clips"]), 3)
        self.assertEqual([(c["x"], c["y"], c["hold"]) for c in idle["clips"]], [(-1.5, -4, 3)] * 3)
        cells = [image_from(self.store.asset_bytes(p, c["asset"])) for c in idle["clips"]]
        self.assertEqual([c.getpixel((0, 0)) for c in cells], [(0, 0, 255, 255), (0, 128, 0, 255), (0, 0, 0, 0)])
        self.assertEqual(len(compiled_preview(self.store, p["id"], "animations", idle["id"])["frames"]), 9)
        item["sheet"]["skipEmpty"] = True
        result = self.store.import_pixel_images(p["id"], {"revision": p["revision"], "files": [item], "hold": 3, "mode": "replace"})
        self.assertEqual(result["frames"], 2)

    def test_rejected_batch_has_no_partial_assets_or_replaced_frames(self):
        good = self.file("idle1.png", "red", "preset:neutral")
        result = self.store.import_pixel_images(self.p["id"], {"revision": 0, "files": [good]})
        before = self.store.export(self.p["id"])
        p = result["project"]
        on_disk = sorted(x.name for x in (self.store.directory(p["id"]) / "assets").iterdir())
        bad = self.file("idle2.png", "blue", "preset:neutral", size=(1023, 1))
        with self.assertRaisesRegex(StudioError, "网格切分"):
            self.store.import_pixel_images(p["id"], {"revision": p["revision"], "files": [self.file("idle0.png", "yellow", "preset:neutral"), bad], "mode": "replace"})
        self.assertEqual(before, self.store.export(p["id"]))
        self.assertEqual(on_disk, sorted(x.name for x in (self.store.directory(p["id"]) / "assets").iterdir()))
        with self.assertRaisesRegex(StudioError, "已更新"):
            self.store.import_pixel_images(p["id"], {"revision": 0, "files": [good]})
        with self.assertRaises(StudioError):
            self.store.import_pixel_images(p["id"], {"revision": p["revision"], "files": [self.file("../escape.png", "red")]})

    def test_inbox_and_replace_are_undoable_without_deleting_sources(self):
        result = self.store.import_pixel_images(self.p["id"], {"revision": 0, "files": [self.file("unassigned.png", "red")]})
        p = result["project"]
        self.assertEqual(result["inbox"], 1)
        self.assertEqual(result["animations"], 0)
        self.assertEqual(p["pixelInbox"], list(p["assets"]))
        result = self.store.import_pixel_images(p["id"], {"revision": p["revision"], "files": [self.file("idle.png", "blue", "preset:neutral")]})
        p = result["project"]
        before = p["animations"]
        result = self.store.import_pixel_images(p["id"], {"revision": p["revision"], "files": [self.file("new.png", "green", "preset:neutral")], "mode": "replace"})
        history = json.loads((self.store.directory(p["id"]) / "history" / f"{p['revision']:06}.json").read_text("utf-8"))
        self.assertEqual(history["animations"], before)
        self.assertEqual(len(result["project"]["assets"]), 3)


if __name__ == "__main__":
    unittest.main()
