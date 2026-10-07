"""Strict declarations, truthful provenance and consistent source handoff."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import (ProjectStore, StudioError, fresh_project, png_bytes, validate,
                         normalize_declarations, validate_declarations, project_checks,
                         declaration_payload, author_readme, animation_variant, clip_variant)
from author_declarations import declaration_report, readiness, _md


class AuthorDeclarationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-author-declarations-")
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.p = self.store.create("声明测试")
        # Different bytes avoid content-addressed deduplication of frame identities.
        self.plain = self.store.add_asset(self.p, "idle_001.png", png_bytes(Image.new("RGBA", (8, 8), "red")), "pixel")
        self.composite = self.store.add_asset(self.p, "idle_001_sp.png", png_bytes(Image.new("RGBA", (8, 8), "blue")), "pixel")
        self.p["animations"] = [self.action("a1", "neutral", [self.plain])]
        self.store._write(self.p)

    def tearDown(self):
        self.temp.cleanup()

    def action(self, aid, slot, assets):
        return {"id": aid, "name": "动作 " + slot, "slot": slot, "kind": "loop", "fps": 60, "frameScale": 6,
                "variant": "special" if slot.startswith("special_") else "normal",
                "clips": [{"asset": asset, "hold": index + 1, "x": 0, "y": 0} for index, asset in enumerate(assets)]}

    def declarations(self, p=None):
        return [i for i in project_checks(p or self.p)["issues"] if i["declaration"]]

    def codes(self, p=None):
        return {i["code"] for i in self.declarations(p)}

    def add_voice(self, vid="v1", filename="join.mp3", **fields):
        aid = self.store.add_asset(self.p, filename, (bytes.fromhex("fffb9000") + bytes(413)) * 4, "voice")
        voice = {"id": vid, "asset": aid, "name": filename, **fields}
        self.p["voices"].append(voice)
        return voice

    def test_normalization_never_coerces_boolean_values(self):
        for value in ("false", "true", "0", 0, 1, -1, .5, [], {}, [False]):
            with self.subTest(value=value):
                p = copy.deepcopy(self.p)
                p["animations"][0]["includesCompanion"] = value
                normalize_declarations(p)
                self.assertEqual(value, p["animations"][0]["includesCompanion"])
                with self.assertRaises(StudioError):
                    validate_declarations(p)
                self.assertFalse(project_checks(p)["readiness"]["canCompile"])
        for value in (True, False, "", None):
            p = copy.deepcopy(self.p)
            p["animations"][0]["includesCompanion"] = value
            normalize_declarations(p)
            validate_declarations(p)
            self.assertIs(p["animations"][0]["includesCompanion"], value) if type(value) is bool else self.assertEqual("", p["animations"][0]["includesCompanion"])

    def test_strict_ui_and_voice_flags_including_numeric_zero(self):
        for group, field in (("uiDeclarations", "autoCrop"), ("voiceDeclarations", "reused")):
            for value in ("false", 0, 1, [], {}):
                with self.subTest(group=group, value=value):
                    p = copy.deepcopy(self.p)
                    p[group] = {"base:square": {field: value}} if group == "uiDeclarations" else [{"asset": "voice", field: value}]
                    normalize_declarations(p)
                    with self.assertRaises(StudioError):
                        validate_declarations(p)
                    self.assertIn("declaration_type_invalid", self.codes(p))

    def test_malformed_containers_text_enums_and_records_fail_cleanly(self):
        patches = [
            {"authorNotes": True}, {"authorNotes": {}}, {"uiDeclarations": []}, {"uiDeclarations": "false"},
            {"voiceDeclarations": {}}, {"voiceDeclarations": False}, {"voiceDeclarations": [False]},
            {"voiceDeclarations": [{"entry": []}]}, {"voiceDeclarations": [{"usage": 4}]},
            {"voiceDeclarations": [{"text": {}}]}, {"voiceDeclarations": [{"file": []}]},
            {"voiceDeclarations": [{"text": "x" * 2001}]},
            {"uiDeclarations": {"base:invalid": {}}}, {"uiDeclarations": {0: {}}},
            {"uiDeclarations": {"nonsense:square": {}}}, {"uiDeclarations": {"base:square": []}},
            {"uiDeclarations": {"base:square": {"mask": ["auto"]}}},
            {"uiDeclarations": {"base:square": {"note": 0}}},
            {"animations": [False]}, {"effects": "oops"},
        ]
        for patch in patches:
            with self.subTest(patch=patch):
                p = copy.deepcopy(self.p)
                p.update(patch)
                normalize_declarations(p)
                with self.assertRaises(StudioError):
                    validate_declarations(p)
                self.assertIn("declaration_type_invalid", self.codes(p))
        for field in ("purpose", "origin", "originNote", "companionNote"):
            for value in (False, 0, [], {}, "x" * 501):
                p = copy.deepcopy(self.p)
                p["animations"][0][field] = value
                normalize_declarations(p)
                with self.subTest(field=field, value=value), self.assertRaises(StudioError):
                    validate(p)

    def test_legacy_load_is_unknown_and_does_not_rewrite_original(self):
        p = copy.deepcopy(self.p)
        for key in ("authorNotes", "uiDeclarations", "voiceDeclarations"):
            p.pop(key, None)
        for key in ("purpose", "includesCompanion", "companionNote", "origin", "originNote"):
            p["animations"][0].pop(key, None)
        path = self.store.directory(p["id"]) / "project.json"
        path.write_text(json.dumps(p), encoding="utf-8")
        before = path.read_bytes()
        loaded = self.store.load(p["id"])
        validate(loaded)
        payload = declaration_payload(loaded)
        self.assertEqual("", payload["animations"][0]["includesCompanion"])
        self.assertNotIn("includesCompanion", loaded["animations"][0])
        self.assertEqual(before, path.read_bytes())
        self.assertIn("未标注", author_readme(loaded))
        self.assertTrue(project_checks(loaded)["readiness"]["canCompile"])

    def test_base_composite_requires_true_and_nonblank_note(self):
        p = self.p
        p["animations"] = [self.action("a1", "neutral", [self.composite])]
        for flag, note, allowed in (("", "", False), (False, "说明", False), (True, "", False),
                                    (True, " \n ", False), (True, "战斗全程有小鸟", True)):
            with self.subTest(flag=flag, note=note):
                p["animations"][0].update(includesCompanion=flag, companionNote=note)
                validate(p)  # Risk is not a persistence/schema error.
                report = project_checks(p)
                self.assertEqual(allowed, report["readiness"]["canCompile"])
                self.assertEqual(not allowed, any(i["blocking"] for i in report["issues"]))
        p["animations"][0]["includesCompanion"] = "false"
        normalize_declarations(p)
        self.assertFalse(project_checks(p)["readiness"]["canCompile"])

    def test_false_composite_blocks_any_slot_including_skill_ready(self):
        for slot in ("neutral", "skill_ready", "special_land", "special_pose", "custom_action"):
            p = copy.deepcopy(self.p)
            p["animations"] = [self.action("a1", slot, [self.composite])]
            p["animations"][0].update(includesCompanion=False, companionNote="不带", purpose="自定义用途")
            report = project_checks(p)
            blocked = [i for i in report["issues"] if i["blocking"]]
            with self.subTest(slot=slot):
                self.assertEqual(["companion_declaration_conflict"], [i["code"] for i in blocked])
                self.assertEqual("a1", blocked[0]["id"])

    def test_actual_selected_frame_evidence_wins_over_asset_and_action_labels(self):
        p = self.p
        p["assets"][self.composite]["variant"] = "plain"
        p["animations"] = [self.action("a1", "neutral", [self.composite])]
        p["animations"][0]["variant"] = "plain"
        self.assertEqual("composite", clip_variant(p, self.composite))
        self.assertEqual("composite", animation_variant(p, p["animations"][0]))
        self.assertFalse(project_checks(p)["readiness"]["canCompile"])
        self.assertEqual("composite", declaration_payload(p)["animations"][0]["variant"])
        p["animations"][0]["clips"][0]["asset"] = self.plain
        self.assertTrue(project_checks(p)["readiness"]["canCompile"])
        self.assertEqual("plain", animation_variant(p, p["animations"][0]))

    def test_all_supported_suffixes_cannot_be_hidden_by_plain(self):
        for suffix in ("_sp", "_summon", "_fx", "_eff", "_glow"):
            for field in ("name", "sourceFile", "sourceName", "file", "logical"):
                p = fresh_project()
                p["assets"] = {"f": {field: "frame" + suffix + ".PNG", "variant": "plain"}}
                self.assertEqual("composite", clip_variant(p, "f"), (suffix, field))
        self.assertEqual("unknown", clip_variant({"assets": {}}, "missing"))

    def test_mixed_selected_frames_not_unused_inbox_are_reported(self):
        p = self.p
        p["animations"] = [self.action("a1", "neutral", [self.plain])]
        self.assertNotIn("frame_group_mixed", self.codes())
        p["animations"][0]["clips"].append({"asset": self.composite, "hold": 3})
        self.assertEqual("mixed", animation_variant(p, p["animations"][0]))
        self.assertIn("frame_group_mixed", self.codes())
        self.assertFalse(project_checks(p)["readiness"]["canCompile"])
        p["animations"][0].update(includesCompanion=True, companionNote="第二段才出现小鸟")
        self.assertTrue(project_checks(p)["readiness"]["canCompile"])
        self.assertIn("frame_group_mixed", self.codes())

    def test_skill_ready_keeps_explicit_plain_and_unmarked_is_only_todo(self):
        p = self.p
        p["animations"] = [self.action("a1", "skill_ready", [self.plain])]
        self.assertTrue(project_checks(p)["readiness"]["canCompile"])
        self.assertIn("companion_undeclared", self.codes())
        p["animations"][0]["includesCompanion"] = False
        self.assertNotIn("companion_undeclared", self.codes())
        self.assertEqual("plain", declaration_payload(p)["animations"][0]["variant"])
        p["animations"][0]["clips"][0]["asset"] = self.composite
        self.assertFalse(project_checks(p)["readiness"]["canCompile"])

    def test_animation_import_issues_do_not_shadow_issue_builder(self):
        p = self.p
        p["animations"] = [self.action("a1", "neutral", [self.composite])]
        p["animations"][0]["issues"] = ["原生素材待核验"]
        self.assertIn("animation_import_warning", {i["code"] for i in project_checks(p)["issues"]})
        self.assertIn("base_state_composite_suspect", self.codes())

    def test_effect_native_and_sequence_need_real_origin_and_source_note(self):
        for native in (False, True):
            p = copy.deepcopy(self.p)
            p["effects"] = [{"id": "fx1", "name": "特效", "native": native}]
            with self.subTest(native=native):
                self.assertIn("effect_origin_missing", self.codes(p))
                p["effects"][0]["origin"] = "reuse"
                self.assertIn("effect_origin_note_missing", self.codes(p))
                p["effects"][0]["originNote"] = "复用模板 hit_1 特效"
                self.assertNotIn("effect_origin_note_missing", self.codes(p))
                self.assertTrue(project_checks(p)["readiness"]["canCompile"])

    def test_voice_rows_validate_content_not_merely_registration_presence(self):
        voice = self.add_voice()
        self.p["voiceDeclarations"] = [{"asset": voice["asset"]}]
        self.assertIn("voice_usage_missing", self.codes())
        self.p["voiceDeclarations"][0].update(entry="ally", usage="join", text="  ")
        self.assertIn("voice_usage_missing", self.codes())
        self.p["voiceDeclarations"][0]["text"] = "暂无台词"
        self.assertNotIn("voice_usage_missing", self.codes())

    def test_voice_uses_actual_ui_usage_text_and_infers_only_supported_entry(self):
        self.add_voice(usage="join", text="我加入了", sourceFile="voice/ally/join.mp3")
        self.assertNotIn("voice_usage_missing", self.codes())
        rows = declaration_payload(self.p)["voiceTable"]
        self.assertEqual(("ally", "join", "我加入了"), (rows[0]["entry"], rows[0]["usage"], rows[0]["text"]))
        self.p["voices"][0].update(usage="other", sourceFile="")
        self.assertIn("voice_usage_missing", self.codes())
        self.p["sounds"] = [{"id": "sound1", "asset": self.p["voices"][0]["asset"], "usage": "skill_sfx", "text": ""}]
        self.assertEqual(1, len(declaration_report(self.p)["voiceTable"]))

    def test_voice_matches_id_asset_source_path_and_unique_basename(self):
        voice = self.add_voice(sourceFile="voice/ally/join.mp3")
        for reference in ({"id": voice["id"]}, {"asset": voice["asset"]}, {"file": "voice/ally/join.mp3"},
                          {"file": "ally/join.mp3"}, {"file": "join.mp3"}):
            self.p["voiceDeclarations"] = [{**reference, "entry": "ally", "usage": "join", "text": "台词"}]
            with self.subTest(reference=reference):
                self.assertNotIn("voice_usage_missing", self.codes())
                self.assertNotIn("voice_declaration_unmatched", self.codes())
        self.p["voiceDeclarations"] = [{"file": "wrong.mp3", "entry": "ally", "usage": "join", "text": "台词"}]
        self.assertIn("voice_declaration_unmatched", self.codes())
        self.assertIn("voice_usage_missing", self.codes())

    def test_ambiguous_or_duplicate_voice_declaration_cannot_complete_voice(self):
        voice = self.add_voice()
        row = {"asset": voice["asset"], "entry": "ally", "usage": "join", "text": "台词"}
        self.p["voiceDeclarations"] = [row, copy.deepcopy(row)]
        self.assertIn("voice_usage_missing", self.codes())
        self.p["voices"].append({**voice, "id": "v2"})
        self.p["voiceDeclarations"] = [row]
        self.assertIn("voice_declaration_unmatched", self.codes())

    def test_ui_exact_form_and_nonempty_intent_are_required_for_actual_selections(self):
        self.p["uiImages"] = {"base:square": {"mode": "image", "asset": self.plain},
                              "evolved:square": {"mode": "image", "asset": self.composite}}
        self.p["uiDeclarations"] = {"base:square": {"autoCrop": True, "mask": "none"}}
        missing = [i for i in self.declarations() if i["code"] == "ui_special_crop_unmarked"]
        self.assertEqual(["evolved:square"], [i["id"] for i in missing])
        self.p["uiDeclarations"]["evolved:square"] = {}
        self.assertIn("ui_special_crop_unmarked", self.codes())
        self.p["uiDeclarations"]["evolved:square"] = {"autoCrop": False, "mask": "none"}
        self.assertIn("ui_special_crop_unmarked", self.codes())
        self.p["uiDeclarations"]["evolved:square"]["note"] = "使用单独头像，禁止母版裁切"
        self.assertNotIn("ui_special_crop_unmarked", self.codes())

    def test_ui_crops_and_official_sources_are_not_treated_as_author_confirmation(self):
        self.p["uiSources"] = {"base:battle_control_board": self.plain}
        self.p["uiImages"] = {"evolved:skill_cutin": {"mode": "crop", "asset": self.composite,
                                "rect": {"x": 0, "y": 0, "width": 8, "height": 8}, "width": 1024, "height": 512}}
        missing = [i["id"] for i in self.declarations() if i["code"] == "ui_special_crop_unmarked"]
        self.assertEqual(["base:battle_control_board", "evolved:skill_cutin"], missing)
        self.p["uiDeclarations"] = {"base:battle_control_board": {"autoCrop": True, "mask": "auto"},
                                   "evolved:skill_cutin": {"autoCrop": True, "mask": "none"}}
        self.assertNotIn("ui_special_crop_unmarked", self.codes())
        self.p["uiDeclarations"]["base:battle_control_board"]["mask"] = "none"
        self.assertIn("ui_special_crop_unmarked", self.codes())

    def test_every_issue_has_stable_ui_schema_and_readiness_counts_are_exact(self):
        p = self.p
        p["animations"] = [self.action("a1", "neutral", [self.composite])]
        report = project_checks(p)
        for issue in report["issues"]:
            self.assertTrue({"code", "level", "page", "id", "summary", "text", "blocking", "declaration", "position", "location", "fix"}.issubset(issue))
            self.assertIs(type(issue["blocking"]), bool)
            self.assertIs(type(issue["declaration"]), bool)
            self.assertTrue(issue["code"] and issue["position"] and issue["fix"])
        r = report["readiness"]
        self.assertEqual(sum(i["blocking"] for i in report["issues"]), r["blocking"])
        for level in ("todo", "warning", "info"):
            self.assertEqual(sum(i["level"] == level for i in report["issues"]), r[level])
        self.assertEqual("blocked", r["status"])
        p["animations"][0].update(includesCompanion=True, companionNote="待机带小鸟")
        r = project_checks(p)["readiness"]
        self.assertTrue(r["canCompile"])
        self.assertEqual("needs_review", r["status"])
        self.assertFalse(report["gameReady"])
        self.assertTrue(report["draft"])
        self.assertEqual("ready", readiness([], {"complete": 0, "total": 0})["status"])

    def test_empty_project_blocks_candidate_but_stays_exportable_as_draft(self):
        empty = fresh_project("空白原创工程")
        report = project_checks(empty)
        blockers = [item for item in report["issues"] if item["code"] == "candidate_visual_missing"]
        self.assertEqual(1, len(blockers))
        self.assertTrue(blockers[0]["blocking"])
        self.assertFalse(report["readiness"]["canCompile"])
        self.assertEqual("blocked", report["readiness"]["status"])
        self.assertTrue(report["draft"])
        self.assertFalse(report["gameReady"])

        saved = self.store.load(self.p["id"])
        saved["animations"] = []
        self.store.save(saved)
        raw = self.store.export(saved["id"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            checks = json.loads(archive.read("检查报告.json"))
            self.assertFalse(checks["readiness"]["canCompile"])
            self.assertTrue(checks["draft"])
            self.assertFalse(checks["gameReady"])
            self.assertIn("README-稿主必读.md", archive.namelist())
            self.assertIn("declarations.json", archive.namelist())

    def test_one_playable_action_does_not_block_on_empty_optional_presets(self):
        report = project_checks(self.p)
        self.assertNotIn("candidate_visual_missing", {item["code"] for item in report["issues"]})
        self.assertTrue(report["readiness"]["canCompile"])

    def test_declaration_completion_counts_only_applicable_complete_records(self):
        p = fresh_project()
        self.assertEqual({"complete": 0, "total": 0}, project_checks(p)["readiness"]["declarations"])
        p = self.p
        p["animations"] = [self.action("a1", "skill_ready", [self.plain])]
        self.add_voice(usage="join", text="加入台词")
        p["effects"] = [{"id": "fx", "origin": "original", "originNote": "原创四件套"}]
        p["uiImages"] = {"base:square": {"mode": "image", "asset": self.plain}}
        p["uiDeclarations"] = {"base:square": {"autoCrop": True, "mask": "none"}}
        self.assertEqual({"complete": 3, "total": 4}, project_checks(p)["readiness"]["declarations"])
        p["animations"][0]["includesCompanion"] = False
        self.assertEqual({"complete": 4, "total": 4}, project_checks(p)["readiness"]["declarations"])
        p["uiDeclarations"]["base:square"] = {}
        self.assertEqual({"complete": 3, "total": 4}, project_checks(p)["readiness"]["declarations"])

    def test_readme_and_payload_are_pure_and_show_unknown_not_confirmed_no(self):
        self.p["uiImages"] = {"base:square": {"mode": "image", "asset": self.plain}}
        self.p["uiDeclarations"] = {"base:square": {}}
        p = self.p
        before = copy.deepcopy(p)
        payload = declaration_payload(p)
        report = project_checks(p)
        readme = author_readme(p, report)
        self.assertEqual(before, p)
        self.assertEqual("", payload["uiDeclarations"]["base:square"]["autoCrop"])
        self.assertIn("| base:square | 未标注 | 未标注 |", readme)
        self.assertNotIn("| base:square | 否 |", readme)
        for issue in report["issues"]:
            self.assertIn("`" + issue["code"] + "`", readme)
            self.assertIn(_md(issue["summary"]), readme)
            self.assertIn(_md(issue["fix"]), readme)

    def test_readme_escapes_all_author_names_multiline_text_and_html(self):
        p = self.p
        value = "名称|第一行\n# 标题\r\n<img src=x onerror=alert(1)>[link](evil)`"
        p["name"] = value
        p["identity"]["author"] = value
        p["authorNotes"] = value
        p["animations"][0]["name"] = value
        p["animations"][0]["purpose"] = value
        self.add_voice(usage="join", text=value)
        p["assets"][p["voices"][0]["asset"]]["name"] = value
        p["effects"] = [{"id": "fx", "name": value, "origin": "reuse", "originNote": value}]
        p["uiImages"] = {"base:square": {"mode": "image", "asset": self.plain}}
        p["uiDeclarations"] = {"base:square": {"autoCrop": False, "mask": "none", "note": value}}
        readme = author_readme(p)
        self.assertNotIn("<img", readme)
        self.assertNotIn("\n# 标题", readme)
        self.assertIn("\\|第一行<br>\\# 标题<br>&lt;img", readme)
        self.assertIn("\\[link\\]", readme)
        self.assertIn("&gt;", readme)

    def test_source_zip_report_readme_and_declarations_use_same_actual_state(self):
        p = self.store.load(self.p["id"])
        p["animations"][0]["clips"][0]["asset"] = self.composite
        saved = self.store.save(p)
        raw = self.store.export(saved["id"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            checks = json.loads(archive.read("检查报告.json"))
            packed = json.loads(archive.read("project.json"))
            payload = json.loads(archive.read("declarations.json"))
            readme = archive.read("README-稿主必读.md").decode("utf-8")
        self.assertEqual(project_checks(packed), checks)
        self.assertEqual(author_readme(packed, checks), readme)
        self.assertEqual(declaration_payload(packed), payload)
        self.assertFalse(checks["readiness"]["canCompile"])
        self.assertTrue(checks["draft"])
        self.assertFalse(checks["gameReady"])
        restored = ProjectStore(Path(self.temp.name) / "restored").import_archive(raw)
        self.assertEqual("composite", animation_variant(restored, restored["animations"][0]))
        self.assertFalse(project_checks(restored)["readiness"]["canCompile"])

    def test_export_omits_only_unknown_mask_without_mutating_draft(self):
        self.p["uiDeclarations"] = {
            "base:square": {"mask": "", "autoCrop": "", "note": "待确认"},
            "evolved:square": {"mask": "none", "autoCrop": False, "note": "专用图"},
        }
        before = copy.deepcopy(self.p)
        payload = declaration_payload(self.p)
        self.assertNotIn("mask", payload["uiDeclarations"]["base:square"])
        self.assertEqual("", payload["uiDeclarations"]["base:square"]["autoCrop"])
        self.assertEqual("待确认", payload["uiDeclarations"]["base:square"]["note"])
        self.assertEqual("none", payload["uiDeclarations"]["evolved:square"]["mask"])
        self.assertIs(False, payload["uiDeclarations"]["evolved:square"]["autoCrop"])
        self.assertEqual(before, self.p)

    def test_export_resolves_effective_voice_for_v1_consumers_without_confirming_reuse(self):
        voice = self.add_voice(usage="join", text="加入台词", sourceFile="voice/ally/join.mp3")
        before = copy.deepcopy(self.p)
        payload = declaration_payload(self.p)
        self.assertEqual(1, len(payload["voiceDeclarations"]))
        row = payload["voiceDeclarations"][0]
        self.assertEqual((voice["id"], voice["asset"], "ally", "join", "加入台词"),
                         (row["id"], row["asset"], row["entry"], row["usage"], row["text"]))
        self.assertEqual("", row["reused"])
        self.assertEqual(before, self.p)
        self.assertEqual([], self.p["voiceDeclarations"])

    def test_export_preserves_explicit_voice_intent_and_unmatched_evidence(self):
        voice = self.add_voice(usage="join", text="原台词", sourceFile="voice/ally/join.mp3")
        self.p["voiceDeclarations"] = [
            {"asset": voice["asset"], "entry": "home", "usage": "home1", "text": "作者台词",
             "reused": False, "note": "保留额外说明"},
            {"file": "not-found.mp3", "entry": "battle", "usage": "attack", "text": "待核对"},
        ]
        before = copy.deepcopy(self.p)
        rows = declaration_payload(self.p)["voiceDeclarations"]
        self.assertEqual(2, len(rows))
        self.assertEqual(("home", "home1", "作者台词"), tuple(rows[0][key] for key in ("entry", "usage", "text")))
        self.assertIs(False, rows[0]["reused"])
        self.assertEqual("保留额外说明", rows[0]["note"])
        self.assertEqual("not-found.mp3", rows[1]["file"])
        self.assertIn("voice_declaration_unmatched", self.codes())
        self.assertEqual(before, self.p)

    def test_export_keeps_duplicate_voice_declarations_unresolved(self):
        voice = self.add_voice(usage="join", text="加入台词")
        row = {"asset": voice["asset"], "entry": "ally", "usage": "join", "text": "台词"}
        self.p["voiceDeclarations"] = [copy.deepcopy(row), copy.deepcopy(row)]
        before = copy.deepcopy(self.p)
        payload = declaration_payload(self.p)
        expected = copy.deepcopy(before)
        normalize_declarations(expected)
        self.assertEqual(expected["voiceDeclarations"], payload["voiceDeclarations"])
        self.assertTrue(payload["voiceTable"][0]["ambiguous"])
        self.assertIn("voice_usage_missing", self.codes())
        self.assertEqual(before, self.p)

    def test_payload_rejects_malformed_declarations_rather_than_attesting_them(self):
        self.p["animations"][0]["includesCompanion"] = "false"
        before = copy.deepcopy(self.p)
        with self.assertRaises(StudioError):
            declaration_payload(self.p)
        self.assertEqual(before, self.p)


if __name__ == "__main__":
    unittest.main()
