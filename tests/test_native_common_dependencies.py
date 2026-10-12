"""Finite Common alternatives must never become observed runtime admission."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_common_dependencies as common
import native_dependencies as deps
from test_native_summon_dependencies import flat


class CommonConditionDependenciesTests(unittest.TestCase):
    def test_all_static_branches_expand_without_author_configuration(self):
        result = common.conditional_common_resources({}, deps._DefinitionReader({}), {})
        self.assertEqual(len(result["references"]), 154)
        self.assertEqual(sum(c["status"] == "included-authoring-union" for c in result["coverage"]), 26)
        logicals = {r["logical"] for r in result["references"]}
        self.assertIn("battle/common/layer0/escape_line", logicals)
        self.assertIn("battle/common/layer0/ball_standby", logicals)
        self.assertIn("battle/common/layer1/touch_to_start", logicals)
        self.assertIn("battle/common/layer0/condition/enhancing_grit_invocation", logicals)
        self.assertEqual(result["selection"]["mode"], "finite-authoring-union")
        self.assertFalse(result["selection"]["observedRuntimeConfiguration"])
        self.assertFalse(result["selection"]["completeSceneBudget"])
        self.assertNotIn("complete", result)
        self.assertNotIn("gameReady", result)

    def test_author_false_flags_do_not_hide_required_branches_or_pending(self):
        project = {"featuresPermit": {"displaysBoss": False, "displaysAttention": False},
                   "assetReadKind": 0, "flipperSkin": {"enable": False}, "complete": True}
        before = copy.deepcopy(project)
        self.assertEqual(common.conditional_common_resources(project), common.conditional_common_resources({}))
        self.assertEqual(project, before)
        self.assertTrue(any("动态" in p["reason"] for p in common.conditional_common_resources(project)["problems"]))

    def test_weight_saving_zero_branch_keeps_all_seven_colors_and_sizes(self):
        refs = [r for r in common.conditional_common_resources()["references"]
                if "getWeightSavingMode" in r["definitionEvidence"]["condition"]]
        expected = {f"battle/common/layer0/effect_particle_attribution/effect_particle_attribution_{color}_{size}"
                    for color in ("black", "blue", "green", "red", "white", "yellow", "colorless")
                    for size in ("large", "medium", "small")}
        self.assertEqual({r["logical"] for r in refs}, expected)
        self.assertTrue(all(r["context"]["layer"] == 0 for r in refs))

    def test_read_kind_three_is_layout_roots_with_exact_layer_context(self):
        refs = [r for r in common.conditional_common_resources()["references"]
                if r["definitionEvidence"]["condition"] == "DevConfig.assetReadKind == 3"]
        self.assertEqual(len(refs), 25)
        self.assertTrue(all(r["context"]["kind"] == "effect" for r in refs))
        chains = [r for r in refs if r["logical"].startswith("battle/common/")]
        self.assertEqual({r["logical"] for r in chains}, {f"battle/common/layer1/cutin_skill_chain{n}" for n in range(4, 10)})
        self.assertTrue(all(r["context"]["layer"] == 1 for r in chains))
        self.assertFalse(any(r["logical"].endswith("/skill_chain") for r in refs))

    def test_conditions_keep_source_identity_and_collection_scope(self):
        for reference in common.conditional_common_resources()["references"]:
            proof = reference["definitionEvidence"]
            self.assertEqual(proof["sha256"], common.BASIS["BattleAssetPathCollectionBuilder"])
            self.assertEqual(proof["selection"], "finite-authoring-union")
            self.assertEqual(len(proof["lines"]), 2)
            self.assertEqual(reference["context"]["bucket"], "Common")
            self.assertIn(reference["context"]["collection"],
                          ("common-battle-authoring", "common-following-logic", "common-view-rich-text"))
            self.assertIn("/Common/", reference["pointer"])
        self.assertTrue(all(c.get("title") for c in common.conditional_common_resources()["coverage"]))

    def test_ui_and_html_fixed_entrypoints_have_consumer_specific_roots(self):
        result = common.conditional_common_resources()
        required = {r["logical"]: r for r in result["requiredReferences"]}
        self.assertEqual(len(required), 12)
        self.assertEqual(required["scene/battle/pause_menu"]["kind"], "ui")
        self.assertEqual(required["rich_text/settlement"]["kind"], "html")
        self.assertTrue(all(r["pointer"] == r["callerPointer"] and r["title"] for r in required.values()))
        refs = [r for r in result["references"] if r["context"]["kind"] in ("ui", "html")]
        self.assertEqual({r["logical"] for r in refs}, set(required))
        self.assertEqual(len(refs), 12)
        self.assertTrue(all(r["context"]["layer"] == "independent" for r in refs))
        self.assertFalse(any(p["pointer"] in {r["pointer"] for r in refs} for p in result["problems"]))
        self.assertTrue(all(not c["runtimeContentsVerified"] for c in result["coverage"] if "runtimeContentsVerified" in c))

    def test_dynamic_skin_and_attention_are_never_zero_or_not_applicable(self):
        result = common.conditional_common_resources()
        skin = next(p for p in result["problems"] if "/flipperSkin/" in p["pointer"])
        attention = next(p for p in result["problems"] if "/displaysAttention/" in p["pointer"])
        self.assertIn("全部行", skin["reason"])
        self.assertIn("非null", skin["reason"])
        self.assertIn("AttentionThumbnail", attention["reason"])
        self.assertIn("Badge", attention["reason"])
        self.assertTrue(skin["dynamic"] and attention["dynamic"])
        self.assertIn("/Attention", result["coveredGapPointers"])
        self.assertEqual(len([p for p in result["problems"] if "AttentionThumbnail" in p["reason"]]), 1)

    def test_exact_bell_is_kept_while_master_sound_sets_remain_pending(self):
        result = common.conditional_common_resources()
        sounds = [r for r in result["references"] if r["context"]["kind"] == "sound"]
        self.assertEqual([r["logical"] for r in sounds], ["sound_effect/common/se_attention_recieve_bell_battle.mp3"])
        self.assertEqual(sounds[0]["context"]["layer"], "independent")
        issue = next(p for p in result["problems"] if "master-loading" in p["pointer"])
        self.assertIn("loading == 7", issue["consumerEvidence"]["additionalSoundEffectSelection"])
        self.assertIn("loading == 12", issue["consumerEvidence"]["additionalSoundEffectSelection"])
        self.assertIn("_skill_chain_attack_", issue["consumerEvidence"]["additionalSoundEffectSelection"])

    def test_skin_all_rows_use_only_actual_animation_columns_with_table_identity(self):
        raw = flat({"1": ["0", "battle/common/layer0/skin/a", "ignored_movie_a", "battle/common/layer0/skin/extra"],
                    "2": ["1", "battle/common/layer0/skin/b", "ignored_movie_b", "battle/common/layer0/skin/extra"]})
        result = common._skin_resources(deps._DefinitionReader({common.SKIN_TABLE: raw}), {})
        self.assertFalse(result["problems"])
        self.assertEqual(len(result["references"]), 4)
        self.assertEqual({r["logical"] for r in result["references"]},
                         {"battle/common/layer0/skin/a", "battle/common/layer0/skin/b", "battle/common/layer0/skin/extra"})
        self.assertTrue(all(r["definitionEvidence"]["sha256"] == hashlib.sha256(raw).hexdigest() for r in result["references"]))
        self.assertEqual({r["definitionEvidence"]["column"] for r in result["references"]}, {1, 3})
        self.assertEqual(result["coverage"][0]["status"], "included-authoring-union")

    def test_skin_bad_leaf_and_empty_additional_do_not_hide_later_good_rows(self):
        raw = flat({"1": ["broken"], "2": ["1", "battle/common/layer0/skin/good", "movie", ""],
                    "3": ["2", "battle/common/layer0/skin/later", "movie", "battle/common/layer0/skin/extra"]})
        result = common._skin_resources(None, {common.SKIN_TABLE: raw})
        self.assertEqual({r["logical"] for r in result["references"]},
                         {"battle/common/layer0/skin/good", "battle/common/layer0/skin/later", "battle/common/layer0/skin/extra"})
        self.assertTrue(any("/rows/1" in p["pointer"] for p in result["problems"]))
        self.assertTrue(any("/rows/2/fields/3" in p["pointer"] and "字符串" in p["reason"] for p in result["problems"]))
        self.assertEqual(result["coverage"][0]["status"], "pending")

    def test_sound_exact_loading_union_and_nonmatching_twelve_are_not_collected(self):
        files = {name: flat({}) for group in common.SOUND_TABLES.values() for name in group}
        files[common.SOUND_TABLES["bgm"][0]] = flat({"bgm/battle": ["0", "0", "0", "0", "(None)", "6"],
                                                  "bgm/not_battle": ["0", "0", "0", "0", "(None)", "7"]})
        files[common.SOUND_TABLES["sound"][0]] = flat({"sound_effect/a": ["0", "0", "0", "6"],
                                                      "sound_effect/b": ["0", "0", "0", "7"],
                                                      "sound_effect/se_skill_chain_attack_x": ["0", "0", "0", "12"],
                                                      "sound_effect/not_chain": ["0", "0", "0", "12"]})
        result = common._sound_resources(None, files)
        self.assertFalse(result["problems"])
        self.assertEqual({r["logical"] for r in result["references"]},
                         {"bgm/battle.mp3", "sound_effect/a.mp3", "sound_effect/b.mp3", "sound_effect/se_skill_chain_attack_x.mp3"})
        self.assertTrue(all(len(r["definitionEvidence"]["unionSources"]) == 3 for r in result["references"]))

    def test_missing_sound_source_and_bad_loading_are_specific_and_keep_good_rows(self):
        name = common.SOUND_TABLES["sound"][0]
        raw = flat({"sound_effect/bad": ["0", "0", "0", "unknown"], "sound_effect/good": ["0", "0", "0", "7"]})
        result = common._sound_resources(None, {name: raw})
        self.assertEqual([r["logical"] for r in result["references"]], ["sound_effect/good.mp3"])
        self.assertTrue(any("/rows/sound_effect~1bad" in p["pointer"] for p in result["problems"]))
        self.assertEqual(len([p for p in result["problems"] if "/sources/" in p["pointer"]]), 5)
        self.assertEqual(result["coverage"][0]["status"], "pending")

    def test_sound_duplicate_across_registered_sources_is_not_silent_override(self):
        files = {name: flat({}) for group in common.SOUND_TABLES.values() for name in group}
        for name in common.SOUND_TABLES["sound"][:2]:
            files[name] = flat({"sound_effect/duplicate": ["0", "0", "0", "6"]})
        result = common._sound_resources(None, files)
        self.assertEqual([r["logical"] for r in result["references"]], ["sound_effect/duplicate.mp3"])
        self.assertTrue(any("重复键" in p["reason"] for p in result["problems"]))

    def test_skin_shared_inflate_budget_keeps_known_rows_and_marks_truncation(self):
        raw = flat({str(n): [str(n), "battle/a", "x" * 200, "battle/b"] for n in range(3)})
        with mock.patch.object(deps, "LIMIT", 600):
            result = common._skin_resources(None, {common.SKIN_TABLE: raw})
        self.assertEqual(len(result["references"]), 4)
        self.assertTrue(any("共享解压预算" in p["reason"] for p in result["problems"]))
        self.assertEqual(result["coverage"][0]["status"], "pending")

    def test_sound_shared_fields_budget_reports_pending_coverage(self):
        files = {name: flat({}) for group in common.SOUND_TABLES.values() for name in group}
        files[common.SOUND_TABLES["sound"][0]] = flat({f"sound_effect/{n}": ["0", "0", "0", "6"] for n in range(3)})
        with mock.patch.object(deps, "MAX_ITEMS", 10):
            result = common._sound_resources(None, files)
        self.assertEqual(len(result["references"]), 2)
        self.assertTrue(any("共享字段预算" in p["reason"] for p in result["problems"]))
        self.assertEqual(result["coverage"][0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
