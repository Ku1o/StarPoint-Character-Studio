import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from character_contract import default_gameplay, export_contract, normalize_gameplay


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-contract-")
        self.root = Path(self.temp.name)
        self.store = type("ReadOnlyStore", (), {"directory": lambda _, pid: self.root / pid})()
        self.p = {"id": "example", "name": "测试角色", "kind": "original", "revision": 7,
                  "identity": {"code": "original_character"}, "referenceFiles": [],
                  "animations": [], "effects": [], "assets": {}, "voices": [], "sounds": [],
                  "skill": {"name": "旧技能名称", "description": "旧版说明"}}

    def tearDown(self):
        self.temp.cleanup()

    def reference(self, name, data):
        path = self.store.directory(self.p["id"]) / "reference" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(data, ensure_ascii=False, indent=3).encode("utf-8")
        path.write_bytes(raw)
        self.p["referenceFiles"].append(name)
        return raw

    def test_original_design_has_six_independent_slots_and_preserves_extensions(self):
        design = default_gameplay()
        other = default_gameplay()
        design["abilities"][1]["description"] = "每次技能发动，攻击力增加 10%"
        design["abilities"][1]["mainOnly"] = True
        design["abilities"][1]["futureTrigger"] = {"count": 2}
        design["designerNotes"] = ["以后扩展"]
        self.p["gameplay"] = design
        before = copy.deepcopy(self.p)
        result = export_contract(self.store, self.p)
        self.assertEqual(self.p, before)
        self.assertEqual([x["slot"] for x in result["gameplayDesign"]["abilities"]], list(range(1, 7)))
        self.assertEqual(result["gameplayDesign"]["abilities"][1]["futureTrigger"], {"count": 2})
        self.assertEqual(result["gameplayDesign"]["designerNotes"], ["以后扩展"])
        self.assertEqual(other["abilities"][1]["description"], "")
        self.assertFalse(result["integration"]["directModImport"])
        self.assertFalse(result["integration"]["gameReady"])
        result["gameplayDesign"]["abilities"][1]["description"] = "返回值编辑"
        self.assertEqual(self.p, before)

    def test_art_only_official_pack_stays_missing_and_program_hash_is_explicit(self):
        self.p.update(kind="template", template={"id": "10", "code": "white_tiger"})
        tree = ["ActionDsl", 3, ["Block", [["Event", ["Wait", 87, "*", ["Block", []]]]]]]
        raw = self.reference("data_readable/skill_dependencies.json", {
            "programs": [{"logical": "battle/action/white_tiger$white_tiger_1.action.dsl.amf3.deflate", "tree": tree}],
            "effects": [],
        })
        result = export_contract(self.store, self.p)
        source = result["sourceDefinition"]
        self.assertEqual(source["status"], "needs_definition_pack")
        self.assertTrue(source["needsDefinitionPack"])
        self.assertTrue(all(s["sourceRows"] is None for s in source["abilities"]))
        program = result["sourcePrograms"][0]
        self.assertEqual(program["tree"], tree)
        self.assertEqual(program["referenceSha256"], hashlib.sha256(raw).hexdigest())
        canonical = json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(program["sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(program["sha256Encoding"], "canonical-json-utf8")
        self.assertEqual(result["gameplayDesign"]["skill"]["name"], "旧技能名称")

    def test_source_rows_follow_actual_references_instead_of_invented_character_keys(self):
        self.p.update(kind="template", template={"id": "10", "code": "white_tiger"})
        row = [""] * 37
        row[0], row[8], row[17] = "white_tiger", "actual_skill_key", "3"
        row[19:25] = ["a", "b", "c", "d", "e", "(None)"]
        raw_rows = {key: {"raw_csv": 'original,"quoted",(None)\n', "rows": [["original", "quoted", "(None)"]]}
                    for key in "abcde"}
        self.reference("data_readable/character.json", {"selected": {"10": {"rows": [row], "raw_csv": ",".join(row)}}})
        self.reference("data_readable/character_text.json", {"selected": {"10": {"rows": [["白"]]}}})
        self.reference("data_readable/leader_ability.json", {"selected": {"3": {"rows": [["actual leader"]]}}})
        self.reference("data_readable/abilities.json", {"selected": raw_rows})
        self.reference("data_readable/action_skill.json", {"outer_key": "actual_skill_key", "rows": [{"inner_key": "1", "fields": ["skill", "description", "", "false", "440", "400", "", "program"]}]})
        result = export_contract(self.store, self.p)
        source = result["sourceDefinition"]
        self.assertEqual(source["status"], "source_data_preserved")
        self.assertEqual(source["leader"]["sourceKey"], "3")
        self.assertEqual(source["abilities"][0]["sourceRows"], raw_rows["a"])
        self.assertEqual(source["abilities"][5]["status"], "not_used_by_source")
        self.assertFalse(result["integration"]["gameReady"])
        # A legacy exporter naming leader by character ID must not claim complete data.
        path = self.store.directory(self.p["id"]) / "reference/data_readable/leader_ability.json"
        path.write_text(json.dumps({"selected": {"10": {"rows": [["wrong key"]]}}}), encoding="utf-8")
        self.assertTrue(export_contract(self.store, self.p)["sourceDefinition"]["needsDefinitionPack"])

    def test_duplicate_slots_and_missing_declared_source_are_rejected(self):
        self.p["gameplay"] = {"abilities": [{"slot": 1}, {"slot": 1}]}
        with self.assertRaisesRegex(ValueError, "槽位"):
            export_contract(self.store, self.p)
        self.p.pop("gameplay")
        self.p["referenceFiles"] = ["data_readable/character.json"]
        with self.assertRaisesRegex(ValueError, "缺失"):
            export_contract(self.store, self.p)

    def test_gameplay_types_energy_bounds_and_blank_legacy_text(self):
        self.p["gameplay"] = default_gameplay()
        original = copy.deepcopy(self.p)
        normalized = normalize_gameplay(self.p)
        self.assertEqual(normalized["skill"]["name"], "旧技能名称")
        self.assertEqual(normalized["skill"]["description"], "旧版说明")
        self.assertEqual(self.p, original)
        for malformed in ([], None, "invalid"):
            with self.subTest(gameplay=malformed), self.assertRaises(ValueError):
                normalize_gameplay({**self.p, "gameplay": malformed})
        for energy in (0, 10000, True, "440", 1.5):
            bad = default_gameplay()
            bad["skill"]["energy"] = energy
            with self.subTest(energy=energy), self.assertRaises(ValueError):
                normalize_gameplay({**self.p, "gameplay": bad})
        for energy in (None, 1, 9999):
            good = default_gameplay()
            good["skill"]["energy"] = energy
            self.assertEqual(normalize_gameplay({**self.p, "gameplay": good})["skill"]["energy"], energy)
        for patch in ({"leader": {"description": []}}, {"abilities": [{"slot": 1, "mainOnly": "true"}]}, {"skill": {"name": 42}}, {"skill": {"name": []}}, {"skill": {"description": None}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                normalize_gameplay({**self.p, "gameplay": patch})

    def test_legacy_decoded_program_and_asset_bindings_survive_handoff(self):
        self.reference("data_readable/action_dsl/decoded/skill_1.json", {
            "logical_path": "battle/action/skill$1.action.dsl.amf3.deflate", "tree": ["ActionDsl", ["Block", []]],
        })
        self.p["effects"] = [{"id": "blast", "name": "爆炸", "native": {"path": "effect/example/decoded/blast.parts.json", "sequence": "normal"}, "nativeFrames": [[]], "soundEvents": [{"start": 44, "asset": "sound1"}]}]
        self.p["assets"] = {"sound1": {"mime": "audio/mpeg", "sha256": "a" * 64}}
        self.p["sounds"] = [{"id": "sound", "asset": "sound1", "logical": "sound_effect/fire/source", "text": "", "usage": "skill_sfx"}]
        self.p["scene"] = {"duration": 180, "tracks": [{"type": "effect", "ref": "blast", "start": 44}]}
        result = export_contract(self.store, self.p)
        self.assertEqual(len(result["sourcePrograms"]), 1)
        self.assertEqual(result["resourceMapping"]["effects"][0]["logical"], "battle/effect/skill_unique/original_character/blast/effect")
        self.assertEqual(result["resourceMapping"]["audio"][0]["sourceLogical"], "sound_effect/fire/source")
        self.assertEqual(result["resourceMapping"]["audio"][0]["encodingStatus"], "requires_compiler_verification")
        self.assertEqual(result["skillPreview"], self.p["scene"])


if __name__ == "__main__":
    unittest.main()
