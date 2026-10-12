"""Frozen definition edges, not runtime summon acceptance."""
import copy
import csv
import hashlib
import io
from pathlib import Path
import sys
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_dependencies as deps
import native_summon_dependencies as summons
from test_native_dependencies import orderedmap_raw
from test_native_gameplay import row


def csv_bytes(fields):
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow(fields)
    return out.getvalue().encode()


def flat(values):
    return orderedmap_raw(list(values), [zlib.compress(csv_bytes(fields)) for fields in values.values()])


def nested(key, versions):
    child = orderedmap_raw(list(versions), [zlib.compress(csv_bytes(fields)) for fields in versions.values()])
    return orderedmap_raw([key], [child])


def state_table(key, fields):
    leaf = orderedmap_raw(["idle"], [zlib.compress(csv_bytes(fields))])
    level = orderedmap_raw(["1"], [leaf])
    return orderedmap_raw([key], [level])


def multiball():
    fields = [""] * 28
    fields[0:4] = ["body", "summon_body", "5", "5"]
    fields[9], fields[10] = "battle/action/summon_body", "技能"
    fields[20:24] = ["31", "(None)", "(None)", "(None)"]
    return fields


def summon_command(key=7):
    return ["CreateSummonsMultiball", 0, key, 1,
        ["E1", ["SpecifyEffectDirectly", "battle/ready"]],
        ["SpecifyEffectDirectly", "battle/create"],
        ["SpecifyEffectDirectly", "battle/destroy"], 0, 0, 0, 0, 0, None]


def fixture():
    ability = row("ability")
    ability[47], ability[71] = "629", "battle/action/support"
    files = {summons.MULTIBALL_TABLES[0]: flat({}),
             summons.MULTIBALL_TABLES[1]: flat({"7": multiball()}),
             summons.ABILITY_TABLE: flat({"31": ability})}
    return files


class SummonDependenciesTests(unittest.TestCase):
    def test_multiball_action_support_and_element_return_actual_graph_edges(self):
        files = fixture()
        before = copy.deepcopy(files)
        mapped = deps.resolve_command_resources(summon_command(7.0), element=3, reference_files=files)
        self.assertEqual(files, before)
        refs = {ref["logical"]: ref for ref in mapped["references"]}
        for path in ("character/summon_body/pixelart/pixelart",
                     "battle/action/summon_body.action.dsl.amf3.deflate",
                     "battle/action/support.action.dsl.amf3.deflate"):
            self.assertIn(path, refs)
            self.assertEqual(refs[path]["context"]["element"], 5)
        support = refs["battle/action/support.action.dsl.amf3.deflate"]
        self.assertEqual(support["definitionEvidence"]["parents"][1]["sha256"],
                         hashlib.sha256(files[summons.ABILITY_TABLE]).hexdigest())
        self.assertEqual(support["definitionEvidence"]["parents"][1]["key"], "31")
        self.assertNotIn("bucket", support["context"])
        self.assertIn({"kind": "Ability", "key": "31", "pointer": "/2/support_skill1", "domain": "summon"},
                      mapped["requiredDefinitions"])
        self.assertTrue(any("dynamicActionSkillName" in p["reason"] for p in mapped["problems"]))
        self.assertTrue(mapped["handled"])

    def test_illegal_support_keeps_problem_and_known_edges(self):
        files = fixture()
        ability = row("ability")
        ability[6], ability[47], ability[71] = "", "629", "battle/action/support"
        files[summons.ABILITY_TABLE] = flat({"31": ability})
        mapped = deps.resolve_command_resources(summon_command(), reference_files=files)
        self.assertTrue(any("原生行不合法" in p["reason"] and p["domain"] == "ability" for p in mapped["problems"]))
        self.assertIn("battle/action/support.action.dsl.amf3.deflate", [r["logical"] for r in mapped["references"]])

    def test_one_missing_union_source_retains_edges_without_closure(self):
        files = fixture()
        del files[summons.MULTIBALL_TABLES[0]]
        mapped = deps.resolve_command_resources(summon_command(), reference_files=files)
        self.assertIn("character/summon_body/pixelart/pixelart", [r["logical"] for r in mapped["references"]])
        self.assertTrue(any("合并源未冻结" in p["reason"] for p in mapped["problems"]))
        self.assertTrue(all(item["status"] != "complete" for item in mapped["coverage"]))

    def test_duplicate_union_key_never_chooses_a_precedence(self):
        files = fixture()
        files[summons.MULTIBALL_TABLES[0]] = flat({"7": multiball()})
        mapped = deps.resolve_command_resources(summon_command(), reference_files=files)
        self.assertTrue(any("重复键" in p["reason"] for p in mapped["problems"]))
        self.assertNotIn("character/summon_body/pixelart/pixelart", [r["logical"] for r in mapped["references"]])

    def test_bad_key_and_parent_path_are_pending_without_guessing(self):
        for key in (True, -1, 7.5, float("nan"), "7/../1"):
            mapped = deps.resolve_command_resources(summon_command(key), reference_files=fixture())
            self.assertTrue(mapped["problems"])
            self.assertNotIn("character/summon_body/pixelart/pixelart", [r["logical"] for r in mapped["references"]])
        files = fixture()
        fields = multiball()
        fields[1] = "../victim"
        files[summons.MULTIBALL_TABLES[1]] = flat({"7": fields})
        mapped = deps.resolve_command_resources(summon_command(), reference_files=files)
        self.assertTrue(any("逻辑路径无效" in p["reason"] for p in mapped["problems"]))

    def test_funnel_body_marker_registered_actions_and_conditional_gauges(self):
        fields = [""] * 139
        fields[0], fields[1] = "2", "battle/funnel/body"
        fields[23], fields[24], fields[37] = "battle/funnel/marker", "battle/funnel/shadow", "routine"
        fields[25:29] = ["battle/check/damage_back", "(None)", "(None)", "battle/check/hit_fore"]
        fields[89] = "battle/action/funnel_a,battle/action/funnel_b"
        state = [""] * 29
        state[16], state[22], state[27], state[28] = "10", "20", "(None)", "(None)"
        files = {summons.FUNNEL_TABLES[0]: flat({}), summons.FUNNEL_TABLES[1]: nested("test", {"1": fields}),
                 summons.FUNNEL_STATE_TABLES[0]: flat({}), summons.FUNNEL_STATE_TABLES[1]: state_table("routine", state)}
        mapped = deps.resolve_command_resources(["SpawnFunnel", ["Funnel", "test"]], reference_files=files)
        refs = {r["logical"]: r for r in mapped["references"]}
        self.assertEqual(refs["battle/funnel/body"]["context"]["element"], 1)
        self.assertEqual(refs["battle/funnel/marker.timeline.amf3.deflate"]["context"]["kind"], "timeline")
        self.assertIn("battle/action/funnel_b.action.dsl.amf3.deflate", refs)
        self.assertIn("battle/common/layer1/hostile_damage_gauge", refs)
        self.assertIn("battle/uncommon/layer1/trial_gauge/trial_gauge_numbers", refs)
        self.assertIn("battle/check/damage_back", refs)
        self.assertIn("battle/check/hit_fore", refs)
        self.assertTrue(any("watch" in p["reason"] for p in mapped["problems"]))

    def test_zako_inherited_body_keeps_unknown_own_element(self):
        fields = [""] * 40
        fields[0], fields[10], fields[11], fields[17] = "0", "battle/zako/marker", "battle/zako/shadow", "routine"
        fields[2:8] = [f"battle/zako/body{i}" for i in range(6)]
        fields[30] = "battle/action/zako"
        files = {summons.ZAKO_TABLES[0]: flat({}), summons.ZAKO_TABLES[1]: nested("test", {"1": fields})}
        mapped = deps.resolve_command_resources(["SpawnFunnel", ["Zako", "test"]], element=4, reference_files=files)
        own = [r for r in mapped["references"] if r["logical"].startswith("battle/zako/body") or ".action.dsl." in r["logical"]]
        self.assertEqual(len(own), 7)
        self.assertTrue(all(r["context"]["element"] is None for r in own))
        self.assertTrue(any("quest element" in p["reason"] for p in mapped["problems"]))

    def test_one_bad_frozen_level_does_not_hide_the_next_valid_level(self):
        invalid = [""] * 40
        invalid[0] = "unknown"
        valid = [""] * 40
        valid[0], valid[1], valid[10], valid[11], valid[17] = "3", "battle/body/good", "battle/good/marker", "battle/good/shadow", "routine"
        valid[30] = "battle/action/good"
        files = {summons.ZAKO_TABLES[0]: flat({}),
                 summons.ZAKO_TABLES[1]: nested("test", {"0": invalid, "1": valid})}
        mapped = deps.resolve_command_resources(["SpawnFunnel", ["Zako", "test"]], reference_files=files)
        self.assertIn("battle/body/good", [r["logical"] for r in mapped["references"]])
        self.assertIn("battle/action/good.action.dsl.amf3.deflate", [r["logical"] for r in mapped["references"]])
        self.assertTrue(any(p["pointer"].endswith("/levels/0") and "字段/element" in p["reason"] for p in mapped["problems"]))

    def test_standard_enemy_dsl_is_typed_pending_never_guessed_as_action(self):
        files = {summons.STANDARD_TABLES[0]: flat({}), summons.STANDARD_TABLES[1]: nested("test", {"1": ["battle/enemy/program"]})}
        mapped = deps.resolve_command_resources(["SpawnFunnel", ["StandardFunnel", "test"]], reference_files=files)
        self.assertEqual([(r["logical"], r["context"]["kind"]) for r in mapped["references"]],
                         [("battle/enemy/program.esdl.amf3.deflate", "enemy-dsl")])
        self.assertTrue(any(d["kind"] == "EnemyDsl" and d["key"] == "battle/enemy/program" for d in mapped["requiredDefinitions"]))
        self.assertTrue(mapped["problems"])

    def test_nested_selected_rows_share_one_inflate_budget(self):
        child = orderedmap_raw(["1", "2"], [zlib.compress(csv_bytes(["x"*70])), zlib.compress(csv_bytes(["y"*70]))])
        raw = orderedmap_raw(["key"], [child])
        with mock.patch.object(deps, "LIMIT", 130):
            with self.assertRaisesRegex(ValueError, "超限"):
                deps._DefinitionReader({"t": raw}).nested_union_rows(("t",), "key")

    def test_real_retained_multiball_bytes_optional_fixture(self):
        import os
        import zipfile
        path = os.environ.get("STUDIO_NATIVE_COMPLEX_REFERENCE")
        if not path:
            self.skipTest("explicit frozen technical archive required")
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        mapped = deps.resolve_command_resources(summon_command(1110022), reference_files=files)
        paths = {r["logical"] for r in mapped["references"]}
        self.assertIn("character/pirates/pixelart/pixelart", paths)
        support = [d["key"] for d in mapped["requiredDefinitions"] if d["kind"] == "Ability"]
        self.assertEqual(support, ["90002", "90003"])
        self.assertTrue(any("/support_skill1/rows/0" in r["pointer"] for r in mapped["references"]))
        self.assertTrue(any(c["code"] == "205" and c["status"] == "included" for c in mapped["coverage"]))
        self.assertFalse(mapped["problems"])


if __name__ == "__main__":
    unittest.main()
