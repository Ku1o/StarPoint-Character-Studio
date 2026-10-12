import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import author_gameplay as author
import native_gameplay as native
from studio_core import ProjectStore
from test_native_gameplay import pack


def card(**changes):
    return {"trigger": "skill", "target": "self", "effect": "attack_up",
            "amount": "20%", "duration": "10秒", "stacking": "single",
            "text": "使用技能时，自己攻击力提高20%，持续10秒。", **changes}


def gauge_card(**changes):
    return card(**{"effect": "skill_gauge_up", "duration": "", "stacking": "unmarked",
                   "text": "使用技能时，尝试增加自己基础最大技能槽的20%。", **changes})


class AuthorGameplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / "projects")
        self.project = self.store.create("中文作者")
        self.definition = pack()
        self.definition["characters"]["10"]["records"]["character"]["selected"]["10"]["rows"][0][3] = "0"
        class Library:
            def load(inner):
                return self.definition
        self.library = Library()
        self.project = native.attach(self.store, self.project["id"], 0, self.library, "10")

    def save_cards(self, cards, plan="ability0", description=None):
        self.project = self.store.load(self.project["id"])
        plans = self.project["productionBrief"]["plans"]
        target = plans["abilities"][int(plan[7:])] if plan.startswith("ability") else plans[plan]
        target["authorCards"] = cards
        target["authorDescription"] = description if description is not None else "\n".join(c.get("text", "") for c in cards if isinstance(c, dict))
        self.project = self.store.save(self.project)

    def apply_supported(self):
        report = author.preview(self.project)
        keys = [row["id"] for row in report["cards"] if row["state"] == "supported"]
        self.assertTrue(keys, report)
        self.project = author.apply(self.store, self.project["id"], self.project["revision"], report["token"], keys)
        return report

    def test_real_condition_enum_units_and_serialized_readback(self):
        self.save_cards([card()])
        original = copy.deepcopy(self.project)
        report = self.apply_supported()
        self.assertFalse(report["gameReady"])
        row = self.project["nativeGameplay"]["abilities"][0]["rows"][-1]
        blocks = native.describe.layout("ability")["blocks"]
        self.assertEqual(row[blocks["instant_trigger"]], "23")
        base = blocks["instant_content"]
        self.assertEqual(row[base], "0")  # timed condition, NOT permanent stat 32
        self.assertEqual(row[base + 4:base + 6], ["20000", "20000"])
        self.assertEqual(row[base + 10:base + 12], ["60000000", "60000000"])
        self.assertEqual(row[base + 12:base + 14], ["100000", "100000"])
        self.assertEqual(row[base + 14], "(None)")
        self.assertEqual(row[base + 27], "1")
        self.assertEqual(row[base + 25], "false")
        files, receipt = native.compile_native(self.project["nativeGameplay"])
        decoded = native.core.read_orderedmap_bytes(files["native-draft/ability.orderedmap"], "<test>")
        self.assertEqual(native.core.read_csv_lines(decoded.rows[0].decode()), self.project["nativeGameplay"]["abilities"][0]["rows"])
        self.assertTrue(receipt["readback"])
        self.assertEqual(self.project["nativeGameplay"]["source"], original["nativeGameplay"]["source"])
        self.assertEqual(self.project["nativeGameplay"]["skills"], original["nativeGameplay"]["skills"])
        self.assertEqual(self.project["productionBrief"], original["productionBrief"])
        self.assertEqual(self.project["nativeGameplay"]["abilities"][0]["rows"][:-1], original["nativeGameplay"]["abilities"][0]["rows"])
        author.validate(self.project)

    def test_mixed_intents_and_free_text_never_disappear(self):
        self.save_cards([card(), card(effect="damage"), card(trigger="hit"), card(customField="unknown")],
                        description="额外要求：技能后恢复原姿势。\n" + card()["text"])
        before = copy.deepcopy(self.project["productionBrief"])
        report = self.apply_supported()
        self.assertEqual([row["state"] for row in report["cards"]], ["supported", "pending", "pending", "pending"])
        current = author.handoff(self.project)
        self.assertEqual(current["cards"][0]["state"], "applied")
        self.assertEqual(len(current["cards"]), 4)
        self.assertIn("额外要求", current["pending"][0]["text"])
        self.assertEqual(self.project["productionBrief"], before)
        self.assertFalse(current["gameReady"])
        json.dumps(current, ensure_ascii=False)

    def test_all_timed_buff_families_apply_one_condition_with_nonzero_magnification(self):
        effects = ["attack_up", "skill_damage_up", "direct_damage_up", "power_flip_up"]
        self.save_cards([card(effect=effect) for effect in effects])
        self.apply_supported()
        rows = self.project["nativeGameplay"]["abilities"][0]["rows"][-4:]
        base = native.describe.layout("ability")["blocks"]["instant_content"]
        self.assertEqual([row[base] for row in rows], ["0", "1", "214", "28"])
        for row in rows:
            self.assertEqual(row[base + 12:base + 14], ["100000", "100000"])
            self.assertEqual(row[base + 14], "(None)")
            self.assertEqual(row[base + 27], "1")
            self.assertEqual(row[base + 28], "0")

    def test_skill_gauge_catalog_and_explicit_native_ratio_readback(self):
        effect = next(value for value in author.catalog()["effects"] if value["id"] == "skill_gauge_up")
        self.assertEqual((effect["amountUnit"], effect["durationMode"]), ("percent", "instant"))
        self.assertEqual(effect["targets"], ["self", "party", "element_party"])
        enums = native.composer.composer_meta()["enums"]["instant_content"]
        self.assertEqual(enums["211"]["en"], "SkillGauge")
        self.assertEqual(enums["215"]["en"], "DirectDamageDownPrevent")
        self.save_cards([gauge_card(), gauge_card(trigger="battle_start", target="party", amount="100%"),
                         gauge_card(trigger="power_flip", target="element_party", amount="0.001%", mainOnly=True,
                                    conditions=[{"kind": "hp_at_least", "value": "80%"}])])
        before = copy.deepcopy(self.project)
        report = author.preview(self.project)
        self.assertEqual([value["state"] for value in report["cards"]], ["supported"] * 3)
        self.assertEqual(self.store.load(self.project["id"]), before)
        self.project = author.apply(self.store, self.project["id"], self.project["revision"], report["token"],
                                    [value["id"] for value in report["cards"]])
        blocks = native.describe.layout("ability")["blocks"]
        base = blocks["instant_content"]
        rows = self.project["nativeGameplay"]["abilities"][0]["rows"][-3:]
        self.assertEqual([row[base:base + 3] for row in rows], [["211", "0", "0"], ["211", "5", "0"], ["211", "1", "Red"]])
        self.assertEqual([row[base + 4:base + 6] for row in rows], [["20000", "20000"], ["100000", "100000"], ["1", "1"]])
        self.assertEqual([row[blocks["instant_trigger"]] for row in rows], ["23", "0", "2"])
        self.assertTrue(all(row[base + 10:base + 14] == ["0"] * 4 for row in rows))
        self.assertEqual(rows[-1][blocks["precondition1"]], "202")
        self.assertEqual(rows[-1][blocks["precondition2"]], "8")
        self.assertIn("基础最大技能槽的20%", report["items"][0]["description"])
        self.assertTrue(all("尝试" in item["description"] and "仍沿游戏获取限制" in item["description"] for item in report["items"]))
        self.assertIn("火属性队友（不含自己", report["items"][-1]["description"])
        files, receipt = native.compile_native(self.project["nativeGameplay"])
        decoded = native.core.read_orderedmap_bytes(files["native-draft/ability.orderedmap"], "<gauge>")
        self.assertEqual(native.core.read_csv_lines(decoded.rows[0].decode()), self.project["nativeGameplay"]["abilities"][0]["rows"])
        self.assertTrue(receipt["readback"])
        self.assertFalse(receipt["gameReady"])
        unchanged = copy.deepcopy(self.project["nativeGameplay"])
        unchanged["abilities"][0]["rows"] = unchanged["abilities"][0]["rows"][:-3]
        self.assertEqual(unchanged, before["nativeGameplay"])
        self.assertEqual(self.project["productionBrief"], before["productionBrief"])
        restored = self.store.import_archive(self.store.export(self.project["id"]))
        self.assertEqual(restored["nativeGameplay"], self.project["nativeGameplay"])
        restored = author.undo(self.store, restored["id"], restored["revision"])
        self.assertEqual(restored["nativeGameplay"], before["nativeGameplay"])

    def test_skill_gauge_rejects_unsupported_rules_without_write(self):
        changes = [{"amount": "0%"}, {"amount": "-1%"}, {"amount": "100.001%"}, {"amount": "20"},
                   {"amount": "2倍"}, {"amount": "0.00001%"}, {"target": "battle_combo"}, {"target": "enemy"},
                   {"trigger": "always"}, {"trigger": "damage"}, {"duration": "10秒"}, {"duration": "永久"},
                   {"stacking": "single"}, {"stacking": "accumulate"}, {"details": {}},
                   {"details": {"mechanic": "custom", "repeat": "每次耗能"}}]
        cards = [gauge_card(**value) for value in changes]
        self.save_cards(cards)
        before = copy.deepcopy(self.project)
        report = author.preview(self.project)
        self.assertFalse(report["canApply"])
        self.assertTrue(all(item["state"] == "pending" for item in report["cards"]))
        self.assertEqual([item["card"] for item in author.handoff(self.project)["cards"]], cards)
        with self.assertRaises(ValueError):
            author.apply(self.store, self.project["id"], self.project["revision"], report["token"], [report["cards"][0]["id"]])
        self.assertEqual(self.store.load(self.project["id"]), before)

    def test_skill_gauge_leader_and_existing_main_gate_are_preserved(self):
        self.save_cards([gauge_card(target="party", trigger="battle_start")], "leader")
        before = copy.deepcopy(self.project["nativeGameplay"])
        self.apply_supported()
        base = native.describe.layout("leader_ability")["blocks"]["instant_content"]
        self.assertEqual(self.project["nativeGameplay"]["leader"]["rows"][-1][base:base + 2], ["211", "5"])
        self.project = author.undo(self.store, self.project["id"], self.project["revision"])
        self.assertEqual(self.project["nativeGameplay"], before)
        self.project["nativeGameplay"]["abilities"][0]["rows"][0][1] = "false"
        self.project = self.store.save(self.project)
        self.save_cards([gauge_card(), gauge_card(mainOnly=True)])
        report = author.preview(self.project)
        self.assertEqual([item["state"] for item in report["cards"] if item["plan"] == "ability0"], ["pending", "supported"])
        self.assertEqual(self.project["nativeGameplay"]["abilities"][0]["rows"][0][1], "false")

    def test_skill_gauge_repeat_stale_preview_and_external_edit_cannot_overwrite(self):
        self.save_cards([gauge_card()])
        initial = author.preview(self.project)
        self.apply_supported()
        applied = author.preview(self.project)
        for report in (initial, applied):
            before = copy.deepcopy(self.project)
            with self.assertRaises(ValueError):
                author.apply(self.store, self.project["id"], self.project["revision"], report["token"], [report["cards"][0]["id"]])
            self.assertEqual(self.store.load(self.project["id"]), before)
        self.project["nativeGameplay"]["abilities"][0]["rows"][-1][native.describe.layout("ability")["blocks"]["instant_content"] + 4] = "30000"
        self.project = self.store.save(self.project)
        before = copy.deepcopy(self.project)
        self.assertFalse(author.preview(self.project)["canUndo"])
        with self.assertRaises(ValueError):
            author.undo(self.store, self.project["id"], self.project["revision"])
        self.assertEqual(self.store.load(self.project["id"]), before)

    def test_explicit_selected_subset_and_exact_undo_roundtrip(self):
        self.save_cards([card(), card(effect="skill_damage_up")])
        original = copy.deepcopy(self.project["nativeGameplay"])
        report = author.preview(self.project)
        self.project = author.apply(self.store, self.project["id"], self.project["revision"], report["token"], [report["cards"][1]["id"]])
        self.assertEqual(len(self.project["nativeGameplay"]["abilities"][0]["rows"]), 2)
        after = author.preview(self.project)
        self.assertEqual([row["state"] for row in after["cards"]], ["supported", "applied"])
        restored = self.store.import_archive(self.store.export(self.project["id"]))
        author.validate(restored)
        undone = author.undo(self.store, restored["id"], restored["revision"])
        self.assertEqual(undone["nativeGameplay"], original)
        self.assertEqual(undone["productionBrief"], self.project["productionBrief"])

    def test_no_definition_or_invalid_old_source_cannot_be_repaired_by_cards(self):
        blank = self.store.create("无定义")
        blank["productionBrief"]["plans"]["abilities"][0]["authorCards"] = [card()]
        report = author.preview(blank)
        self.assertFalse(report["canApply"])
        self.assertFalse(report["gameReady"])
        self.assertTrue(report["blockers"])
        self.assertNotIn("nativeGameplay", blank)
        bad = copy.deepcopy(self.definition)
        bad["characters"]["10"]["records"]["abilities"]["selected"]["81"]["rows"][0][6] = ""
        class BadLibrary:
            def load(inner):
                return bad
        p = self.store.create("旧异常")
        p = native.attach(self.store, p["id"], 0, BadLibrary(), "10")
        p["productionBrief"]["plans"]["abilities"][0]["authorCards"] = [card()]
        p = self.store.save(p)
        old = copy.deepcopy(p)
        report = author.preview(p)
        self.assertFalse(report["canApply"])
        with self.assertRaises(ValueError):
            author.apply(self.store, p["id"], p["revision"], report["token"], [report["cards"][0]["id"]])
        self.assertEqual(self.store.load(p["id"]), old)

    def test_unknown_units_conditions_and_guessed_semantics_are_pending(self):
        changes = [dict(amount="20"), dict(amount="2倍"), dict(amount="NaN%"),
                   dict(amount="0.00001%"), dict(amount="0%"), dict(duration=""),
                   dict(duration="-10秒"), dict(stacking=""), dict(stacking="accumulate"),
                   dict(mainOnly="false"), dict(target="enemy"), dict(trigger="damage"),
                   dict(target=[]), dict(effect={}), dict(trigger=[]),
                   dict(effect="heal", duration=""), dict(trigger="skill", duration="永久")]
        self.save_cards([card(**value) for value in changes])
        report = author.preview(self.project)
        self.assertFalse(report["canApply"])
        self.assertTrue(all(row["state"] == "pending" for row in report["cards"]))
        self.assertEqual(len(report["cards"]), len(changes))

    def test_heal_permanent_main_only_and_element_target_contracts(self):
        self.save_cards([card(effect="heal", duration="", healBasis="maximum_hp", target="party"),
                         card(trigger="battle_start", duration="永久", target="element_party", mainOnly=True)])
        self.apply_supported()
        rows = self.project["nativeGameplay"]["abilities"][0]["rows"]
        base = native.describe.layout("ability")["blocks"]["instant_content"]
        self.assertEqual(rows[-2][base:base + 3], ["206", "5", "0"])
        self.assertEqual(rows[-1][base:base + 3], ["32", "1", "Red"])
        self.assertEqual(rows[-1][1], "false")
        self.assertEqual(rows[-1][native.describe.layout("ability")["blocks"]["precondition1"]], "202")
        self.save_cards([card(trigger="battle_start", duration="永久")], "leader")
        self.apply_supported()
        self.assertEqual(len(self.project["nativeGameplay"]["leader"]["rows"]), 2)

    def test_existing_first_row_gate_is_not_rewritten_to_admit_unison(self):
        self.project["nativeGameplay"]["abilities"][0]["rows"][0][1] = "false"
        self.project = self.store.save(self.project)
        self.save_cards([card(), card(mainOnly=True)])
        report = author.preview(self.project)
        self.assertEqual([item["state"] for item in report["cards"]], ["pending", "supported"])
        self.assertIn("原能力组首条", report["cards"][0]["pendingNextAction"])
        self.apply_supported()
        self.assertEqual(self.project["nativeGameplay"]["abilities"][0]["rows"][0][1], "false")
        row = self.project["nativeGameplay"]["abilities"][0]["rows"][-1]
        self.assertEqual(row[native.describe.layout("ability")["blocks"]["precondition1"]], "202")

    def test_same_batch_cannot_close_empty_group_to_selected_unison_card(self):
        self.project["nativeGameplay"]["abilities"][0]["rows"] = []
        self.project = self.store.save(self.project)
        self.save_cards([card(mainOnly=True), card(mainOnly=False)])
        before = copy.deepcopy(self.project)
        report = author.preview(self.project)
        self.assertEqual([item["state"] for item in report["cards"]], ["supported", "supported"])
        ids = [item["id"] for item in report["cards"]]
        with self.assertRaisesRegex(ValueError, "未保存|首条"):
            author.apply(self.store, self.project["id"], self.project["revision"], report["token"], ids)
        self.assertEqual(self.store.load(self.project["id"]), before)
        # Choosing the unison entry first leaves whole-group admission open;
        # the second main-only entry still has the actual OwnerIsMain condition.
        self.project = author.apply(self.store, self.project["id"], self.project["revision"], report["token"], ids[::-1])
        rows = self.project["nativeGameplay"]["abilities"][0]["rows"]
        self.assertEqual(rows[0][1], "true")
        self.assertEqual(rows[1][native.describe.layout("ability")["blocks"]["precondition1"]], "202")
        self.assertTrue(native.compile_native(self.project["nativeGameplay"])[1]["readback"])
        self.project = author.undo(self.store, self.project["id"], self.project["revision"])
        self.assertEqual(self.project["nativeGameplay"], before["nativeGameplay"])

    def test_hash_stale_selection_repeat_and_external_edit_are_safe(self):
        self.save_cards([card(), card(effect="damage")])
        before = copy.deepcopy(self.project)
        report = author.preview(self.project)
        for ids in ([], ["unknown"], [report["cards"][1]["id"]], [report["cards"][0]["id"]] * 2):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                author.apply(self.store, self.project["id"], self.project["revision"], report["token"], ids)
            self.assertEqual(self.store.load(self.project["id"]), before)
        self.apply_supported()
        with self.assertRaises(ValueError):
            author.apply(self.store, self.project["id"], self.project["revision"], report["token"], [report["cards"][0]["id"]])
        after = author.preview(self.project)
        self.assertNotEqual(report["token"], after["token"])
        with self.assertRaises(ValueError):
            author.apply(self.store, self.project["id"], self.project["revision"], after["token"], [report["cards"][0]["id"]])
        changed = copy.deepcopy(self.project)
        changed["nativeGameplay"]["skills"][0]["fields"][0] = "其他任务编辑"
        changed = self.store.save(changed)
        with self.assertRaises(ValueError):
            author.undo(self.store, changed["id"], changed["revision"])
        self.assertEqual(self.store.load(changed["id"]), changed)

    def test_changed_applied_card_keeps_old_row_and_requires_undo(self):
        self.save_cards([card()])
        self.apply_supported()
        rows = copy.deepcopy(self.project["nativeGameplay"]["abilities"][0]["rows"])
        self.save_cards([card(amount="30%")])
        report = author.preview(self.project)
        self.assertEqual(report["cards"][0]["state"], "pending")
        self.assertIn("撤回", report["cards"][0]["pendingNextAction"])
        self.assertEqual(self.project["nativeGameplay"]["abilities"][0]["rows"], rows)

    def test_deleted_or_changed_applied_row_is_pending_in_preview_and_handoff(self):
        self.save_cards([card()])
        self.apply_supported()
        applied = copy.deepcopy(self.project)
        for operation, spec in (("delete", {}), ("patch", {"value": 30})):
            with self.subTest(operation=operation):
                fresh = self.store.create("修改或删除")
                value = copy.deepcopy(applied)
                value["id"] = fresh["id"]
                value["revision"] = fresh["revision"]
                value = self.store.save(value)
                value = native.edit(self.store, value["id"], value["revision"], operation, 1, 1, spec)
                report = author.preview(value)
                self.assertEqual(report["items"][0]["status"], "pending")
                self.assertIn("修改或删除", report["items"][0]["reason"])
                self.assertFalse(report["canApply"])
                self.assertFalse(report["canUndo"])
                self.assertEqual(author.handoff(value)["cards"][0]["state"], "pending")
                self.assertEqual(value["authorGameplayIntegration"], applied["authorGameplayIntegration"])
                with self.assertRaises(ValueError):
                    author.apply(self.store, value["id"], value["revision"], report["token"], [report["cards"][0]["id"]])
                self.assertEqual(self.store.load(value["id"]), value)

    def test_identical_row_hash_does_not_hide_deletion_of_one_applied_card(self):
        self.save_cards([card(), card()])
        self.apply_supported()
        self.project = native.edit(self.store, self.project["id"], self.project["revision"], "delete", 1, 2, {})
        report = author.preview(self.project)
        self.assertEqual([item["status"] for item in report["items"]], ["pending", "pending"])
        self.assertFalse(report["canApply"])
        self.assertEqual(len(self.project["authorGameplayIntegration"]["history"][0]["cards"]), 2)

    def test_metadata_bounds_do_not_forge_game_acceptance(self):
        author.validate(self.project)
        self.save_cards([card()])
        self.apply_supported()
        bad = copy.deepcopy(self.project)
        bad["authorGameplayIntegration"]["history"][0]["gameReady"] = True
        with self.assertRaises(ValueError):
            author.validate(bad)
        bad = copy.deepcopy(self.project)
        bad["authorGameplayIntegration"]["history"] *= 11
        with self.assertRaises(ValueError):
            author.validate(bad)

    @unittest.skipUnless(os.environ.get("STUDIO_NATIVE_REFERENCE"), "opt-in retained production definition")
    def test_retained_production_definitions_serialize_without_changing_source(self):
        raw = Path(os.environ["STUDIO_NATIVE_REFERENCE"]).read_bytes()
        library = native.DefinitionLibrary(Path(self.tmp.name) / "actual-definitions")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
        library.install(files)
        for cid in ("169978", "159992"):
            with self.subTest(cid=cid):
                p = self.store.create("保留生产定义" + cid)
                p = native.attach(self.store, p["id"], p["revision"], library, cid)
                source = copy.deepcopy(p["nativeGameplay"]["source"])
                skills = copy.deepcopy(p["nativeGameplay"]["skills"])
                p["productionBrief"]["plans"]["abilities"][0]["authorCards"] = [card(), gauge_card()]
                p = self.store.save(p)
                report = author.preview(p)
                p = author.apply(self.store, p["id"], p["revision"], report["token"], [item["id"] for item in report["cards"]])
                self.assertEqual(p["nativeGameplay"]["source"], source)
                self.assertEqual(p["nativeGameplay"]["skills"], skills)
                native.compile_native(p["nativeGameplay"])
                restored = author.undo(self.store, p["id"], p["revision"])
                self.assertEqual(restored["nativeGameplay"]["source"], source)


if __name__ == "__main__":
    unittest.main()
