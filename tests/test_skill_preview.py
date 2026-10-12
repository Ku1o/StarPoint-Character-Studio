import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skill_preview import plan_program, effect_path, preview_plans, author_to_world, validate_preview, anchor_state_report


def effect(ref, name="normal", ticks=30, scale=6, kind="once", begin=1):
    return {"id": ref.rsplit("/", 1)[-1] + "_" + name, "name": name, "kind": kind, "frameScale": scale,
            "native": {"path": effect_path(ref), "sequence": name, "begin": begin, "end": begin+ticks-1}, "clips": [], "nativeFrames": [[{}]] * ticks}


def show(ref, life=None, scale=None, label="effect"):
    return ["ShowEffect", label, ["SpecifyEffectDirectly", ref], -18, ["ForesideOfCharacter"],
            life or ["PlayOnlyFirstSequence"], ["AB"], 0, 0, 0, False, False,
            ["Some", [{"min": scale, "max": scale}]] if scale is not None else ["None"]]


def block(*commands):
    return ["Block", [["Command", c] for c in commands]]


class SkillPlanTests(unittest.TestCase):
    def test_normal_cast_restore_requires_explicit_mapping_and_keeps_native_deferred(self):
        self.assertEqual(anchor_state_report({})["status"], "deferred")
        contract = {"sourceCanvas": [64, 64], "bodyAnchor": [32, 32], "feetAnchor": [32, 48]}
        p = {"animations": [{"id": key, "frameScale": 6, "actionContract": copy.deepcopy(contract), "clips": [{"hold": 1}]}
                            for key in ("normal", "cast", "restore")],
             "skillPreview": {"actionStates": {"normal": "normal", "cast": "cast", "restore": "restore", "source": "author-mapping"}}}
        self.assertTrue(anchor_state_report(p)["declaredAnchorConsistency"])
        self.assertFalse(anchor_state_report(p)["nativeVerified"])
        p["animations"][1]["actionContract"]["feetAnchor"] = [32, 49]
        self.assertFalse(anchor_state_report(p)["declaredAnchorConsistency"])

    def test_optional_preview_metadata_rejects_bad_values_and_keeps_extensions(self):
        p = {"skillPreview": {"custom": [1]}, "effects": [{"coordinateDeclaration": {"custom": {"v": 2}}}]}
        original = copy.deepcopy(p); validate_preview(p); self.assertEqual(p, original)
        for bad in ({"canvas": [-1, 2]}, {"anchor": [1]}, {"partsScale": True}, {"source": 3}):
            with self.assertRaises(ValueError):
                validate_preview({"effects": [{"coordinateDeclaration": bad}]})

    def test_ball_hide_is_known_invalid_and_does_not_hide_actor(self):
        p = {"animations": [{"id": "idle", "slot": "neutral", "clips": [{"hold": 6}]}]}
        result = plan_program(p, {"tree": block(["HideCharacter", -18, 48])})
        self.assertEqual([t["start"] for t in result["scene"]["tracks"] if t["type"] == "actor"], [0])
        self.assertEqual(result["deferred"][0]["status"], "known-invalid")
        self.assertTrue(any("原生无效" in n for n in result["notes"]))
        self.assertFalse(result["scene"]["source"]["trust"]["nativeVerified"])

    def test_declared_author_canvas_recipe_is_not_native_acceptance(self):
        declaration = {"canvas": [180, 320], "anchor": [90, 160], "partsScale": 6, "source": "controlled-vyrn-recipe"}
        self.assertEqual([author_to_world(declaration, [90, y])["localWorldOffset"][1] for y in (80, 132, 184, 236)], [-480, -168, 144, 456])
        self.assertFalse(author_to_world(declaration, [90, 80])["nativeVerified"])
        self.assertEqual(author_to_world({}, [90, 80])["status"], "unknown")

    def test_member_follow_zone_lock_and_hit_binding_are_distinct(self):
        a = "battle/effect/a/create"
        p = {"effects": [effect(a)], "skillPreview": {"subjectBindings": {"-123": {"name": "ZoneCenter", "source": "fixture-binding"}}}}
        member, zone = show(a), show(a)
        member[3], member[10] = -17, True
        zone[3] = -123
        result = plan_program(p, {"tree": block(member, zone)})
        coords = [t["source"]["coordinate"] for t in result["scene"]["tracks"]]
        self.assertEqual([c["subjectName"] for c in coords], ["Member", "ZoneCenter"])
        self.assertTrue(coords[0]["follow"])
        self.assertTrue(coords[1]["locked"])
        self.assertFalse(any(c["nativeVerified"] for c in coords))

    def test_unknown_subject_stays_deferred_even_with_visible_reference(self):
        a = "battle/effect/a/create"; command = show(a); command[3] = -999
        result = plan_program({"effects": [effect(a)]}, {"tree": block(command)})
        self.assertEqual(result["visualEvents"], 1)
        self.assertEqual(result["scene"]["tracks"][0]["source"]["coordinate"]["status"], "deferred")
        self.assertTrue(result["deferred"])

    def test_wait_hiding_first_sequence_and_override_scale(self):
        a, b = "battle/effect/a/jump", "battle/effect/a/blast"
        p = {"animations": [{"id": "idle", "slot": "neutral", "clips": [{"hold": 6}]}],
             "effects": [effect(a), effect(b), effect(b, "angle_45")]}
        tree = block(["HideCharacter", -17, 48], show(a), ["Wait", 44, "*", block(show(b, scale=8))])
        original = copy.deepcopy(tree)
        result = plan_program(p, {"logical": "test", "tree": tree})
        effects = [t for t in result["scene"]["tracks"] if t["type"] == "effect"]
        self.assertEqual([(t["start"], t["ref"]) for t in effects], [(0, "jump_normal"), (44, "blast_normal")])
        self.assertAlmostEqual(effects[1]["scale"] * p["effects"][1]["frameScale"], 8)
        self.assertEqual([t["start"] for t in result["scene"]["tracks"] if t["type"] == "actor"], [48])
        self.assertEqual(tree, original)

    def test_creation_callback_is_immediate_hit_callback_is_deferred(self):
        a, b = "battle/effect/a/create", "battle/effect/a/hit"
        p = {"effects": [effect(a), effect(b)]}
        command = ["CreateHitArea"] + [None] * 23
        command[2:6] = [-18, ["AB"], 7, -12]
        command[12], command[19] = ["Single"], 0
        command[20], command[23] = block(show(a)), block(show(b))
        command[20][1][0][1][3] = 0
        result = plan_program(p, {"tree": block(["Wait", 9, "*", block(command)])})
        self.assertEqual(result["visualEvents"], 1)
        self.assertEqual(len(result["deferred"]), 1)
        t = result["scene"]["tracks"][0]
        self.assertEqual((t["start"], t["x"], t["y"]), (9, 7, -12))

    def test_once_holds_until_lifetime_then_end(self):
        a = "battle/effect/a/loop"
        p = {"effects": [effect(a, "normal", 10), effect(a, "end", 4, begin=11)]}
        result = plan_program(p, {"tree": block(show(a, ["SpecifyEffectLifetimeDirectly", 87]))})
        self.assertEqual([(t["ref"], t["start"], t["end"]) for t in result["scene"]["tracks"]],
                         [("loop_normal", 0, 87), ("loop_end", 87, 91)])
        self.assertEqual([t["playMode"] for t in result["scene"]["tracks"]], ["once", "once"])

    def test_snapping_directions_are_replacements_and_do_not_fade_to_end(self):
        a = "battle/effect/a/beam"
        p = {"effects": [effect(a, "angle_45", 10, begin=11), effect(a, "end", 4, begin=21), effect(a, "normal", 10)]}
        result = plan_program(p, {"tree": block(show(a, ["SpecifyEffectLifetimeDirectly", 87]))})
        self.assertEqual([(t["ref"], t["start"], t["end"]) for t in result["scene"]["tracks"]], [("beam_normal", 0, 87)])
        self.assertTrue(any("方向" in note for note in result["notes"]))

    def test_pass_follows_contiguous_global_frames_not_array_order(self):
        a = "battle/effect/a/fire"
        p = {"effects": [effect(a, "loop", 180, kind="loop", begin=21), effect(a, "end", 4, begin=201),
                         effect(a, "start", 20, kind="pass")]}
        result = plan_program(p, {"tree": block(show(a, ["SpecifyEffectLifetimeDirectly", 120]))})
        tracks = result["scene"]["tracks"]
        self.assertEqual([(t["ref"], t["start"], t["end"], t["playMode"]) for t in tracks],
                         [("fire_start", 0, 20, "pass"), ("fire_loop", 20, 120, "loop"), ("fire_end", 120, 124, "once")])
        self.assertEqual(len({t["instanceId"] for t in tracks}), 1)
        self.assertEqual(tracks[1]["phaseOf"], tracks[0]["id"])
        self.assertEqual(tracks[2]["endingOf"], tracks[0]["id"])

    def test_pass_gap_is_deferred_instead_of_guessing_successor(self):
        a = "battle/effect/a/fire"
        p = {"effects": [effect(a, "start", 20, kind="pass"), effect(a, "loop", 10, kind="loop", begin=25)]}
        result = plan_program(p, {"tree": block(show(a, ["SpecifyEffectLifetimeDirectly", 120]))})
        self.assertEqual([(t["start"], t["end"]) for t in result["scene"]["tracks"]], [(0, 20)])
        self.assertTrue(result["deferred"])

    def test_hide_cuts_whole_instance_including_future_phases_and_moves_end(self):
        a = "battle/effect/a/fire"
        p = {"effects": [effect(a, "start", 20, kind="pass"), effect(a, "loop", 180, kind="loop", begin=21), effect(a, "end", 4, begin=201)]}
        for hide_at, expected in [(0, [("fire_end", 0, 4)]), (10, [("fire_start", 0, 10), ("fire_end", 10, 14)]),
                                  (40, [("fire_start", 0, 20), ("fire_loop", 20, 40), ("fire_end", 40, 44)])]:
            result = plan_program(p, {"tree": block(show(a, ["SpecifyEffectLifetimeDirectly", 120]), ["Wait", hide_at, "*", block(["HideEffect", "effect"])])})
            self.assertEqual([(t["ref"], t["start"], t["end"]) for t in result["scene"]["tracks"]], expected)

    def test_hide_does_not_cancel_a_later_instance_with_the_same_label(self):
        a = "battle/effect/a/fire"
        p = {"effects": [effect(a)]}
        result = plan_program(p, {"tree": block(show(a), ["Wait", 50, "*", block(show(a))], ["Wait", 10, "*", block(["HideEffect", "effect"])])})
        self.assertEqual([(t["start"], t["end"]) for t in result["scene"]["tracks"]], [(0, 10), (50, 80)])

    def test_stop_freezes_first_frame_for_whole_lifetime(self):
        a = "battle/effect/a/static"
        result = plan_program({"effects": [effect(a, ticks=5, kind="stop")]}, {"tree": block(show(a, ["SpecifyEffectLifetimeDirectly", 80]))})
        t = result["scene"]["tracks"][0]
        self.assertEqual((t["start"], t["end"], t["playMode"]), (0, 80, "stop"))

    def test_first_sequence_lifetime_fades_without_entering_later_loop(self):
        a = "battle/effect/a/fire"
        p = {"effects": [effect(a, "start", 20, kind="pass"), effect(a, "loop", 180, kind="loop", begin=21), effect(a, "end", 4, begin=201)]}
        result = plan_program(p, {"tree": block(show(a))})
        self.assertEqual([(t["ref"], t["start"], t["end"]) for t in result["scene"]["tracks"]], [("fire_start", 0, 20), ("fire_end", 20, 24)])

    def test_legacy_project_reads_reference_coordinates_without_saving(self):
        a = "battle/effect/a/fire"
        p = {"effects": [effect(a, "loop", 180, kind="loop", begin=21), effect(a, "start", 20, kind="pass")]}
        for e in p["effects"]:
            del e["native"]["begin"], e["native"]["end"]
        original = copy.deepcopy(p)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            timeline = base / "reference" / effect_path(a).replace(".parts.json", ".timeline.json")
            timeline.parent.mkdir(parents=True)
            timeline.write_text(json.dumps({"sequences": [{"name": "loop", "begin": 21, "end": 200}, {"name": "start", "begin": 1, "end": 20}]}), "utf-8")
            deps = base / "reference/data_readable/skill_dependencies.json"
            deps.parent.mkdir()
            deps.write_text(json.dumps({"programs": [{"tree": block(show(a, ["SpecifyEffectLifetimeDirectly", 120]))}]}), "utf-8")
            class Store:
                def load(self, pid): return copy.deepcopy(p)
                def directory(self, pid): return base
            result = preview_plans(Store(), "test")["programs"][0]
        self.assertEqual([(t["ref"], t["start"], t["end"]) for t in result["scene"]["tracks"]], [("fire_start", 0, 20), ("fire_loop", 20, 120)])
        self.assertEqual(p, original)

    def test_system_feedback_is_explicitly_deferred(self):
        result = plan_program({}, {"tree": block(["Anything", ["GenericHealHitEffect"]], ["Anything", ["GenericConditionHitEffect"]])})
        self.assertEqual(result["visualEvents"], 0)
        self.assertEqual(len(result["deferred"]), 2)
        self.assertTrue(any("系统反馈" in note for note in result["notes"]))

    def test_element_resolution_and_repeat_bound(self):
        base = "battle/effect/generic/buff"
        logical = base + "/buff_yellow/buff_yellow"
        p = {"identity": {"element": "雷"}, "effects": [effect(logical)]}
        command = show(logical)
        command[2] = ["ResolveByElement", base, 255]
        result = plan_program(p, {"tree": block(["Repeat", 3, 100000, "*", block(command)])})
        self.assertEqual(result["visualEvents"], 128)
        self.assertEqual(result["scene"]["tracks"][1]["start"], 3)
        self.assertTrue(result["notes"])

    def test_unknown_target_branch_stays_deferred(self):
        a = "battle/effect/a/burst"
        result = plan_program({"effects": [effect(a)]}, {"tree": block(["FindNearSubjects", 0, block(show(a))])})
        self.assertEqual(result["visualEvents"], 0)
        self.assertEqual(len(result["deferred"]), 1)


if __name__ == "__main__":
    unittest.main()
