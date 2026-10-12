import copy
import io
import os
from pathlib import Path
import unittest
import zipfile

import test_author_gameplay as common
import author_gameplay as author
import native_gameplay as native


def conditional(**changes):
    return common.card(**{"conditions": [{"kind": "hp_at_least", "value": "80%"},
                                           {"kind": "combo_at_most", "value": "20"}], **changes})


def combo(**changes):
    return common.card(**{"effect": "combo_add", "target": "battle_combo", "amount": "10", "duration": "",
                          "stacking": "unmarked", "text": "自身使用技能时，追加本次战斗连击10。", **changes})


class ComplexAuthorGameplayTests(unittest.TestCase):
    setUp = common.AuthorGameplayTests.setUp
    save_cards = common.AuthorGameplayTests.save_cards
    apply_supported = common.AuthorGameplayTests.apply_supported

    def test_two_conditions_and_main_only_use_all_real_precondition_slots(self):
        self.save_cards([conditional(mainOnly=True)])
        before = copy.deepcopy(self.project)
        report = self.apply_supported()
        self.assertIn("同时满足", report["items"][0]["description"])
        self.assertIn("生命比例视作", report["items"][0]["description"])
        row = self.project["nativeGameplay"]["abilities"][0]["rows"][-1]
        b = native.describe.layout("ability")["blocks"]
        self.assertEqual(row[b["precondition1"]], "202")
        self.assertEqual(row[b["precondition2"]:b["precondition2"] + 7], ["8", "0", "", "80000", "80000", "", "0"])
        self.assertEqual(row[b["precondition3"]:b["precondition3"] + 7], ["11", "0", "", "2000000", "2000000", "", "0"])
        self.assertEqual(self.project["nativeGameplay"]["source"], before["nativeGameplay"]["source"])
        self.assertEqual(self.project["nativeGameplay"]["skills"], before["nativeGameplay"]["skills"])
        files, receipt = native.compile_native(self.project["nativeGameplay"])
        decoded = native.core.read_orderedmap_bytes(files["native-draft/ability.orderedmap"], "<complex>")
        self.assertEqual(native.core.read_csv_lines(decoded.rows[0].decode()), self.project["nativeGameplay"]["abilities"][0]["rows"])
        self.assertTrue(receipt["readback"])
        self.project = author.undo(self.store, self.project["id"], self.project["revision"])
        self.assertEqual(self.project["nativeGameplay"], before["nativeGameplay"])

    def test_native_inclusive_bounds_barrier_and_count_units(self):
        conditions = [{"kind": "hp_at_most", "value": "30%"},
                      {"kind": "combo_at_least", "value": "25"},
                      {"kind": "has_barrier", "value": ""},
                      {"kind": "combo_at_most", "value": "0"}]
        self.save_cards([common.card(conditions=[value]) for value in conditions])
        self.apply_supported()
        rows = self.project["nativeGameplay"]["abilities"][0]["rows"][-4:]
        base = native.describe.layout("ability")["blocks"]["precondition1"]
        self.assertEqual([row[base] for row in rows], ["9", "10", "87", "11"])
        self.assertEqual([row[base + 3] for row in rows], ["30000", "2500000", "0", "0"])
        self.assertTrue(native.compile_native(self.project["nativeGameplay"])[1]["readback"])

    def test_unproven_or_contradictory_conditions_remain_pending_without_write(self):
        values = [None, {}, [{"kind": "combo_at_least", "value": "0"}],
                  [{"kind": "hp_at_least", "value": "80"}],
                  [{"kind": "hp_at_most", "value": "101%"}],
                  [{"kind": "hp_at_most", "value": "0.00001%"}],
                  [{"kind": "combo_at_least", "value": "2.5"}],
                  [{"kind": "combo_at_least", "value": "10000"}],
                  [{"kind": "hp_at_least", "value": "80%", "target": "enemy"}],
                  [{"kind": "has_barrier", "value": "20%"}],
                  [{"kind": "skill_ready", "value": "100%"}],
                  [{"kind": "hp_at_least", "value": "90%"}, {"kind": "hp_at_most", "value": "50%"}],
                  [{"kind": "combo_at_least", "value": "20"}] * 2,
                  [{"kind": "has_barrier", "value": ""}] * 3]
        cards = [common.card(conditions=value) for value in values]
        cards += [conditional(trigger="always", duration="永久"), common.card(conditionMode="any")]
        self.save_cards(cards)
        before = copy.deepcopy(self.project)
        result = author.preview(self.project)
        self.assertEqual([item["status"] for item in result["items"]], ["pending"] * len(cards))
        self.assertFalse(result["canApply"])
        self.assertEqual(self.store.load(self.project["id"]), before)
        self.assertEqual([item["card"] for item in author.handoff(self.project)["cards"]], cards)

    def test_add_combo_is_native_battle_count_and_does_not_touch_skills_or_dsl(self):
        self.save_cards([combo(conditions=[{"kind": "hp_at_least", "value": "80%"}])])
        before = copy.deepcopy(self.project)
        self.apply_supported()
        row = self.project["nativeGameplay"]["abilities"][0]["rows"][-1]
        base = native.describe.layout("ability")["blocks"]["instant_content"]
        self.assertEqual(row[base], "226")
        self.assertEqual(row[base + 4:base + 6], ["1000000", "1000000"])
        self.assertEqual(row[base + 10:base + 14], ["0", "0", "0", "0"])
        description = author.preview(self.project)["items"][0]["description"]
        self.assertIn("本次战斗连击增加10", description)
        self.assertNotIn("0秒", description)
        self.assertNotIn("×0", description)
        self.assertNotIn("强度2", description)
        self.assertEqual(self.project["nativeGameplay"]["source"], before["nativeGameplay"]["source"])
        self.assertEqual(self.project["nativeGameplay"]["skills"], before["nativeGameplay"]["skills"])
        self.assertTrue(native.compile_native(self.project["nativeGameplay"])[1]["readback"])
        exported = self.store.import_archive(self.store.export(self.project["id"]))
        self.assertEqual(exported["nativeGameplay"], self.project["nativeGameplay"])
        restored = author.undo(self.store, exported["id"], exported["revision"])
        self.assertEqual(restored["nativeGameplay"], before["nativeGameplay"])

    def test_supported_human_descriptions_use_actual_units_and_only_used_fields(self):
        self.save_cards([common.card(), common.card(effect="heal", amount="30%", duration="", healBasis="maximum_hp"),
                         common.card(trigger="battle_start", duration="永久", target="element_party", mainOnly=True), combo()])
        items = author.preview(self.project)["items"]
        self.assertIn("基础持续10秒", items[0]["description"])
        self.assertIn("最大生命值的30%", items[1]["description"])
        self.assertIn("火属性队友", items[2]["description"])
        self.assertIn("持续到战斗结束", items[2]["description"])
        self.assertIn("携带角色须处于主位", items[2]["description"])
        self.assertEqual(items[3]["description"], "自己使用技能时，本次战斗连击增加10。")
        for item in items:
            self.assertNotIn("强度2", item["description"])
            self.assertNotIn("需连击", item["description"])

    def test_add_combo_rejects_wrong_target_units_and_repeat_semantics(self):
        changes = [{"amount": "10%"}, {"amount": "2倍"}, {"amount": "0"}, {"amount": "2.5"},
                   {"amount": "10000"}, {"target": "self"}, {"target": "party"},
                   {"duration": "10秒"}, {"stacking": "single"}, {"trigger": "always"}]
        cards = [combo(**value) for value in changes] + [common.card(target="battle_combo")]
        self.save_cards(cards)
        report = author.preview(self.project)
        self.assertTrue(all(item["status"] == "pending" for item in report["items"]))
        self.assertFalse(report["canApply"])
        self.assertEqual([item["card"] for item in report["cards"]], cards)

    def test_unsupported_summon_and_skill_reuse_keep_provided_details_and_missing_prompts(self):
        details = {"mechanic": "summon", "reference": "沿用碧的参考动作", "count": "同时最多2个", "newUnknownRule": "切阶段保留"}
        self.save_cards([common.card(details=details)])
        before = copy.deepcopy(self.project)
        report = author.preview(self.project)
        item = report["items"][0]
        self.assertEqual(item["status"], "pending")
        self.assertIn("遗漏", item["reason"])
        prompts = {value["field"]: value for value in item["detailPrompts"]}
        self.assertEqual(prompts["reference"]["value"], details["reference"])
        self.assertEqual(prompts["count"]["status"], "provided")
        self.assertEqual(prompts["lifetime"]["status"], "needed")
        self.assertEqual(author.handoff(self.project)["cards"][0]["card"]["details"], details)
        self.assertEqual(self.store.load(self.project["id"]), before)
        self.save_cards([common.card(details={"mechanic": "skill_reuse", "reference": "复用已有主动技能"})], plan="activeSkill")
        active = next(item for item in author.preview(self.project)["items"] if item["plan"] == "activeSkill")
        self.assertEqual(active["status"], "pending")
        self.assertTrue(any(value["field"] == "repeat" and value["status"] == "needed" for value in active["detailPrompts"]))

    def test_complete_condition_and_detail_inputs_change_preview_hash(self):
        self.save_cards([conditional()])
        old = author.preview(self.project)
        self.save_cards([conditional(conditions=[{"kind": "hp_at_least", "value": "90%"}])])
        current = author.preview(self.project)
        self.assertNotEqual(current["token"], old["token"])
        with self.assertRaises(ValueError):
            author.apply(self.store, self.project["id"], self.project["revision"], old["token"], [old["items"][0]["id"]])
        self.save_cards([conditional(details={"mechanic": "summon", "reference": "新参考"})])
        self.assertNotEqual(author.preview(self.project)["token"], current["token"])

    def test_malformed_text_mechanic_and_card_shapes_are_pending_and_raw_preserved(self):
        cards = [common.card(text=[]), common.card(text={"unrecognized": "原值"}),
                 common.card(details={"mechanic": [], "reference": "已有参考"}),
                 common.card(details={"mechanic": {"custom": "新规则"}}),
                 common.card(details=[]), ["未知卡片形状"], "未知文字卡片",
                 common.card(text={"content": "保留"}, newUnknownRule={"anything": [1, 2]})]
        self.save_cards(cards, description="所有未知输入都保留，请继续协助。")
        before = copy.deepcopy(self.project)
        report = author.preview(self.project)
        self.assertTrue(all(item["status"] == "pending" for item in report["items"]))
        self.assertTrue(all(isinstance(item["text"], str) for item in report["items"]))
        self.assertEqual([item["card"] for item in report["cards"]], cards)
        self.assertEqual([item["card"] for item in author.handoff(self.project)["cards"]], cards)
        self.assertTrue(all(isinstance(item["detailPrompts"], list) for item in report["items"]))
        self.assertEqual(self.store.load(self.project["id"]), before)
        with self.assertRaises(ValueError):
            author.apply(self.store, self.project["id"], self.project["revision"], report["token"], [report["items"][0]["id"]])
        self.assertEqual(self.store.load(self.project["id"]), before)

    @unittest.skipUnless(os.environ.get("STUDIO_NATIVE_REFERENCE"), "opt-in retained production definition")
    def test_real_retained_native_definitions_new_conditions_and_combo_roundtrip(self):
        library = native.DefinitionLibrary(Path(self.tmp.name) / "complex-definitions")
        with zipfile.ZipFile(io.BytesIO(Path(os.environ["STUDIO_NATIVE_REFERENCE"]).read_bytes())) as archive:
            library.install({name: archive.read(name) for name in archive.namelist() if not name.endswith("/")})
        for cid in ("169978", "159992"):
            with self.subTest(cid=cid):
                p = self.store.create("复杂卡片真实定义" + cid)
                p = native.attach(self.store, p["id"], p["revision"], library, cid)
                original = copy.deepcopy(p["nativeGameplay"])
                p["productionBrief"]["plans"]["abilities"][0]["authorCards"] = [conditional(mainOnly=True), combo()]
                p = self.store.save(p)
                report = author.preview(p)
                self.assertTrue(all(item["status"] == "supported" for item in report["items"]))
                p = author.apply(self.store, p["id"], p["revision"], report["token"], [item["id"] for item in report["items"]])
                self.assertEqual(p["nativeGameplay"]["source"], original["source"])
                self.assertEqual(p["nativeGameplay"]["skills"], original["skills"])
                self.assertTrue(native.compile_native(p["nativeGameplay"])[1]["readback"])
                self.assertFalse(author.handoff(p)["gameReady"])
                p = author.undo(self.store, p["id"], p["revision"])
                self.assertEqual(p["nativeGameplay"], original)
