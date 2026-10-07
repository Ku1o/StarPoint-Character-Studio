import copy
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from portrait_editor import (contract_report, render, resolve_mask, selection)
from studio_compile import compile_project
from studio_core import ProjectStore, StudioError, UI_SLOTS, image_from, png_bytes, project_checks, validate


class UiDeclarationRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-ui-declaration-")
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.p = self.store.create("UI 声明回归")
        image = Image.new("RGBA", (2000, 2000), (70, 120, 210, 255))
        image.putpixel((0, 0), (70, 120, 210, 0))
        self.source = png_bytes(image)
        self.aid = self.store.add_asset(self.p, "portrait.png", self.source)
        self.p["portraits"]["base"] = self.aid
        self.p["portraits"]["evolved"] = self.aid
        self.p.setdefault("uiImages", {})
        self.p.setdefault("uiDeclarations", {})
        self.store._write(self.p)

    def tearDown(self):
        self.temp.cleanup()

    def _crop(self, slot):
        width, height = UI_SLOTS[slot][1:]
        rect_width = 400.0
        rect_height = rect_width * height / width
        return {
            "mode": "crop", "asset": self.aid, "width": width, "height": height,
            "rect": {"x": 100.0, "y": 100.0, "width": rect_width, "height": rect_height},
            "mask": "none",
        }

    def test_base_and_evolved_declarations_override_old_specs_independently(self):
        self.p["uiImages"] = {
            "base:battle_control_board": {"mode": "image", "asset": self.aid, "mask": "none"},
            "evolved:battle_control_board": {"mode": "image", "asset": self.aid, "mask": "none"},
        }
        self.p["uiDeclarations"] = {
            "base:battle_control_board": {"autoCrop": True, "mask": "cone", "note": "基础技能栏"},
            "evolved:battle_control_board": {"autoCrop": True, "mask": "circle", "note": "进化技能栏"},
        }
        base = selection(self.p, "base", "battle_control_board")
        evolved = selection(self.p, "evolved", "battle_control_board")
        self.assertEqual(base["mask"], "cone")
        self.assertEqual(evolved["mask"], "circle")
        self.assertEqual(resolve_mask("battle_control_board", base), "control_board")
        self.assertEqual(resolve_mask("battle_control_board", evolved), "member_status")
        self.assertEqual(base["declarationNote"], "基础技能栏")
        self.assertEqual(evolved["declarationNote"], "进化技能栏")
        report = contract_report(self.store, self.p)
        rows = {row["key"]: row for row in report["slots"]}
        self.assertEqual(rows["base:battle_control_board"]["mask"], "control_board")
        self.assertEqual(rows["base:battle_control_board"]["requestedMask"], "cone")
        self.assertEqual(rows["base:battle_control_board"]["maskSource"], "declaration")
        self.assertEqual(rows["evolved:battle_control_board"]["mask"], "member_status")
        self.assertEqual(rows["evolved:battle_control_board"]["autoCrop"], True)
        self.assertEqual(rows["evolved:battle_control_board"]["autoCropSource"], "declaration")

    def test_empty_declaration_does_not_change_existing_internal_mask(self):
        self.p["uiImages"] = {
            "base:square_round_95_95": {
                "mode": "image", "asset": self.aid, "mask": "round_95", "autoCrop": False,
            }
        }
        self.p["uiDeclarations"] = {
            "base:square_round_95_95": {"autoCrop": "", "mask": "", "note": ""}
        }
        spec = selection(self.p, "base", "square_round_95_95")
        self.assertEqual(spec["mask"], "round_95")
        self.assertFalse(spec["autoCrop"])
        self.assertEqual(resolve_mask("square_round_95_95", spec), "round_95")

    def test_public_aliases_work_for_images_and_crops_without_mutating_source(self):
        aliases = (
            ("battle_control_board", "cone"),
            ("cutin_skill_chain", "hexagon"),
            ("battle_member_status", "circle"),
        )
        original = self.store.asset_bytes(self.p, self.aid)
        for slot, alias in aliases:
            key = "base:" + slot
            self.p["uiImages"][key] = {"mode": "image", "asset": self.aid, "mask": "none"}
            self.p["uiDeclarations"][key] = {"autoCrop": True, "mask": alias, "note": "official"}
            raw = render(self.store, self.p, "base", slot)
            self.assertEqual(image_from(raw).size, (2000, 2000))
            alpha = image_from(raw).getchannel("A")
            self.assertGreater(max(alpha.getdata()), 0)
            self.assertEqual(original, self.store.asset_bytes(self.p, self.aid))

        for slot, alias in aliases:
            key = "evolved:" + slot
            self.p["uiImages"][key] = self._crop(slot)
            self.p["uiDeclarations"][key] = {"autoCrop": True, "mask": alias, "note": "official crop"}
            raw = render(self.store, self.p, "evolved", slot)
            self.assertEqual(image_from(raw).size, UI_SLOTS[slot][1:])
            self.assertEqual(original, self.store.asset_bytes(self.p, self.aid))

    def test_auto_uses_slot_geometry_and_is_rendered(self):
        key = "base:battle_control_board"
        self.p["uiImages"][key] = {"mode": "image", "asset": self.aid, "mask": "none"}
        self.p["uiDeclarations"][key] = {"autoCrop": True, "mask": "auto", "note": "官方形状"}
        spec = selection(self.p, "base", "battle_control_board")
        self.assertEqual(resolve_mask("battle_control_board", spec), "control_board")
        image = image_from(render(self.store, self.p, "base", "battle_control_board"))
        self.assertEqual(image.getchannel("A").getpixel((0, 0)), 0)
        self.assertGreater(image.getchannel("A").getpixel((1000, 1000)), 0)

    def test_forbidden_crop_is_draft_saveable_but_contract_and_compile_block_it(self):
        key = "base:battle_control_board"
        self.p["uiImages"][key] = self._crop("battle_control_board")
        self.p["uiDeclarations"][key] = {
            "autoCrop": False, "mask": "cone", "note": "必须使用专用图"
        }
        saved = self.store.save(self.p)
        before = copy.deepcopy(saved)
        checks = project_checks(saved)
        self.assertFalse(checks["readiness"]["canCompile"])
        self.assertTrue(any(issue["code"] == "ui_contract_invalid" and issue["blocking"]
                            for issue in checks["issues"]))
        self.assertEqual(before, saved)
        report = contract_report(self.store, saved)
        self.assertTrue(any(key in problem and "禁止从母版自动裁切" in problem
                            for problem in report["problems"]))
        with self.assertRaisesRegex(StudioError, "禁止从母版自动裁切"):
            render(self.store, self.p, "base", "battle_control_board")
        self.store._write(self.p)
        with self.assertRaisesRegex(StudioError, "禁止从母版自动裁切"):
            compile_project(self.store, saved["id"])

    def test_check_report_blocks_ratio_conflict_and_recovers_after_dedicated_image(self):
        key = "base:battle_control_board"
        self.p["uiImages"][key] = self._crop("battle_control_board")
        self.p["uiImages"][key]["rect"]["height"] *= 2
        self.p["uiDeclarations"][key] = {"autoCrop": True, "mask": "none", "note": ""}
        saved = self.store.save(self.p)
        checks = project_checks(saved)
        self.assertFalse(checks["readiness"]["canCompile"])
        self.assertTrue(any("长宽比" in issue["summary"] for issue in checks["issues"]
                            if issue["code"] == "ui_contract_invalid"))
        with self.assertRaisesRegex(StudioError, "长宽比"):
            compile_project(self.store, saved["id"])
        saved["uiImages"][key] = {"mode": "image", "asset": self.aid, "mask": "none"}
        saved["uiDeclarations"][key]["autoCrop"] = False
        saved = self.store.save(saved)
        self.assertTrue(project_checks(saved)["readiness"]["canCompile"])
        self.assertEqual([], contract_report(self.store, saved)["problems"])

    def test_check_and_compile_share_small_canvas_mask_geometry_blocker(self):
        key = "base:square_round_95_95"
        self.p["uiImages"][key] = {
            "mode": "crop", "asset": self.aid, "width": 16, "height": 16,
            "rect": {"x": 0, "y": 0, "width": 16, "height": 16},
        }
        self.p["uiDeclarations"][key] = {"autoCrop": True, "mask": "auto", "note": ""}
        saved = self.store.save(self.p)
        before = copy.deepcopy(saved)
        pure = contract_report(None, saved)
        actual = contract_report(self.store, saved)
        self.assertEqual(pure["problems"], actual["problems"])
        self.assertTrue(any("填充率" in problem for problem in pure["problems"]))
        self.assertFalse(project_checks(saved)["readiness"]["canCompile"])
        with self.assertRaisesRegex(StudioError, "填充率"):
            compile_project(self.store, saved["id"])
        self.assertTrue(self.store.export(saved["id"]))
        self.assertEqual(before, saved)

    def test_forbidden_legacy_crop_is_reported_and_not_silently_allowed(self):
        key = "base:battle_control_board"
        self.p["crops"][key] = {"x": 0.5, "y": 0.5, "zoom": 1}
        self.p["uiDeclarations"][key] = {
            "autoCrop": False, "mask": "auto", "note": "专用图待补"
        }
        spec = selection(self.p, "base", "battle_control_board")
        self.assertTrue(spec["legacy"])
        self.assertFalse(spec["autoCrop"])
        self.assertFalse(project_checks(self.p)["readiness"]["canCompile"])
        report = contract_report(self.store, self.p)
        self.assertTrue(any(key in problem and "禁止从母版自动裁切" in problem
                            for problem in report["problems"]))
        with self.assertRaisesRegex(StudioError, "禁止从母版自动裁切"):
            render(self.store, self.p, "base", "battle_control_board")


if __name__ == "__main__":
    unittest.main()
