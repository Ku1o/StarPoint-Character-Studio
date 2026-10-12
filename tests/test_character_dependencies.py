import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from character_dependencies import analyze, analyze_project, resource_catalog, validate, canonical, DOMAINS


def record(kind, data=None, **extra):
    return {"kind": kind, "data": data, "sha256": hashlib.sha256(canonical(data)).hexdigest(), "source": "frozen-fixture", **extra}


def root(logical="program", **extra):
    return {"logical": logical, "requester": "caster", "source": "frozen-fixture", "bucket": "BattlePart",
            "collection": "main", "layer": 0, "roles": ["main"], "forms": ["base"], **extra}


def fixture():
    effect = "battle/effect/test/effect"
    cell = "battle/effect/test/.gen/0"
    catalog = {
        "program": record("dsl", ["Block", [["Command", ["ShowEffect", "label", ["SpecifyEffectDirectly", effect]]]]]),
        effect: record("effect", {"parts": "parts", "timeline": "timeline"}),
        "parts": record("parts", {"i": [{"p": cell}], "g": [{"t": 1, "s": [{"s": 0, "i": 0, "l": [{"t": 1}]}]}]}),
        "timeline": record("timeline", {"sounds": [{"path": "sound_effect/test"}]}),
        "battle/effect/test/test.atlas.json": record("atlas", [{"n": cell, "x": 0, "y": 0, "w": 4, "h": 4}]),
        "battle/effect/test/test.png": record("texture", width=4, height=4),
        "sound_effect/test.mp3": record("sound"),
    }
    return catalog


class DependencyClosureTests(unittest.TestCase):
    def test_common_frame_uses_fixed_layer_sheet_and_keeps_transform_and_missing_frames(self):
        from studio_core import amf_bytes
        for layer in (0, 1):
            sheet = f'battle/common/layer{layer}'
            logical = sheet + '/flipper.frame.amf3.deflate'
            prefix = sheet + '/.gen/flipper/f'
            frame = {'name': prefix, 'scale': 6, 'smoothing': False, 'x': -62, 'y': -35}
            image = Image.new('RGBA', (4, 4)); output = io.BytesIO(); image.save(output, 'PNG')
            files = {logical: amf_bytes(frame), sheet + '.atlas.amf3.deflate':
                     amf_bytes([{'n': prefix + '0001', 'x': 0, 'y': 0, 'w': 4, 'h': 4}]),
                     sheet + '.png': output.getvalue()}
            before = copy.deepcopy(files)
            result = analyze([root(logical, category='shared')], resource_catalog(files))
            self.assertTrue(result['closure']['compiledResourceClosure'])
            self.assertEqual(files, before)
            self.assertEqual(resource_catalog(files)[logical]['data'], frame)
            self.assertEqual({row['logical'] for row in result['dependencies']},
                             {logical, sheet + '.atlas.amf3.deflate', sheet + '.png', prefix + '0001'})
            files[logical] = amf_bytes({**frame, 'name': sheet + '/.gen/not-found/f'})
            result = analyze([root(logical)], resource_catalog(files))
            self.assertFalse(result['closure']['compiledResourceClosure'])
            self.assertTrue(any('前缀' in row['reason'] for row in result['missingReferences']))
        unsupported = record('frame', {**frame, 'name': 'battle/common/layer2/.gen/flipper/f'})
        result = analyze([root('battle/common/layer2/flipper.frame.json')],
                         {'battle/common/layer2/flipper.frame.json': unsupported})
        self.assertFalse(result['closure']['compiledResourceClosure'])
        self.assertTrue(result['unsupported'])

    def test_enemy_dsl_keeps_physical_identity_and_cannot_masquerade_as_action_dsl(self):
        logical='battle/enemy/sample.esdl.amf3.deflate';raw=b'opaque retained enemy program'
        catalog=resource_catalog({logical:raw})
        result=analyze([root(logical,kind='enemy-dsl',category='summon')],catalog)
        self.assertEqual(result['counts']['missing'],0)
        self.assertEqual(result['dependencies'][0]['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['dependencies'][0]['kind'],'enemy-dsl')
        self.assertNotIn('decodeError',catalog[logical])
        self.assertIn('EnemyDsl',result['unsupported'][0]['reason'])
        self.assertFalse(result['closure']['compiledResourceClosure'])

    def test_deep_parts_and_resource_chains_return_gaps_without_crashing_or_hiding_other_roots(self):
        groups=[{'s':[{'s':2147483648,'i':i+1}]} for i in range(1200)]+[{'s':[]}]
        catalog={'parts':record('parts',{'i':[],'g':groups}),'ordinary':record('sound')}
        result=analyze([root('parts'),root('ordinary')],catalog)
        self.assertFalse(result['closure']['compiledResourceClosure'])
        self.assertTrue(any('有界上限' in row['reason'] for row in result['unsupported']))
        self.assertIn('ordinary',{row['logical'] for row in result['dependencies']})
        chain={f'node{i}':record('references',{'references':[f'node{i+1}']}) for i in range(1100)}
        chain['node1100']=record('sound');chain['ordinary']=record('sound')
        result=analyze([root('node0'),root('ordinary')],chain)
        self.assertFalse(result['closure']['compiledResourceClosure'])
        self.assertTrue(any('有界上限' in row['reason'] for row in result['unsupported']))
        self.assertIn('ordinary',{row['logical'] for row in result['dependencies']})

    def test_same_program_for_two_summon_elements_keeps_both_resource_branches(self):
        command=["CreateNormalAttack",2,255,[],[],140,[],[],False,False,False,False,False,[],[],["Coarse"],True]
        catalog={"program":record("dsl",["Command",command])}
        result=analyze([root(element=0),root(element=1)],catalog,{"element":5})
        missing={row['logical'] for row in result['missingReferences']}
        self.assertEqual(missing,{
            'battle/effect/hit/normal_damage/coarse/coarse_red/coarse_red',
            'battle/effect/hit/normal_damage/coarse/coarse_blue/coarse_blue'})
        self.assertEqual({c['element'] for c in result['dependencies'][0]['contexts']},{0,1})
        self.assertEqual(result['unresolvedDynamic'],[])
        for invalid in ({},True,7):
            with self.subTest(element=invalid),self.assertRaisesRegex(ValueError,'element'):
                analyze([root(element=invalid)],catalog)

    def test_amf_rejects_trailing_compressed_or_decoded_data_and_truncation(self):
        def packed(data):
            encoder = zlib.compressobj(wbits=-15)
            return encoder.compress(data) + encoder.flush()
        invalid = [packed(b"\x01\x01"), packed(b"\x01") + b"junk", packed(b"\x01") + packed(b"\x01"),
                   packed(b"\x06\x07x"), packed(b"\x05abc")]
        for raw in invalid:
            with self.subTest(raw=raw):
                result = analyze([root("bad.timeline.amf3.deflate")], resource_catalog({"bad.timeline.amf3.deflate": raw}))
                self.assertFalse(result["closure"]["compiledResourceClosure"])
                self.assertTrue(result["unsupported"])

    def test_amf_declared_huge_array_object_and_deep_tree_are_bounded(self):
        def packed(data):
            encoder = zlib.compressobj(wbits=-15)
            return encoder.compress(data) + encoder.flush()
        invalid = [b"\x09\xff\xff\xff\xff\x01", b"\x0a\xff\xff\xff\xff\x01",
                   (b"\x09\x03\x01" * 170) + b"\x01"]
        for data in invalid:
            result = resource_catalog({"bad.parts.amf3.deflate": packed(data)})
            self.assertIn("decodeError", result["bad.parts.amf3.deflate"])
            self.assertFalse(analyze([root("bad.parts.amf3.deflate")], result)["closure"]["fullyClosed"])

    def test_json_duplicate_keys_nonfinite_and_large_or_deep_container_rejected(self):
        for raw in (b'{"sounds":[],"sounds":[]}', b'{"sounds":[],"bad":NaN}', b"[" * 170 + b"0" + b"]" * 170,
                    json.dumps([None] * 100001).encode()):
            catalog = resource_catalog({"bad.timeline.json": raw})
            self.assertIn("decodeError", catalog["bad.timeline.json"])
            self.assertFalse(analyze([root("bad.timeline.json")], catalog)["closure"]["compiledResourceClosure"])

    def test_png_accepts_only_real_or_game_header_and_rejects_crc_tail_truncation(self):
        image = Image.new("RGBA", (4, 4)); output = io.BytesIO(); image.save(output, "PNG")
        valid = output.getvalue()
        for raw in (valid, b"\x89png\r\n\x1a\n" + valid[8:]):
            self.assertTrue(analyze([root("sheet.png")], resource_catalog({"sheet.png": raw}))["closure"]["compiledResourceClosure"])
        corrupt = bytearray(valid); corrupt[16] ^= 1
        for raw in (b"NOTPNG!!" + valid[8:], valid[:-1], valid + b"tail", bytes(corrupt)):
            result = analyze([root("sheet.png")], resource_catalog({"sheet.png": raw}))
            self.assertFalse(result["closure"]["compiledResourceClosure"])
            self.assertTrue(result["unsupported"])

    def test_png_pixel_budget_checks_before_image_allocation(self):
        image = Image.new("RGBA", (4, 4)); output = io.BytesIO(); image.save(output, "PNG")
        raw = bytearray(output.getvalue())
        raw[16:20] = (60000).to_bytes(4, "big"); raw[20:24] = (60000).to_bytes(4, "big")
        raw[29:33] = (zlib.crc32(raw[12:29]) & 0xffffffff).to_bytes(4, "big")
        result = resource_catalog({"sheet.png": bytes(raw)})
        self.assertIn("像素", result["sheet.png"]["decodeError"])

    def test_atlas_invalid_rectangle_duplicate_name_or_target_bounds_leave_open(self):
        name = "battle/effect/test/test.atlas.json"
        cases = [{"x": -1}, {"y": -1}, {"w": 0}, {"h": -1}, {"w": 4.5}, {"x": 1}, {"y": 1}]
        for edit in cases:
            catalog = fixture(); catalog[name]["data"][0].update(edit)
            result = analyze([root()], catalog)
            self.assertFalse(result["closure"]["compiledResourceClosure"])
            self.assertTrue(result["unsupported"])
        catalog = fixture(); catalog[name]["data"].append(copy.deepcopy(catalog[name]["data"][0]))
        self.assertFalse(analyze([root()], catalog)["closure"]["compiledResourceClosure"])
        catalog = fixture(); del catalog["battle/effect/test/test.png"]["width"]
        self.assertFalse(analyze([root()], catalog)["closure"]["compiledResourceClosure"])

    def test_finite_positive_has_real_counts_and_resource_identity(self):
        result = analyze([root()], fixture(), {"kind": "finite-resources", "closed": True})
        self.assertTrue(result["closure"]["fullyClosed"])
        self.assertTrue(result["closure"]["compiledResourceClosure"])
        self.assertFalse(result["closure"]["characterSemanticClosure"])
        self.assertFalse(result["runtimeAccepted"])
        self.assertEqual(result["counts"]["missing"], 0)
        self.assertEqual(result["counts"]["byKind"]["texture"], 1)
        self.assertTrue(all(len(d["sha256"]) == 64 for d in result["dependencies"]))

    def test_missing_fixed_is_not_dynamic(self):
        catalog = fixture(); del catalog["sound_effect/test.mp3"]
        result = analyze([root()], catalog)
        self.assertFalse(result["closure"]["fullyClosed"])
        self.assertEqual(result["missingReferences"][0]["logical"], "sound_effect/test.mp3")
        self.assertEqual(result["unresolvedDynamic"], [])

    def test_implicit_typed_hit_requires_frozen_element_and_reports_real_fixed_target(self):
        command = ["CreateNormalAttack", 2, 255, [], [], 140, [{"min": 14, "max": 14}], [{"min": 0, "max": 0}],
                   False, False, False, False, False, [], [], ["Coarse"], True]
        catalog = {"program": record("dsl", ["Command", command])}
        result = analyze([root()], catalog)
        self.assertEqual(result["counts"]["dynamic"], 1)
        self.assertEqual(result["counts"]["unsupported"], 0)
        result = analyze([root()], catalog, {"element": 3})
        self.assertEqual(result["counts"]["dynamic"], 0)
        self.assertEqual(result["missingReferences"][0]["logical"], "battle/effect/hit/normal_damage/coarse/coarse_green/coarse_green")

    def test_direct_hit_maps_fixed_effect_without_guessing_scalar_strings(self):
        command = ["CreateNormalAttack", 2, 255, [], [], 140, [], [], False, False, False, False, False, [], [], ["Dark"], True]
        logical = "battle/effect/hit/normal_damage/dark/dark"
        catalog = {"program": record("dsl", ["Block", [["Command", command], ["Command", ["Trace", "a/path/is-not-a-resource"]]]]),
                   logical: record("references", {"references": []})}
        result = analyze([root()], catalog)
        self.assertTrue(result["closure"]["fullyClosed"])
        self.assertEqual(result["counts"]["resolved"], 2)

    def test_scalar_trace_payload_does_not_become_typed_resource(self):
        catalog = {"program": record("dsl", ["Command", ["Trace", ["SpecifyEffectDirectly", "ignored/log-payload"]]])}
        result = analyze([root()], catalog)
        self.assertTrue(result["closure"]["fullyClosed"])
        self.assertEqual(result["missingReferences"], [])

    def test_hitarea_unknown_guard_does_not_close(self):
        command = ["CreateHitArea"] + [0] * 25 + [["FutureGuard", "implicit"]]
        result = analyze([root()], {"program": record("dsl", ["Command", command])})
        self.assertFalse(result["closure"]["fullyClosed"])
        self.assertIn("guard", result["unsupported"][0]["reason"])

    def test_malformed_dynamic_sound_and_group_index_are_reported_not_crashed(self):
        catalog = fixture()
        catalog["timeline"]["data"]["sounds"][0]["path"] = {"dynamic": "field"}
        catalog["parts"]["data"]["g"][0]["s"][0] = {"s": 2 << 30, "i": ["invalid"]}
        result = analyze([root()], catalog)
        self.assertFalse(result["closure"]["fullyClosed"])
        self.assertTrue(result["unresolvedDynamic"])
        self.assertTrue(result["unsupported"])

    def test_dynamic_and_unknown_are_distinct_and_not_closed_by_declaration(self):
        catalog = {"program": record("dsl", ["Block", [["Command", ["ShowEffect", "e", ["SpecifyEffectByElement", 1, 255]]],
                                                        ["Command", ["NewNativeCommand", "may-be-resource"]]]])}
        result = analyze([root()], catalog, {"closed": True})
        self.assertFalse(result["closure"]["fullyClosed"])
        self.assertEqual(result["missingReferences"], [])
        self.assertIn("元素", result["unresolvedDynamic"][0]["reason"])
        self.assertIn("NewNativeCommand", result["unsupported"][0]["reason"])

    def test_all_condition_callback_wait_repeat_branches_walked(self):
        catalog = fixture()
        good = catalog["program"]["data"]
        catalog["program"] = record("dsl", ["Block", [["Command", ["ConditionalsMainOrUnison", good,
            ["Event", ["Wait", 5, "label", ["Event", ["Repeat", 1, 3, "label", good]]]]]],
            ["Event", ["CollisionOfBallAndSpecificEnemy", 0, 0, 0, "label", 0, good, good]]]])
        result = analyze([root()], catalog)
        self.assertTrue(result["closure"]["fullyClosed"])
        # Shared Python objects may recur; at least both distinct branches appear.
        self.assertGreaterEqual(len([e for e in result["edges"] if e["to"] == "battle/effect/test/effect"]), 1)
        # The missing branch must not be skipped because preview would defer it.
        catalog["program"]["data"][1][0][1][2] = ["Command", ["ShowEffect", "late", ["SpecifyEffectDirectly", "missing/conditional"]]]
        result = analyze([root()], catalog)
        self.assertIn("missing/conditional", [m["logical"] for m in result["missingReferences"]])

    def test_nested_native_kind_two_resolves_leaf_and_cycle_is_open(self):
        catalog = fixture()
        catalog["parts"] = record("parts", {"i": [{"p": "battle/effect/test/.gen/0"}], "g": [
            {"t": 1, "s": [{"s": -2147483648.0, "i": 1.0, "l": [{"t": 1}]}]},
            {"t": 1, "s": [{"s": 0, "i": 0, "l": [{"t": 1}]}]}]})
        self.assertTrue(analyze([root()], catalog)["closure"]["fullyClosed"])
        catalog["parts"]["data"]["g"][1]["s"][0] = {"s": 2 << 30, "i": 0}
        result = analyze([root()], catalog)
        self.assertFalse(result["closure"]["fullyClosed"])
        self.assertTrue(any("循环" in u["reason"] for u in result["unsupported"]))

    def test_explicit_graph_cycle_terminates_with_evidence(self):
        catalog = {"a": record("references", {"references": ["b"]}), "b": record("references", {"references": ["a"]})}
        result = analyze([root("a")], catalog)
        self.assertTrue(result["closure"]["fullyClosed"])
        self.assertEqual(len(result["cycles"]), 1)
        self.assertEqual(result["counts"]["resolved"], 2)

    def test_dedupes_same_collection_preserves_cross_collection_bucket_context(self):
        roots = [root(requester="main"), root(requester="unison", roles=["unison"]), root(bucket="Common"), root(collection="Attention")]
        result = analyze(roots, fixture())
        sheets = [d for d in result["dependencies"] if d["kind"] == "texture"]
        self.assertEqual(len(sheets), 3)
        self.assertEqual(sheets[0]["requesters"], ["main", "unison"])
        self.assertEqual(len(result["roots"]), 4)

    def test_roles_forms_switches_select_reachable_scope(self):
        result = analyze([root(forms=["evolved"], switches=["on"]), root("missing", roles=["unison"])], fixture(),
                         {"roles": ["main"], "forms": ["evolved"], "switches": ["on"]})
        self.assertTrue(result["closure"]["fullyClosed"])
        self.assertEqual(result["counts"]["roots"], 1)
        self.assertEqual(result["dependencies"][0]["switches"], ["on"])

    def test_closed_character_without_root_inventory_is_open(self):
        result = analyze([root()], fixture(), {"kind": "character-semantic", "closed": True, "roles": ["main"], "forms": ["base"]})
        self.assertTrue(result["closure"]["compiledResourceClosure"])
        self.assertFalse(result["closure"]["fullyClosed"])
        self.assertEqual({g["domain"] for g in result["characterSemanticGaps"]}, set(DOMAINS))

    def test_handwritten_inventory_closes_only_declared_graph_not_native_semantics(self):
        catalog = fixture()
        domains = {d: {"status": "included" if d == "skill" else "not-applicable", "roots": ["program"] if d == "skill" else []} for d in DOMAINS}
        catalog["inventory"] = record("evidence", {"schema": "declared-root-inventory-v1", "domains": domains})
        evidence = {"logical": "inventory", "sha256": catalog["inventory"]["sha256"]}
        scope = {"kind": "character-semantic", "roles": ["main"], "forms": ["base"],
                 "domains": {d: {"status": "included" if d == "skill" else "not-applicable", "evidence": evidence,
                                   "roots": ["program"] if d == "skill" else []} for d in DOMAINS}}
        result = analyze([root()], catalog, scope)
        self.assertTrue(result["closure"]["declaredRootInventoryClosed"])
        self.assertFalse(result["closure"]["characterSemanticClosure"])
        self.assertFalse(result["closure"]["completeCharacterTotal"])
        scope["domains"]["ability"]["evidence"] = {**evidence, "sha256": "0" * 64}
        self.assertFalse(analyze([root()], catalog, scope)["closure"]["characterSemanticClosure"])

    def test_png_hash_and_all_not_applicable_cannot_fake_character_closure(self):
        catalog = fixture()
        evidence = {"logical": "battle/effect/test/test.png", "sha256": catalog["battle/effect/test/test.png"]["sha256"]}
        scope = {"kind": "character-semantic", "roles": ["main"], "forms": ["base"],
                 "domains": {d: {"status": "not-applicable", "evidence": evidence} for d in DOMAINS}}
        result = analyze([root()], catalog, scope)
        self.assertFalse(result["closure"]["characterSemanticClosure"])
        self.assertFalse(result["closure"]["fullyClosed"])
        self.assertFalse(result["closure"]["declaredRootInventoryClosed"])

    def test_malformed_or_unwrapped_dsl_statement_is_open(self):
        for tree in (["ActionDsl", ["Block", []]], ["Block", [["FutureCommand", "path"]]]):
            result = analyze([root()], {"program": record("dsl", tree)})
            self.assertFalse(result["closure"]["fullyClosed"])
            self.assertTrue(result["unsupported"])

    def test_unsupported_resource_and_identity_do_not_silently_close(self):
        for catalog in ({"program": record("native-ability", {})}, {"program": {"kind": "sound"}}):
            result = analyze([root()], catalog)
            self.assertFalse(result["closure"]["fullyClosed"])
            self.assertTrue(result["unsupported"])

    def test_filemap_reads_amf_companions_and_missing_atlas_cell(self):
        from studio_core import amf_bytes
        image = Image.new("RGBA", (4, 4)); output = io.BytesIO(); image.save(output, "PNG")
        files = {"compiled/common/battle/effect/test/effect.parts.amf3.deflate": amf_bytes({"i": [{"p": "cell"}], "g": [{"t": 1, "s": [{"s": 0, "i": 0}]}]}),
                 "compiled/common/battle/effect/test/effect.timeline.amf3.deflate": amf_bytes({"sounds": []}),
                 "compiled/common/battle/effect/test/test.atlas.amf3.deflate": amf_bytes([{"n": "cell", "x": 0, "y": 0, "w": 4, "h": 4}]),
                 "compiled/common/battle/effect/test/test.png": output.getvalue()}
        result = analyze([root("battle/effect/test/effect")], resource_catalog(files))
        self.assertTrue(result["closure"]["fullyClosed"])
        del files["compiled/common/battle/effect/test/test.atlas.amf3.deflate"]
        result = analyze([root("battle/effect/test/effect")], resource_catalog(files))
        self.assertEqual(result["missingReferences"][0]["logical"], "cell")

    def test_old_project_read_only_keeps_unknown_fields_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = {"id": "old", "revision": 1, "referenceFiles": ["data_readable/skill_dependencies.json"], "future": {"preserve": True},
                       "dependencyScope": {"roots": [root(category="summon")]}}
            base = Path(tmp); (base / "reference/data_readable").mkdir(parents=True)
            path = base / "reference/data_readable/skill_dependencies.json"
            raw = json.dumps({"programs": [{"logical": "program", "tree": ["Block", [["Command", ["Trace", "x"]]]]}]}).encode()
            path.write_bytes(raw)
            class Store:
                def directory(self, pid): return base
            before = copy.deepcopy(project)
            result = analyze_project(Store(), project)
            self.assertEqual(project, before)
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse(result["closure"]["completeCharacterTotal"])
            self.assertTrue(result["closure"]["compiledResourceClosure"])
            coverage = result["nativeDefinitionCoverage"]["domains"]["summon"]
            self.assertEqual(coverage["graphResolved"], 1)
            self.assertEqual(coverage["roots"], [])
            self.assertEqual(coverage["status"], "pending")
            self.assertFalse((base / "project.json").exists())

    def test_reference_path_boundary_and_malformed_scope_rejected(self):
        for value in ({"roots": [{"logical": "../game/asset"}]}, {"roots": [root(layer=True)]}, {"domains": {"fake": {}}}):
            with self.assertRaises(ValueError): validate({"dependencyScope": value})


if __name__ == "__main__":
    unittest.main()
