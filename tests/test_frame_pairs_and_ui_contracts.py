# -*- coding: utf-8 -*-
"""`_sp` 合成帧选择、官方模板键集与 UI 形状契约的回归测试。"""
from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import unittest
import zipfile
import zlib
import re
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import AMF3Reader  # noqa: E402
from studio_core import (ProjectStore, StudioError, image_from, png_bytes, validate,
                         declaration_payload, author_readme, project_checks,
                         animation_variant)  # noqa: E402
from studio_compile import (compile_pixelart, compile_pixelart_with_report,
                            compile_project, detect_frame_offset,
                            plan_pixel_frames, pixelart_timeline,
                            PIXELART_TIMELINE_TEMPLATE)  # noqa: E402
import portrait_editor as portrait  # noqa: E402
import pixel_import  # noqa: E402


def frame(color, size=(8, 8), marks=()):
    image = Image.new("RGBA", size, color)
    for xy, value in marks:
        image.putpixel(xy, value)
    return image


class FramePairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-frame-pair-")
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.p = self.store.create("合成帧测试")
        # 纯本体 13×13；合成帧 37×25，纯本体精确位于 (12,12)。
        plain = frame((0, 0, 0, 0), (13, 13), [((3, 3), (255, 0, 0, 255))])
        composite = Image.new("RGBA", (37, 25), (0, 0, 0, 0))
        composite.paste(plain, (12, 12))
        composite.putpixel((0, 0), (0, 255, 0, 255))
        composite.putpixel((36, 24), (0, 255, 0, 255))
        self.plain_aid = self.store.add_asset(self.p, "neutral_001.png", png_bytes(plain), "pixel")
        self.composite_aid = self.store.add_asset(self.p, "neutral_001_sp.png", png_bytes(composite), "pixel")
        self.p["animations"] = [
            {"id": "a1", "name": "待机", "slot": "neutral", "variant": "normal",
             "kind": "loop", "fps": 60, "frameScale": 6,
             "clips": [{"asset": self.composite_aid, "hold": 4, "x": -6, "y": -12,
                        "flip": False, "rotation": 0, "scale": 1, "opacity": 1}]},
            {"id": "a2", "name": "技能准备", "slot": "skill_ready", "variant": "normal",
             "kind": "once", "fps": 60, "frameScale": 6,
             "clips": [{"asset": self.plain_aid, "hold": 4, "x": -6, "y": -12,
                        "flip": False, "rotation": 0, "scale": 1, "opacity": 1}]},
        ]
        self.store._write(self.p)

    def tearDown(self):
        self.temp.cleanup()

    def test_detect_offset_is_exact_and_unique(self):
        plain = image_from(self.store.asset_bytes(self.p, self.plain_aid))
        composite = image_from(self.store.asset_bytes(self.p, self.composite_aid))
        offset, matches = detect_frame_offset(plain, composite)
        self.assertEqual((12, 12), offset)
        self.assertEqual(1, matches)
        offset, matches = detect_frame_offset(plain, plain)
        self.assertEqual((0, 0), offset)
        blank = frame((0, 0, 0, 0), (13, 13))
        offset, matches = detect_frame_offset(blank, composite)
        self.assertIsNone(offset)
        self.assertGreater(matches, 1)

    def test_base_state_swaps_to_plain_and_skill_state_keeps_composite(self):
        plan, report = plan_pixel_frames(self.store, self.p, self.p["animations"], "normal")
        self.assertIn(("a1", 0), plan)
        asset_id, dx, dy = plan[("a1", 0)]
        self.assertEqual(self.plain_aid, asset_id)
        self.assertEqual((12, 12), (dx, dy))
        # 技能状态：clip 引用纯本体 -> 切到合成帧并反向补偿
        self.assertIn(("a2", 0), plan)
        asset_id, dx, dy = plan[("a2", 0)]
        self.assertEqual(self.composite_aid, asset_id)
        self.assertEqual((-12, -12), (dx, dy))
        self.assertEqual(2, len(report["swaps"]))

    def test_compiled_atlas_uses_client_semantics(self):
        files, sequences, report = compile_pixelart_with_report(
            self.store, self.p, self.p["animations"], "normal", "pair_test")
        atlas = AMF3Reader(zlib.decompress(next(
            v for k, v in files.items() if k.endswith(".atlas.amf3.deflate")), -15)).read_value()
        by_end = {int(re.search(r"(\d+)$", record["n"]).group(1)): record
                  for record in atlas}
        # 客户端语义：区域左上角 = (-fx,-fy)，画布原点 = frame.x/y = -128。
        # a1: 合成帧 x=-6 -> 纯本体画在 (-6+12, -12+12)=(6,0)
        self.assertEqual((6, 0), (-by_end[4]["fx"] - 128, -by_end[4]["fy"] - 128))
        # a2: 纯本体 x=-6 -> 合成帧画在 (-6-12, -12-12)=(-18,-24)
        self.assertEqual((-18, -24), (-by_end[8]["fx"] - 128, -by_end[8]["fy"] - 128))
        receipts = [item for item in report["slots"] if item["slot"] == "skill_ready"]
        self.assertEqual(1, receipts[0]["swapped"])

    def test_unverifiable_pair_keeps_base_state_fail_closed(self):
        # 合成帧与纯本体没有任何包含关系 -> 基础状态必须失败关闭
        other = frame((1, 2, 3, 255), (13, 13))
        aid = self.store.add_asset(self.p, "neutral_002_sp.png", png_bytes(other), "pixel")
        self.store.add_asset(self.p, "neutral_002.png",
                             png_bytes(frame((9, 9, 9, 255), (13, 13))), "pixel")
        self.p["animations"][0]["clips"][0]["asset"] = aid
        self.store._write(self.p)
        with self.assertRaisesRegex(StudioError, "无法证明"):
            plan_pixel_frames(self.store, self.p, self.p["animations"], "normal")

    def test_transformed_base_clip_is_rejected(self):
        self.p["animations"][0]["clips"][0]["flip"] = True
        self.store._write(self.p)
        with self.assertRaisesRegex(StudioError, "翻转"):
            plan_pixel_frames(self.store, self.p, self.p["animations"], "normal")

    def test_pixelart_timeline_template_is_deepcopied_and_checked(self):
        timeline = pixelart_timeline([])
        self.assertEqual(sorted(PIXELART_TIMELINE_TEMPLATE), sorted(timeline))
        self.assertEqual([], timeline["sounds"])
        timeline["points"].append({"x": 1})
        self.assertEqual([], pixelart_timeline([])["points"])


class UiShapeContractTests(unittest.TestCase):
    def test_shape_masks_match_official_geometry(self):
        sizes = {shape: portrait.UI_SLOTS[slot][1:]
                 for slot, shape in portrait.SLOT_SHAPES.items()}
        self.assertEqual(set(portrait.SHAPE_MASKS), set(sizes))
        for key, size in sizes.items():
            mask = portrait.shape_mask_image(key, size)
            self.assertEqual(size, mask.size)
            coverage = sum(1 for value in mask.getdata() if value > 127) / (size[0] * size[1])
            official = portrait.OFFICIAL_FILL[key]
            self.assertLess(abs(coverage - official), 0.03, key)

    def test_shape_masking_zeroes_alpha_outside_and_keeps_center(self):
        image = Image.new("RGBA", (104, 268), (255, 0, 0, 255))
        result = portrait.apply_shape_mask(image, "control_board")
        alpha = result["image"].getchannel("A")
        self.assertEqual(0, alpha.getpixel((0, 0)))
        self.assertEqual(0, alpha.getpixel((103, 267)))
        self.assertGreater(alpha.getpixel((52, 134)), 0)
        problems = portrait.validate_shape_output("control_board", result["image"])
        self.assertEqual([], problems)

    def test_crop_ratio_contract_rejects_letterboxing(self):
        p = {"assets": {"x": {"mime": "image/png"}}, "portraits": {}, "uiImages": {}}
        spec = {"mode": "crop", "asset": "x", "width": 212, "height": 212,
                "rect": {"x": 0, "y": 0, "width": 300, "height": 200}, "mask": "none"}
        with self.assertRaisesRegex(StudioError, "0.3%"):
            portrait.validate_selection(p, spec)
        good = dict(spec, rect={"x": 0, "y": 0, "width": 212.2, "height": 212})
        portrait.validate_selection(p, good)
        legacy = dict(spec, legacy=True)
        portrait.validate_selection(p, legacy)

    def test_declared_cone_mask_is_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProjectStore(Path(tmp) / "projects")
            p = store.create("遮罩测试")
            master = png_bytes(Image.new("RGBA", (104, 268), (10, 20, 30, 255)))
            aid = store.add_asset(p, "立绘.png", master)
            p["portraits"]["base"] = aid
            p["uiImages"] = {"base:battle_control_board": {
                "mode": "image", "asset": aid, "mask": "auto"}}
            store._write(p)
            raw = portrait.render(store, p, "base", "battle_control_board")
            image = image_from(raw)
            self.assertEqual((104, 268), image.size)
            self.assertEqual(0, image.getchannel("A").getpixel((0, 0)))
            self.assertGreater(image.getchannel("A").getpixel((52, 134)), 0)


class DeclarationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-declaration-")
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.p = self.store.create("声明测试")
        self.plain = self.store.add_asset(self.p, "idle1.png", png_bytes(frame((1, 2, 3, 255))), "pixel")
        self.composite = self.store.add_asset(
            self.p, "idle1_sp.png", png_bytes(frame((1, 2, 3, 255))), "pixel")
        self.p["animations"] = [
            {"id": "a1", "name": "待机", "slot": "neutral", "variant": "normal",
             "kind": "loop", "fps": 60, "frameScale": 6,
             "clips": [{"asset": self.composite, "hold": 4, "x": 0, "y": 0,
                        "flip": False, "rotation": 0, "scale": 1, "opacity": 1}]},
            {"id": "a2", "name": "获取·登场", "slot": "special_land", "variant": "special",
             "kind": "pass", "fps": 60, "frameScale": 6,
             "clips": [{"asset": self.composite, "hold": 4, "x": 0, "y": 0,
                        "flip": False, "rotation": 0, "scale": 1, "opacity": 1}]},
        ]
        self.store._write(self.p)

    def tearDown(self):
        self.temp.cleanup()

    def test_project_checks_report_composite_base_state(self):
        p = self.store.load(self.p["id"])
        result = project_checks(p)
        warnings = [issue for issue in result["issues"]
                    if issue["level"] == "warning" and "基础状态" in issue["text"]]
        self.assertTrue(warnings, result["issues"])
        self.assertIn("位置：", warnings[0]["text"])
        self.assertIn("改法：", warnings[0]["text"])
        todos = [issue for issue in result["issues"] if "尚未说明是否带召唤物" in issue["text"]]
        self.assertTrue(todos)

    def test_declaring_companions_clears_the_warning(self):
        p = self.store.load(self.p["id"])
        p["animations"][0]["includesCompanion"] = True
        p["animations"][1]["includesCompanion"] = True
        p["animations"][0]["companionNote"] = "基础态不带，仅测试标记"
        validate(p)
        result = project_checks(p)
        self.assertFalse([issue for issue in result["issues"]
                          if issue["level"] == "warning" and "基础状态" in issue["text"]])

    def test_declaration_payload_and_readme_are_exported(self):
        p = self.store.load(self.p["id"])
        payload = declaration_payload(p)
        self.assertEqual("composite", payload["animations"][0]["variant"])
        self.assertEqual("", payload["animations"][0]["includesCompanion"])
        readme = author_readme(p)
        self.assertIn("动作清单", readme)
        self.assertIn("未标注项清单", readme)
        archive = self.store.export(p["id"])
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            names = z.namelist()
            self.assertIn("README-稿主必读.md", names)
            self.assertIn("declarations.json", names)
            self.assertEqual("composite", json.loads(
                z.read("declarations.json").decode("utf-8"))["animations"][0]["variant"])

    def test_pixel_import_returns_companion_notice(self):
        request = {"revision": self.p["revision"], "hold": 4, "files": [
            {"name": "walk_001.png", "path": "新角色/前进/walk_001.png",
             "target": "preset:walk_front",
             "data": base64.b64encode(png_bytes(frame((9, 9, 9, 255)))).decode()},
            {"name": "walk_001_sp.png", "path": "新角色/前进/walk_001_sp.png",
             "target": "preset:walk_front",
             "data": base64.b64encode(png_bytes(frame((8, 8, 8, 255)))).decode()},
        ]}
        result = pixel_import.import_images(self.store, self.p["id"], request)
        self.assertEqual({"plain": 1, "composite": 1}, result["variantCounts"])
        self.assertIsNotNone(result["companionNotice"])
        self.assertEqual(1, result["companionNotice"]["pairs"])
        self.assertIn("walk_front", result["companionNotice"]["base_state_targets"])
        project = result["project"]
        variants = {asset.get("variant") for asset in project["assets"].values()}
        self.assertIn("composite", variants)


if __name__ == "__main__":
    unittest.main()
