import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_dependencies as deps
import native_ability_dependencies as ability
from test_native_gameplay import row
from test_native_summon_dependencies import flat
from test_native_dependencies import unique_table, fixture


class AbilityDependenciesTests(unittest.TestCase):
    def test_instant_pf_override_expands_three_real_levels_and_source_hash(self):
        fields = row("ability")
        fields[47], fields[82] = "722", "custom"
        files = {ability.PF_TABLES[0]: flat({"other": ["a", "b", "c"]}),
                 ability.PF_TABLES[1]: flat({"custom": ["battle/pf/a", "battle/pf/b", "battle/pf/c"]})}
        before = copy.deepcopy(fields)
        result = ability.resolve_ability_resources(fields, "ability", 3, deps._DefinitionReader(files), "/ability")
        self.assertEqual(fields, before)
        roots = [r for r in result["references"] if r["domain"] == "powerFlip"]
        self.assertEqual([r["logical"] for r in roots], [f"battle/pf/{p}.action.dsl.amf3.deflate" for p in "abc"])
        self.assertTrue(all(r["definitionEvidence"]["sha256"] == hashlib.sha256(files[ability.PF_TABLES[1]]).hexdigest() for r in roots))
        self.assertTrue(all(r["context"]["element"] == 3 for r in roots))
        self.assertFalse(result["problems"])

    def test_during_pf_missing_union_and_duplicate_keys_are_explicit(self):
        fields = row("ability")
        fields[109], fields[120] = "419", "custom"
        files = {ability.PF_TABLES[1]: flat({"custom": ["battle/pf/a", "battle/pf/b", "battle/pf/c"]})}
        result = ability.resolve_ability_resources(fields, "ability", 1, deps._DefinitionReader(files))
        self.assertEqual(len([r for r in result["references"] if r["domain"] == "powerFlip"]), 3)
        self.assertTrue(any("合并源未冻结" in p["reason"] for p in result["problems"]))
        self.assertTrue(any(c["code"] == "419" and c["status"] == "pending" for c in result["coverage"]))
        files[ability.PF_TABLES[0]] = files[ability.PF_TABLES[1]]
        result = ability.resolve_ability_resources(fields, "ability", 1, deps._DefinitionReader(files))
        self.assertFalse([r for r in result["references"] if r["domain"] == "powerFlip"])
        self.assertTrue(any("重复键" in p["reason"] for p in result["problems"]))

    def test_unique_enemy_resolves_icon_and_direction_but_not_manual_complete(self):
        fields = row("ability")
        fields[47], fields[68] = "413", "123"
        result = ability.resolve_ability_resources(fields, "ability", 2, deps._DefinitionReader({deps.UNIQUE_TABLE: unique_table(direction="1")}))
        refs = {r["logical"]: r for r in result["references"]}
        self.assertEqual(refs["battle/unique/icon"]["context"]["kind"], "image")
        self.assertEqual(refs["battle/unique/icon"]["definitionEvidence"]["key"], "123")
        self.assertIn("battle/effect/hit/condition/debuff/debuff", refs)
        self.assertNotIn("complete", result)

    def test_timed_guts_combo_reduction_and_heal_rejection_are_fixed_resources(self):
        for code, expected in (("701", "battle/effect/hit/condition/buff/buff"),
                               ("468", "battle/effect/hit/condition/enhancing_grit/enhancing_grit"),
                               ("718", "battle/effect/hit/condition/combo_reduction/combo_reduction"),
                               ("475", "battle/effect/hit/condition/enfeebling_no_heal/enfeebling_no_heal")):
            fields = row("ability")
            fields[47] = code
            result = ability.resolve_ability_resources(fields, "ability", 3, deps._DefinitionReader({}))
            self.assertIn(expected, [r["logical"] for r in result["references"]], code)

    def test_instant_226_bridge_has_no_asset_branch_but_unknown_code_stays_pending(self):
        fields = row("ability")
        fields[47] = "226"
        result = ability.resolve_ability_resources(fields, "ability", 0, deps._DefinitionReader({}))
        self.assertFalse(result["problems"])
        self.assertEqual({r["logical"] for r in result["references"]},
            {"battle/common/layer1/total_ability_damage_effect", "battle/common/layer1/total_powerflip_damage_effect"})
        fields[47] = "999999"
        result = ability.resolve_ability_resources(fields, "ability", 0, deps._DefinitionReader({}))
        self.assertTrue(any("999999" in p["reason"] for p in result["problems"]))
        self.assertEqual(result["coverage"][0]["status"], "pending")

    def test_static_common_roots_retain_separate_bucket_and_concrete_feature_gaps(self):
        roots = deps.extract_native_roots(fixture())["roots"]
        common = [r for r in roots if r["bucket"] == "Common"]
        logicals = {r["logical"] for r in common}
        self.assertIn("battle/common/layer0/flipper_guide_line", logicals)
        self.assertIn("battle/common/layer0/attack_to_hostile_hit", logicals)
        self.assertIn("battle/common/layer0/damage_effect_out_hole", logicals)
        self.assertIn("battle/common/layer1/accumulation_damage_effect_to_hostile", logicals)
        self.assertIn("battle/effect/skill_chain/skill_chain", logicals)
        battle = [r for r in common if r["kind"] not in ("ui", "html")]
        self.assertTrue(all(r["collection"] == "common-battle-authoring" for r in battle))
        interface = [r for r in common if r["kind"] in ("ui", "html")]
        self.assertEqual(len(interface), 36)
        self.assertTrue(all(r["collection"] == ("common-following-logic" if r["kind"] == "ui"
                                               else "common-view-rich-text") for r in interface))
        result = ability.common_resources()
        self.assertNotIn("battle/common/layer0/escape_line", {r["logical"] for r in result["references"]})
        self.assertEqual({p["pointer"] for p in result["problems"]},
                         {"/Common/featuresPermit", "/Common/assetReadKind", "/Attention"})

    def test_current_known_instant_paths_keep_shared_preload_and_exact_branch_proof(self):
        expected = {
            "96": ["InstantAbilityContent.Common:2", "CommonAbilityContent.Character:1", "CommonAbilityCharacterContent.ConditionSlayer:23"],
            "191": ["InstantAbilityContent.InstantCharacter:4", "InstantAbilityInstantCharacterContent.ConditionExtend:10"],
            "200": ["InstantAbilityContent.Common:2", "CommonAbilityContent.Battle:0", "CommonAbilityBattleContent.PowerFlipComboCountDown:9"],
            "211": ["InstantAbilityContent.InstantCharacter:4", "InstantAbilityInstantCharacterContent.SkillGauge:8"],
        }
        for kind in ("ability", "leader_ability"):
            for code, runtime_path in expected.items():
                with self.subTest(kind=kind, raw=code):
                    fields = row(kind)
                    base = 47 if kind == "ability" else 45
                    fields[base] = code
                    before = copy.deepcopy(fields)
                    result = ability.resolve_ability_resources(fields, kind, 5, deps._DefinitionReader({}), "/native/row")
                    self.assertEqual(fields, before)
                    self.assertFalse(result["problems"])
                    self.assertEqual({r["logical"] for r in result["references"]},
                        {"battle/common/layer1/total_ability_damage_effect", "battle/common/layer1/total_powerflip_damage_effect"})
                    item = result["coverage"][0]
                    self.assertEqual(item["status"], "included")
                    self.assertEqual(item["runtimePath"], runtime_path)
                    self.assertEqual(item["resourceBehavior"], "no-additional-static-collector-roots")
                    self.assertEqual(item["sourceProof"]["method"], "ABC299/body14488")
                    self.assertEqual(item["sourceProof"]["sourceHashes"]["InstantAbilitySource.resolveInstantContent.body"],
                        "b920769d365cae73818ed25a5ef2e243714122e218ed2061f7657d36acc38056")
                    self.assertFalse(item["runtimeAcceptance"])
                    self.assertNotIn("complete", result)

    def test_pinch_slayer_runtime_hit_uses_signed_endpoints_and_keeps_unknown_pending(self):
        for endpoints, directions in ((("50000", "50000"), {"buff"}),
                                       (("-50000", "-10000"), {"debuff"}),
                                       (("-1", "1"), {"buff", "debuff"}),
                                       (("0", "0"), {"debuff"})):
            fields = row("ability")
            fields[47], fields[51:53] = "24", list(endpoints)
            result = ability.resolve_ability_resources(fields, "ability", 5, deps._DefinitionReader({}))
            hits = [r for r in result["references"] if r["origin"] == "runtime-implicit"]
            self.assertEqual({r["logical"] for r in hits},
                {f"battle/effect/hit/condition/{d}/{d}" for d in directions})
            self.assertEqual(result["coverage"][0]["runtimePath"][-1], "ConditionChangeContent.PinchSlayer:18")
        fields[51] = "NaN"
        result = ability.resolve_ability_resources(fields, "ability", 5, deps._DefinitionReader({}))
        self.assertTrue(result["problems"])
        self.assertFalse([r for r in result["references"] if r["origin"] == "runtime-implicit"])

    def test_piercing_and_flying_real_blank_strengths_do_not_become_zero_or_missing(self):
        for code, name in (("26", "enhancing_penetrate"), ("27", "enhancing_waftage")):
            fields = row("ability")
            fields[47], fields[51:53] = code, ["", ""]
            before = copy.deepcopy(fields)
            result = ability.resolve_ability_resources(fields, "ability", 5, deps._DefinitionReader({}), "/real/blank-strength")
            self.assertEqual(fields, before)
            self.assertFalse(result["problems"])
            hit = next(r for r in result["references"] if r["origin"] == "runtime-implicit")
            self.assertEqual(hit["logical"], f"battle/effect/hit/condition/{name}/{name}")
            self.assertEqual(hit["domain"], "ability")
            self.assertEqual(hit["context"]["element"], 5)
            self.assertEqual(result["coverage"][0]["runtimePath"][0], "InstantAbilityContent.ConditionBattle:1")

    def test_during_charging_and_pf_damage_use_current_common_enum_and_no_extra_preload(self):
        for kind in ("ability", "leader_ability"):
            for code, tail in (("3", "CommonAbilityCharacterContent.SkillGaugeCharging:8"),
                               ("23", "CommonAbilityBattleContent.PowerFlipDamage:0")):
                fields = row(kind)
                base, during = (47, 109) if kind == "ability" else (45, 107)
                fields[base-1], fields[during] = "(None)", code
                before = copy.deepcopy(fields)
                result = ability.resolve_ability_resources(fields, kind, 3, deps._DefinitionReader({}), "/during/row")
                self.assertEqual(fields, before)
                self.assertFalse(result["problems"])
                self.assertFalse(result["references"])
                item = result["coverage"][0]
                self.assertEqual(item["status"], "included")
                self.assertEqual(item["runtimePath"][-1], tail)
                self.assertEqual(item["sourceProof"]["method"], "DuringAbilitySource.createFromDuringAbilityValues")
                self.assertFalse(item["runtimeAcceptance"])

    def test_exact_branch_support_does_not_clear_neighbouring_unknowns_or_inactive_rows(self):
        fields = row("ability")
        fields[47], fields[109] = "212", "24"
        result = ability.resolve_ability_resources(fields, "ability", 3, deps._DefinitionReader({}))
        self.assertTrue(any("instant_content 212" in p["reason"] for p in result["problems"]))
        self.assertTrue(any("during_content 24" in p["reason"] for p in result["problems"]))
        self.assertTrue(all(item["status"] == "pending" for item in result["coverage"]))
        fields[46], fields[47], fields[109] = "(None)", "211", "0"
        result = ability.resolve_ability_resources(fields, "ability", 3, deps._DefinitionReader({}))
        self.assertFalse(result["references"])
        self.assertFalse(result["coverage"])

    def test_returned_proof_cannot_mutate_fixed_branch_mapping(self):
        fields = row("ability")
        fields[47] = "211"
        first = ability.resolve_ability_resources(fields, "ability", 3, deps._DefinitionReader({}))
        first["coverage"][0]["runtimePath"].append("invented")
        second = ability.resolve_ability_resources(fields, "ability", 3, deps._DefinitionReader({}))
        self.assertNotIn("invented", second["coverage"][0]["runtimePath"])

    def test_real_retained_two_character_rows_optional_fixture(self):
        path = os.environ.get("STUDIO_NATIVE_ABILITY_DEFINITIONS")
        if not path:
            self.skipTest("explicit frozen native definitions required")
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        seen = set()
        for cid in ("169978", "159992"):
            records = data["characters"][cid]["records"]
            for section, kind in (("leader_ability", "leader_ability"), ("abilities", "ability")):
                for key, value in records[section]["selected"].items():
                    for index, fields in enumerate(value["rows"]):
                        before = copy.deepcopy(fields)
                        result = ability.resolve_ability_resources(fields, kind, 5, deps._DefinitionReader({}), f"/{cid}/{section}/{key}/{index}")
                        self.assertEqual(fields, before)
                        for item in result["coverage"]:
                            branch = (item["block"], item["code"])
                            if branch in ability.BRANCHES:
                                seen.add(branch)
                                self.assertEqual(item["status"], "included")
                        self.assertFalse([p for p in result["problems"] if "完整资源转换" in p["reason"]])
        self.assertEqual(seen, set(ability.BRANCHES))
        self.assertEqual(Path(path).read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
