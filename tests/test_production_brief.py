import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from production_brief import checks, default_production_brief, hydrate_from_project, normalize_production_brief
from studio_core import ProjectStore, json_bytes


class ProductionBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="production-brief-")
        self.store = ProjectStore(Path(self.tmp.name) / "projects")
        self.project = self.store.create("稻穗流程验收")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_contains_author_fields_resources_voices_and_workflow(self):
        brief = self.project["productionBrief"]
        self.assertEqual(brief["workflow"]["status"], "author_package")
        self.assertEqual([p["slot"] for p in brief["plans"]["abilities"]], list(range(1, 7)))
        self.assertTrue(any(r["id"] == "skill_projectile" for r in brief["resources"]))
        self.assertTrue(any(v["id"] == "home_evolved" for v in brief["voices"]))
        self.assertTrue(any(s["id"] == "skill_sfx" for s in brief["sounds"]))
        self.assertTrue(brief["acceptance"]["previewIsNotCombat"])

    def test_core_plan_names_and_required_sound_are_reported(self):
        brief = self.project["productionBrief"]
        for key in ("activeSkill", "pf", "leader"):
            brief["plans"][key]["authorDescription"] = "作者先描述想要的表现。"
        texts = [item["text"] for item in checks(self.project)]
        self.assertIn("主动技能尚未填写名称", texts)
        self.assertIn("PF尚未填写名称", texts)
        self.assertIn("音效待补：技能施放音效", texts)
        self.assertFalse(any("能力 1" in text for text in texts if "尚未填写" in text))

    def test_old_project_without_brief_reads_and_persists_additive_default(self):
        path = self.store.directory(self.project["id"]) / "project.json"
        legacy = copy.deepcopy(self.project)
        legacy.pop("productionBrief")
        path.write_bytes(json_bytes(legacy))
        opened = self.store.load(self.project["id"])
        self.assertIn("productionBrief", opened)
        opened["productionBrief"]["author"]["title"] = "旧工程迁入后补填"
        saved = self.store.save(opened)
        stored = json.loads(path.read_bytes())
        self.assertEqual(stored["productionBrief"]["author"]["title"], "旧工程迁入后补填")
        self.assertEqual(saved["productionBrief"]["author"]["characterName"], "稻穗流程验收")

    def test_legacy_identity_and_gameplay_seed_new_brief_without_dropping_old_fields(self):
        path = self.store.directory(self.project["id"]) / "project.json"
        legacy = copy.deepcopy(self.project)
        legacy.pop("productionBrief")
        legacy["identity"].update(title="月下", role="输出", race="人")
        legacy["skill"] = {"name": "旧主动技", "description": "旧版技能说明"}
        legacy["gameplay"] = {"leader": {"name": "旧队长技", "description": "旧队长说明"}, "abilities": [{"slot": 2, "name": "旧能力", "description": "旧能力说明"}]}
        path.write_bytes(json_bytes(legacy))
        opened = self.store.load(self.project["id"])
        brief = opened["productionBrief"]
        self.assertEqual(brief["author"]["title"], "月下")
        self.assertEqual(brief["plans"]["activeSkill"]["name"], "旧主动技")
        self.assertEqual(brief["plans"]["leader"]["authorDescription"], "旧队长说明")
        self.assertEqual(brief["plans"]["abilities"][1]["authorDescription"], "旧能力说明")
        self.assertEqual(opened["gameplay"]["abilities"][0]["slot"], 2)

    def test_required_and_optional_resource_voice_missing_are_distinguished(self):
        brief = self.project["productionBrief"]
        brief["author"].update(characterName="角色", title="称号", role="输出", race="人", baseForm="基础", evolvedForm="进化")
        brief["plans"]["activeSkill"]["authorDescription"] = "对前方敌人造成伤害并留下月光。"
        brief["plans"]["pf"]["authorDescription"] = "PF 命中时产生方向明确的拖尾。"
        brief["plans"]["leader"]["authorDescription"] = "战斗开始时提升队伍攻击。"
        required = next(item for item in brief["resources"] if item["id"] == "portrait_base")
        required.update(status="provided", assetIds=["asset-base"])
        optional = next(item for item in brief["resources"] if item["id"] == "skill_fullscreen")
        self.assertFalse(optional["required"])
        issues = checks(self.project)
        texts = [item["text"] for item in issues]
        self.assertNotIn("资源待补：进化前大立绘", texts)
        self.assertIn("资源待补：进化后大立绘", texts)
        self.assertIn("语音待补：主城语音（进化前）", texts)
        self.assertTrue(any("释放技能" in text for text in texts))
        self.assertNotIn("资源待补：主动技能：全屏 / 镜头帧集", texts)

    def test_evolution_voice_pair_and_encoding_review_are_reported(self):
        brief = self.project["productionBrief"]
        base = next(item for item in brief["voices"] if item["id"] == "home_base")
        evolved = next(item for item in brief["voices"] if item["id"] == "home_evolved")
        base.update(status="provided", source="new_recording", filename="home-base.mp3", encoding="game-container")
        evolved.update(status="missing")
        audio = next(item for item in brief["review"] if item["id"] == "audio_container")
        audio["state"] = "risk"
        texts = [item["text"] for item in checks(self.project)]
        self.assertIn("进化前后语音未成对：主城语音（进化后）", texts)
        self.assertIn("稳定经验存在风险：校验游戏所需音频封装", "\n".join(texts))

    def test_export_import_roundtrip_keeps_author_fields_and_states(self):
        brief = self.project["productionBrief"]
        brief["workflow"]["status"] = "maker_review"
        brief["workflow"]["handoff"][0]["complete"] = True
        brief["author"]["title"] = "月下稻穗"
        brief["plans"]["abilities"][0].update(name="月行", authorDescription="受到攻击后短时间获得月行状态。", nativeSupport="needs_verification")
        next(item for item in brief["resources"] if item["id"] == "pf_frames").update(status="reuse_official", notes="复用官方基础帧后改色")
        next(item for item in brief["voices"] if item["id"] == "home_base").update(status="reuse_official", source="reuse_official", textJapanese="公式音声")
        next(item for item in brief["review"] if item["id"] == "official_projectile")["state"] = "pass"
        self.store._write(self.project)
        other = ProjectStore(Path(self.tmp.name) / "other")
        restored = other.import_archive(self.store.export(self.project["id"]))
        self.assertEqual(restored["productionBrief"], self.project["productionBrief"])
        self.assertEqual(restored["productionBrief"]["plans"]["abilities"][0]["authorDescription"], "受到攻击后短时间获得月行状态。")

    def test_unknown_future_fields_survive_normalization(self):
        brief = default_production_brief()
        brief["futureExtension"] = {"keep": True}
        brief["author"]["futureAuthorField"] = "保留"
        normalized = normalize_production_brief(brief)
        self.assertEqual(normalized["futureExtension"], {"keep": True})
        self.assertEqual(normalized["author"]["futureAuthorField"], "保留")

    def test_imported_assets_hydrate_checklist_without_claiming_effect_support(self):
        project = copy.deepcopy(self.project)
        project["template"] = {"id": "10", "name": "官方模板"}
        project["identity"].update(title="官方称号", element="水")
        project["assets"] = {key: {"mime": "image/png"} for key in ("portrait", "ui", "idle", "effect")}
        project["assets"]["voice"] = {"mime": "audio/mpeg"}
        project["portraits"] = {"base": "portrait", "evolved": None}
        project["uiSources"] = {"base:square": "ui"}
        project["animations"] = [{"slot": "neutral", "clips": [{"asset": "idle"}]}]
        project["effects"] = [{"id": "fx", "nativeFrames": [[{"asset": "effect"}]]}]
        project["voices"] = [{"usage": "home", "asset": "voice"}, {"usage": "skill_voice", "asset": "voice"}]
        brief = hydrate_from_project(project)
        resources = {item["id"]: item for item in brief["resources"]}
        self.assertEqual(brief["author"]["characterName"], "官方模板")
        self.assertEqual(brief["author"]["title"], "官方称号")
        self.assertEqual(resources["portrait_base"]["status"], "provided")
        self.assertEqual(resources["pixel_idle"]["status"], "provided")
        self.assertEqual(resources["skill_projectile"]["status"], "needs_review")
        self.assertEqual(next(item for item in brief["voices"] if item["id"] == "home_base")["status"], "provided")
        self.assertEqual(next(item for item in brief["voices"] if item["id"] == "skill")["status"], "provided")

    def test_invalid_status_is_rejected_before_save(self):
        bad = copy.deepcopy(self.project)
        bad["productionBrief"]["resources"][0]["status"] = "done"
        with self.assertRaises(ValueError):
            normalize_production_brief(bad)

    def test_http_handoff_download_contains_json_and_attachment_name(self):
        from studio import create_server
        server = create_server(Path(self.tmp.name) / "http-projects")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            project = server.store.create("HTTP 交接工程")
            project["productionBrief"]["author"]["title"] = "HTTP 交接"
            server.store.save(project)
            url = f"http://127.0.0.1:{server.server_port}/api/production-handoff?id={project['id']}"
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read())
                disposition = response.headers.get("Content-Disposition", "")
            self.assertEqual(payload["productionBrief"]["author"]["title"], "HTTP 交接")
            self.assertIn("制作交接.json", urllib.parse.unquote(disposition))
            self.assertFalse(payload["gameReady"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    unittest.main()
