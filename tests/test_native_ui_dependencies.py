import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import encode_amf3
import native_ui_dependencies as ui


def compress(value):
    compressor = zlib.compressobj(wbits=-15)
    return compressor.compress(value) + compressor.flush()


def layout(name, **groups):
    children = {key: [] for key in ("bitmaps", "texts", "containers", "guides", "components")}
    children.update(groups)
    return {"id": name, "children": children}


def bitmap(kind="simple", path="scene/general/sprite_sheet/icon"):
    return {"name": "icon", "attributes": {"kind": kind, "path": path}, "frames": []}


def container(target):
    return {"name": "child", "attributes": {"layout_id": target}, "frames": []}


def decode(data, **kwargs):
    return ui.resolve_ui_resources("scene/example.ui.json", json.dumps(data).encode(), **kwargs)


def html(value):
    return ui.resolve_ui_resources("rich_text/example.html.deflate", compress(value.encode()), "html")


class NativeUiDependenciesTests(unittest.TestCase):
    def test_physical_suffixes_follow_current_reader(self):
        self.assertEqual(ui.physical_path("scene/battle/pause_menu", "ui"), "scene/battle/pause_menu.ui.amf3.deflate")
        self.assertEqual(ui.physical_path("scene/example", "ui", True), "scene/example.ui.json")
        self.assertEqual(ui.physical_path("rich_text/example", "html"), "rich_text/example.html.deflate")
        self.assertEqual(ui.physical_path("rich_text/example", "html", True), "rich_text/example.html")

    def test_all_three_image_kinds_read_exact_texture_but_dummy_has_no_fake_file(self):
        data = {"layouts": [layout("main", bitmaps=[bitmap(k, "scene/a/" + k) for k in ("simple", "slice", "fill", "dummy")])], "timelines": {}}
        before = copy.deepcopy(data)
        result = decode(data, context={"role": "unison", "bucket": "FollowingLogic", "collection": "prior"})
        self.assertEqual(data, before)
        self.assertEqual([r["logical"] for r in result["references"]], ["scene/a/" + k for k in ("simple", "slice", "fill")])
        for index, ref in enumerate(result["references"]):
            self.assertEqual(ref["pointer"], f"/layouts/0/children/bitmaps/{index}/attributes/path")
            self.assertEqual(ref["lookup"], "exact-texture")
            self.assertEqual(ref["context"]["kind"], "texture")
            self.assertEqual(ref["context"]["role"], "unison")
            self.assertEqual(ref["context"]["collection"], "common-view-ui-textures")
            self.assertEqual(ref["context"]["bucket"], "Common")
        self.assertTrue(any("dummy" in p["reason"] for p in result["problems"]))
        self.assertFalse(result["complete"])

    def test_blank_text_slot_is_not_a_guessed_text_table_key(self):
        data = {"layouts": [layout("main", texts=[{"name": "before_stone", "attributes": {}, "frames": []}])]}
        result = decode(data)
        self.assertFalse(result["references"])
        self.assertEqual(result["texts"][0]["text"], "")
        self.assertEqual(result["texts"][0]["status"], "runtime-bound")
        self.assertEqual(result["texts"][0]["name"], "before_stone")
        self.assertFalse(result["runtimeContentBindingsVerified"])
        self.assertTrue(result["problems"])

    def test_same_file_layout_closure_respects_requested_selectors_and_exact_ids(self):
        data = {"layouts": [layout("main", containers=[container("child ")]),
                            layout("child ", bitmaps=[bitmap(path="scene/a/known")]),
                            layout("unused", bitmaps=[bitmap(path="scene/a/unrequested")])], "timelines": {}}
        result = decode(data, context={"requiredLayouts": ["main"]})
        self.assertEqual(result["layoutIds"], ["main", "child ", "unused"])
        self.assertEqual(result["selectedLayoutIds"], ["main", "child "])
        self.assertEqual([r["logical"] for r in result["references"]], ["scene/a/known"])
        self.assertFalse(result["problems"])
        self.assertEqual(result["parserCoverage"]["selection"], "required-layouts-and-same-file-closure")
        result = decode(data, context={"requiredLayouts": ["missing"]})
        self.assertTrue(any("要求的UI内部布局不存在" in p["reason"] for p in result["problems"]))

    def test_cycles_missing_ids_and_duplicates_do_not_prevent_known_sibling_images(self):
        data = {"layouts": [layout("a", containers=[container("b"), container("missing")]),
                            layout("b", containers=[container("a")], bitmaps=[bitmap()]),
                            layout("a")]}
        result = decode(data)
        self.assertEqual(len(result["references"]), 1)
        self.assertTrue(any("成环" in p["reason"] for p in result["problems"]))
        self.assertTrue(any("不存在" in p["reason"] for p in result["problems"]))
        self.assertTrue(any("重复" in p["reason"] for p in result["problems"]))
        self.assertFalse(result["parserCoverage"]["fixedReferencesComplete"])

    def test_unknown_nested_tags_bad_paths_and_malformed_nodes_are_pending(self):
        data = {"layouts": [layout("a", bitmaps=[bitmap(["simple"]), bitmap("future"), bitmap(path="../escape"), bitmap()],
                                   containers=[container(["a"])], components=[{"src": "not-invented"}])]}
        result = decode(data)
        self.assertEqual([r["logical"] for r in result["references"]], ["scene/general/sprite_sheet/icon"])
        self.assertGreaterEqual(len(result["problems"]), 5)
        self.assertEqual(result["parserCoverage"]["status"], "pending")

    def test_html_uses_first_top_html_direct_body_and_ignores_stylesheet_navigation(self):
        result = html('<!DOCTYPE html/><html><head><link href="style.css"/></head><body><p>正文</p><a href="https://example.test"><img button="button/base" alt="按钮"/></a></body></html><html><body><img src="file://ignored.png"/></body></html>')
        self.assertEqual([r["logical"] for r in result["references"]], ["scene/common_ui_bundled/general_button"])
        self.assertIn("layout/box_background/highlight", result["references"][0]["requiredLayouts"])
        self.assertIn("layout/box_background/disable", result["references"][0]["requiredLayouts"])
        self.assertIn("layout/box_down_blur/standard", result["references"][0]["requiredLayouts"])
        self.assertEqual(result["references"][0]["context"]["bucket"], "FollowingLogic")
        self.assertEqual([t["text"] for t in result["texts"]], ["正文", "按钮"])
        self.assertFalse(result["problems"])
        self.assertTrue(any(c["status"] == "navigation" for c in result["coverage"]))

    def test_a_first_child_whitespace_and_p_embedded_img_are_not_asset_references(self):
        result = html('<html><body><a>\n<img src="file://ignored1.png"/></a><p><img src="file://ignored2.png"/></p><div><img src="file://scene/a/known.png"/></div></body></html>')
        self.assertEqual([r["logical"] for r in result["references"]], ["scene/a/known"])
        self.assertEqual(result["references"][0]["lookup"], "standalone-file-texture")
        self.assertFalse(result["problems"])

    def test_local_file_uses_first_dot_and_remote_or_invalid_src_remains_pending(self):
        result = html('<html><body><img src="file://scene/a.v2/icon.png"/><img src="https://example.test/a.png"/><img src="plain/image.png"/><img src="file://../../escape.png"/><img src="file://character/test/ui/skill_cutin_0.png"/></body></html>')
        self.assertEqual([r["logical"] for r in result["references"]], ["scene/a"])
        self.assertEqual(len(result["problems"]), 4)
        self.assertTrue(any(p.get("requiredReferences", [{}])[0].get("kind") == "remote-image" for p in result["problems"]))
        self.assertFalse(result["parserCoverage"]["fixedReferencesComplete"])

    def test_fragment_nested_body_and_dtd_entities_are_rejected(self):
        for value in ('<body><p>bad</p></body>', '<html><div><body/></div></html>',
                      '<!DOCTYPE html [<!ENTITY x "expand">]><html><body>&x;</body></html>'):
            result = html(value)
            self.assertTrue(result["problems"])
            self.assertFalse(result["references"])
            self.assertFalse(result["complete"])

    def test_actual_codec_source_sha_and_pointers_are_fixed_not_user_proof(self):
        data = {"layouts": [layout("main", bitmaps=[bitmap()])], "timelines": {}}
        raw = compress(encode_amf3(data))
        result = ui.resolve_ui_resources("scene/a.ui.amf3.deflate", raw, context={"sourceProof": {"complete": True}}, pointer="/input")
        self.assertEqual(result["sourceIdentity"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["references"][0]["definitionEvidence"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["references"][0]["pointer"], "/input/layouts/0/children/bitmaps/0/attributes/path")
        self.assertEqual(result["sourceProof"]["swf"], ui.SWF)
        self.assertFalse(result["runtimeAcceptance"])
        result["sourceProof"]["sourceHashes"].clear()
        self.assertTrue(ui.BASIS)

    def test_compressed_bomb_truncation_trailing_bytes_and_json_duplicate_fields_fail_closed(self):
        for raw in (compress(b"x" * 1000), compress(b"bad")[:-1], compress(b"bad") + b"tail"):
            with mock.patch.object(ui, "LIMIT", 64):
                result = ui.resolve_ui_resources("scene/a.ui.amf3.deflate", raw)
            self.assertTrue(result["problems"])
        result = ui.resolve_ui_resources("scene/a.ui.json", b'{"layouts":[],"layouts":[]}')
        self.assertTrue(result["problems"])
        data = {"layouts": [layout("main")]}
        result = ui.resolve_ui_resources("scene/a.ui.amf3.deflate", compress(encode_amf3(data) + b"tail"))
        self.assertTrue(result["problems"])
        # Dynamic object, repeated a key (second key string is reference zero).
        result = ui.resolve_ui_resources("scene/a.ui.amf3.deflate", compress(b'\x0a\x0b\x01\x03a\x04\x01\x00\x04\x02\x01'))
        self.assertTrue(any("重复" in p["reason"] for p in result["problems"]))

    def test_declared_counts_bad_references_and_deep_json_are_bounded(self):
        for raw in (b"\x09\x0f\x01", b"\x06\x00", b"\x0a\x00"):
            with mock.patch.object(ui, "MAX_NODES", 3):
                result = ui.resolve_ui_resources("scene/a.ui.amf3.deflate", compress(raw))
            self.assertTrue(result["problems"])
        value = {"layouts": []}
        for _ in range(12):
            value = {"child": value}
        with mock.patch.object(ui, "MAX_DEPTH", 5):
            result = decode(value)
        self.assertTrue(result["problems"])

    def test_missing_layout_arrays_and_wrong_api_inputs_do_not_raise(self):
        for raw, kind, logical in (([], "ui", "scene/a"), (b"", ["ui"], "scene/a"),
                                   (b"{}", "ui", "../escape"), (b"{}", "ui", "scene/a.ui.json")):
            result = ui.resolve_ui_resources(logical, raw, kind=kind)
            self.assertTrue(result["problems"])

    def test_retained_twelve_exact_files_optional_fixture(self):
        value = os.environ.get("STUDIO_NATIVE_UI_INPUTS")
        if not value:
            self.skipTest("explicit frozen UI input directory required")
        root = Path(value)
        rows = json.loads((root / "ui-inputs-provenance.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(len(rows), 12)
        for row in rows:
            path = root / row["physical"]
            raw = path.read_bytes()
            result = ui.resolve_ui_resources(row["physical"], raw, row["kind"])
            self.assertFalse([p for p in result["problems"] if p["reason"].startswith("UI资源解析待核")], row["logical"])
            self.assertEqual(result["sourceIdentity"]["sha256"], row["source"]["sha256"])
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse(result["complete"])
            self.assertFalse(result["runtimeAcceptance"])
            self.assertFalse(result["runtimeContentBindingsVerified"])


if __name__ == "__main__":
    unittest.main()
