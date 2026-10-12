import copy
import io
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from character_audit import report, compiled_report, validate, parts_metrics


def dependency(logical="a", **extra):
    return {"logical": logical, "width": 10.2, "height": 20.2, "bucket": "BattlePart",
            "collection": "main", "layer": 0, "source": "test-trace", "requester": "caster",
            "category": "skill", "collectionDedupe": "logical", **extra}


class CharacterAuditTests(unittest.TestCase):
    def test_closure_evidence_requires_source_and_never_claims_native_verification(self):
        for evidence in ("a-file", {}, {"source": False}):
            with self.assertRaises(ValueError):
                report({"characterAudit": {"closureEvidence": evidence}})
        p = {"characterAudit": {"closureEvidence": {"source": "local-receipt", "verified": True, "future": {"preserve": True}}}}
        result = report(p)
        self.assertTrue(result["closure"]["evidenceProvided"])
        self.assertFalse(result["closure"]["completeCharacterTotal"])
        self.assertEqual(result["closure"]["evidence"]["future"], {"preserve": True})

    def test_verified_static_character_dimensions_recalculate_reference(self):
        cases = [([(1024, 19), (1024, 231)], [(168, 420), (216, 130), (245, 205), (536, 1254)], 1087977, 827373),
                 ([(1024, 106), (1024, 107)], [(168, 968)], 387542, 164900)]
        # Fixture dimensions are the nine observed 1.4.135 static targets;
        # unknown implicit dependencies stay outside this static subtotal.
        for pixelart, skill, expected, skill_expected in cases:
            deps = [dependency(str(i), width=w, height=h, category=category)
                    for i, (category, (w, h)) in enumerate([*(('pixelart', pair) for pair in pixelart), *(('skill', pair) for pair in skill)])]
            result = report({"characterAudit": {"dependencies": deps}})
            self.assertEqual(result["layers"]["0"]["knownAreaPixels"], expected)
            self.assertEqual(sum(d["paddedAreaPixels"] for d in result["dependencies"] if d["category"] == "skill"), skill_expected)
            self.assertFalse(result["closure"]["completeCharacterTotal"])

    def test_ceil_and_total_margin_once(self):
        result = report({"characterAudit": {"dependencies": [dependency()]}})
        self.assertEqual(result["layers"]["0"]["knownAreaPixels"], 13 * 23)
        self.assertFalse(result["closure"]["complete"])
        self.assertFalse(result["gameReady"])

    def test_dedupe_within_collection_only_and_keep_requesters(self):
        result = report({"characterAudit": {"dependencies": [dependency(), dependency(requester="unison"),
                                       dependency(bucket="Common"), dependency(collection="Attention"),
                                       dependency(collectionDedupe="none")]}})
        self.assertEqual(result["layers"]["0"]["knownAreaPixels"], 4 * 13 * 23)
        self.assertEqual(result["dependencies"][1]["requester"], "unison")
        self.assertEqual(result["dependencies"][1]["deduplicatedTo"], 0)

    def test_scope_selects_main_unison_leader_forms(self):
        deps = [dependency(str(i), roles=[role], forms=["normal"], category=cat)
                for i, (role, cat) in enumerate([("main", "pixelart"), ("unison", "skill"), ("leader", "powerFlip")])]
        result = report({"characterAudit": {"scope": {"roles": ["unison"], "forms": ["normal"]}, "dependencies": deps}})
        self.assertEqual([d["category"] for d in result["dependencies"]], ["skill"])

    def test_ui_independent_and_unknown_not_merged(self):
        deps = [dependency(), dependency("ui", category="ui", layer=1),
                dependency("cut", category="cutin", layer="independent"), dependency("unknown", layer=None)]
        result = report({"characterAudit": {"dependencies": deps}})
        self.assertEqual(result["layers"]["0"]["knownAreaPixels"], 299)
        self.assertEqual(result["layers"]["1"]["knownAreaPixels"], 299)
        self.assertEqual(len(result["independent"]), 1)
        self.assertEqual(len(result["unknown"]), 1)

    def test_unknown_and_scope_closed_do_not_make_complete_total(self):
        result = report({"characterAudit": {"scope": {"closed": True, "roles": ["main"], "forms": ["normal"]},
                                            "dependencies": [dependency(unknown="ability closure missing")]}})
        self.assertFalse(result["closure"]["complete"])
        self.assertEqual(result["layers"]["0"]["knownAreaPixels"], 0)
        self.assertTrue(result["unknown"])
        self.assertFalse(report({})["closure"]["complete"])

    def test_closed_empty_matching_scope_is_incomplete(self):
        result = report({"characterAudit": {"scope": {"closed": True, "roles": ["main"], "forms": ["normal"]},
                                            "dependencies": [dependency(roles=["unison"])]}})
        self.assertFalse(result["closure"]["complete"])

    def test_invalid_known_fields_rejected_unknown_fields_preserved(self):
        p = {"characterAudit": {"custom": {"v": 9}, "dependencies": [dependency(custom=[1, 2])]}}
        before = copy.deepcopy(p)
        validate(p)
        self.assertEqual(p, before)
        for invalid in ({"width": -1}, {"width": float("nan")}, {"layer": True}, {"roles": ["fake"]}, {"collectionDedupe": "global"}):
            with self.assertRaises(ValueError):
                validate({"characterAudit": {"dependencies": [dependency(**invalid)]}})

    def test_area_does_not_prove_shape_packing(self):
        result = report({"characterAudit": {"dependencies": [dependency(width=4095, height=1)]}})
        self.assertTrue(result["layers"]["0"]["shapeLimitExceeded"])
        self.assertFalse(result["nativePackingVerified"])
        self.assertEqual(result["optimizer"]["status"], "pending")

    def test_compiled_png_reads_whole_sheet_and_never_guesses_layer(self):
        image = Image.new("RGBA", (13, 17)); buffer = io.BytesIO(); image.save(buffer, "PNG")
        p = {}; before = copy.deepcopy(p)
        result = compiled_report(p, {"battle/effect/a.png": buffer.getvalue()})
        self.assertEqual(result["compiledSheets"][0]["paddedAreaPixels"], 15 * 19)
        self.assertEqual(result["assetBytes"], len(buffer.getvalue()))
        self.assertEqual(result["layers"]["0"]["knownAreaPixels"], 0)
        self.assertTrue(result["unknown"])
        self.assertEqual(p, before)

    def test_compiled_declared_mapping_and_parts_workload(self):
        image = Image.new("RGBA", (13, 17)); buffer = io.BytesIO(); image.save(buffer, "PNG")
        p = {"characterAudit": {"dependencies": [dependency("battle/effect/a", width=1, height=1)]}}
        result = compiled_report(p, {"battle/effect/a.png": buffer.getvalue()})
        self.assertEqual(result["layers"]["0"]["knownAreaPixels"], 285)
        parts = {"i": [{"p": "x", "s": False}], "a": [3], "t": [{"a": 4096, "b": 0, "c": 0, "d": 4096, "x": 0, "y": 0}],
                 "g": [{"t": 2, "s": [{"s": 0, "i": 0, "l": [{"m": 255, "t": 2}]}]}]}
        metric = parts_metrics(parts)
        self.assertEqual(metric["prebuiltInstances"], 3)
        self.assertEqual(metric["leafCommandsPerTick"], [1, 1])
        self.assertIsNone(metric["gpuDrawCalls"])


if __name__ == "__main__":
    unittest.main()
