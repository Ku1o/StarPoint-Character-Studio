import base64
import copy
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import test_studio as fixture
from project_storage import upgrade_projects, history, recover, inventory
from studio_core import ProjectStore, StudioError, json_bytes, make_zip
from studio import create_server


class StorageTests(fixture.unittest.TestCase):
    setUp = fixture.StudioTests.setUp
    tearDown = fixture.StudioTests.tearDown

    def legacy(self, project=None):
        p = copy.deepcopy(project or self.p)
        p.pop("formatVersion", None)
        p.pop("lastSavedWith", None)
        p.pop("uiSources", None)
        p["extensionFromCreator"] = {"layers": [1, 3], "note": "不能丢"}
        path = self.store.directory(p["id"]) / "project.json"
        path.write_bytes(json_bytes(p))
        return p, path

    def test_read_only_legacy_load_and_exact_backup_before_first_save(self):
        p, path = self.legacy()
        before = inventory(path.parent)
        raw = path.read_bytes()
        opened = self.store.load(p["id"])
        self.assertEqual(inventory(path.parent), before)
        opened["notes"] = "升级后的修改"
        saved = self.store.save(opened)
        self.assertEqual(saved["extensionFromCreator"], p["extensionFromCreator"])
        self.assertTrue(any(file.read_bytes() == raw for file in (path.parent / "history").glob("*.json")))
        self.assertEqual(saved["formatVersion"], 1)
        self.assertEqual(self.store.load(p["id"]), saved)

    def test_upload_and_direct_editor_writes_also_snapshot_previous_state(self):
        _, path = self.legacy()
        old = path.read_bytes()
        self.store.upload(self.p["id"], [{"name": "another.png", "data": base64.b64encode(self.raw).decode()}])
        self.assertTrue(any(p.read_bytes() == old for p in (path.parent / "history").glob("*.json")))

    def test_failed_backup_or_replace_never_changes_current_project(self):
        _, path = self.legacy()
        raw = path.read_bytes()
        p = self.store.load(self.p["id"])
        p["notes"] = "不应覆盖"
        with patch("project_storage.snapshot", side_effect=OSError("磁盘写入失败")):
            with self.assertRaises(OSError):
                self.store.save(p)
        self.assertEqual(path.read_bytes(), raw)
        with patch.object(Path, "replace", side_effect=OSError("替换失败")):
            with self.assertRaises(OSError):
                self.store.save(p)
        self.assertEqual(path.read_bytes(), raw)
        self.assertTrue(any(f.read_bytes() == raw for f in (path.parent / "history").glob("*.json")))
        self.assertEqual(self.store.load(p["id"])["notes"], self.p["notes"])

    def test_same_revision_history_is_never_overwritten(self):
        _, path = self.legacy()
        first = inventory(path.parent / "history")
        p = self.store.load(self.p["id"])
        self.store.save(p)
        after = inventory(path.parent / "history")
        for name, digest in first.items():
            self.assertEqual(after[name], digest)

    def test_future_format_load_save_and_import_rejected_without_writes(self):
        p, path = self.legacy()
        p["formatVersion"] = 99
        path.write_bytes(json_bytes(p))
        before = inventory(self.store.root)
        for action in (lambda: self.store.load(p["id"]), lambda: self.store.save(self.p),
                       lambda: self.store.import_archive(make_zip({"project.json": json_bytes(p)}))):
            with self.assertRaisesRegex(StudioError, "数据格式"):
                action()
            self.assertEqual(inventory(self.store.root), before)
        self.assertIn("error", self.store.list()[0])

    def test_structurally_corrupt_json_remains_listed_without_breaking_home(self):
        p, path = self.legacy()
        for field, value in (("assets", []), ("assets", {"bad": None}), ("updated", "invalid")):
            broken = dict(p, **{field: value})
            path.write_bytes(json_bytes(broken))
            before = path.read_bytes()
            rows = self.store.list()
            self.assertEqual(rows[0]["id"], p["id"])
            self.assertIn("error", rows[0])
            self.assertEqual(path.read_bytes(), before)

    def test_partial_backup_failure_can_retry_without_a_truncated_history_entry(self):
        _, path = self.legacy()
        before = path.read_bytes()
        p = self.store.load(self.p["id"])
        import project_storage
        real_write = project_storage.write_bytes
        def disk_full(target, raw, mode="wb"):
            if target.parent.name == "history":
                real_write(target, raw[:10], mode)
                raise OSError("磁盘空间不足")
            return real_write(target, raw, mode)
        with patch("project_storage.write_bytes", side_effect=disk_full):
            with self.assertRaises(OSError):
                self.store.save(p)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list((path.parent / "history").glob(".pending-*")))
        self.store.save(p)
        self.assertTrue(any(f.read_bytes()==before for f in (path.parent/"history").glob("*.json")))

    def test_upgrade_preserves_all_payloads_and_repeat_import_skips_edited_copy(self):
        p, path = self.legacy()
        (path.parent / "creator-notes.txt").write_text("未登记的源画稿也保留", encoding="utf-8")
        (path.parent / "project.pending").write_bytes(b"previous interrupted save")
        before = inventory(self.store.root)
        new = ProjectStore(Path(self.temp.name) / "new" / "projects")
        report = upgrade_projects(new, self.store.root.parent)
        self.assertEqual((len(report["copied"]), len(report["failed"])), (1, 0))
        opened = new.load(p["id"])
        self.assertEqual(opened["animations"], p["animations"])
        for key, digest in inventory(path.parent).items():
            if key != "project.json":
                self.assertEqual(inventory(new.directory(p["id"]))[key], digest)
        opened["notes"] = "新版继续编辑"
        new.save(opened)
        report = upgrade_projects(new, self.store.root)
        self.assertEqual(len(report["skipped"]), 1)
        self.assertEqual(new.load(p["id"])["notes"], "新版继续编辑")
        self.assertEqual(inventory(self.store.root), before)

    def test_conflicting_project_id_makes_separate_copy(self):
        p, path = self.legacy()
        new = ProjectStore(Path(self.temp.name) / "new")
        destination = new.directory(p["id"])
        destination.mkdir()
        conflict = copy.deepcopy(p)
        conflict["name"] = "新版已制作的工程"
        new._write(conflict)
        before = inventory(destination)
        result = upgrade_projects(new, self.store.root)
        self.assertNotEqual(result["copied"][0]["id"], p["id"])
        self.assertEqual(inventory(destination), before)
        self.assertEqual(len(new.list()), 2)

    def test_damaged_or_missing_current_json_recovers_copy_with_assets(self):
        p, path = self.legacy()
        self.store.save(self.store.load(p["id"]))
        records = history(self.store, p["id"])
        chosen = next(r for r in records if json.loads((path.parent / "history" / r["file"]).read_bytes()).get("extensionFromCreator"))
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    path.unlink()
                else:
                    path.write_bytes(b'{"broken')
                before = inventory(path.parent)
                row = next(r for r in self.store.list() if r["id"] == p["id"])
                self.assertIn("error", row)
                restored = recover(self.store, p["id"], chosen["file"])
                self.assertNotEqual(restored["id"], p["id"])
                self.assertEqual(restored["animations"], p["animations"])
                self.assertEqual(restored["extensionFromCreator"], p["extensionFromCreator"])
                self.assertEqual(self.store.asset_bytes(restored, self.aid), self.raw)
                self.assertEqual(inventory(path.parent), before)

    def test_corrupt_asset_and_changed_source_do_not_publish_partial_copies(self):
        p, path = self.legacy()
        new = ProjectStore(Path(self.temp.name) / "new")
        asset_path = path.parent / "assets" / p["assets"][self.aid]["file"]
        asset_path.write_bytes(b"damaged")
        result = upgrade_projects(new, self.store.root)
        self.assertEqual(len(result["failed"]), 1)
        self.assertFalse(new.list())
        asset_path.write_bytes(self.raw)
        import project_storage
        real_copy = project_storage.shutil.copytree
        def changing_copy(source, target, *args, **kwargs):
            result = real_copy(source, target, *args, **kwargs)
            if Path(source) == path.parent:
                p["notes"] = "迁入中修改"
                path.write_bytes(json_bytes(p))
            return result
        with patch("project_storage.shutil.copytree", side_effect=changing_copy):
            result = upgrade_projects(new, self.store.root)
        self.assertIn("发生变化", result["failed"][0]["error"])
        self.assertFalse(list(new.root.iterdir()))

    def test_all_editable_domains_survive_legacy_upgrade_and_zip_roundtrip(self):
        from test_effect_channels import ChannelTests
        from test_native_gameplay import pack
        from native_gameplay import attach
        p = ChannelTests.imported(self)
        p["effects"][0]["channels"][0].update(x=19, opacity=.7)
        aid = self.store.add_asset(p, "画稿.png", self.raw)
        p["animations"] = [dict(self.anim, clips=[dict(self.anim["clips"][0], asset=aid, hold=23)])]
        p["portraits"]["base"] = aid
        p["crops"]["base:square"] = {"x": .3, "y": .6, "zoom": 1.4}
        p["uiImages"] = {"base:square": {"mode": "image", "asset": aid}}
        sound = self.store.add_asset(p, "技能.mp3", (bytes.fromhex("fffb9000") + bytes(413)) * 4, "sfx")
        p["sounds"] = [{"id": "sfx", "asset": sound, "name": "施放", "usage": "skill_sfx", "text": ""}]
        p["voices"] = [{"id": "voice", "asset": sound, "name": "语音", "usage": "skill", "text": "开始"}]
        p["template"].update(id="10", version="1.4.54")
        self.store._write(p)
        library = type("Library", (), {"load": lambda _: pack()})()
        p = attach(self.store, p["id"], p["revision"], library, "10")
        p, path = self.legacy(p)
        new = ProjectStore(Path(self.temp.name) / "new")
        report = upgrade_projects(new, self.store.root)
        self.assertFalse(report["failed"])
        opened = new.load(p["id"])
        restored = new.import_archive(new.export(opened["id"]))
        for key in ("animations", "effects", "portraits", "crops", "uiImages", "sounds", "voices", "nativeGameplay", "extensionFromCreator"):
            self.assertEqual(restored[key], p[key], key)
        for aid in p["assets"]:
            self.assertEqual(new.asset_bytes(restored, aid), self.store.asset_bytes(p, aid))

    def test_http_storage_routes_require_token_and_ignore_client_paths(self):
        server = create_server(Path(self.temp.name) / "http")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            session = json.load(urllib.request.urlopen(url + "/api/session"))
            self.assertEqual(Path(session["projectDirectory"]), server.store.root)
            def post(path, body, token=True):
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["X-Studio-Token"] = session["token"]
                return json.load(urllib.request.urlopen(urllib.request.Request(url+path, data=json_bytes(body), headers=headers)))
            with self.assertRaises(urllib.error.HTTPError):
                post("/api/upgrade-projects", {}, token=False)
            with self.assertRaises(urllib.error.HTTPError):
                post("/api/upgrade-projects", {"path": str(self.store.root)})
            server.choose_project_directory = lambda: str(self.store.root)
            result = post("/api/upgrade-projects", {"path": "ignored"})
            pid = result["copied"][0]["id"]
            rows = json.load(urllib.request.urlopen(url + "/api/project-history?id=" + pid))["records"]
            restored = post("/api/project-recover", {"id": pid, "file": rows[0]["file"]})
            self.assertNotEqual(pid, restored["id"])
            with self.assertRaises(urllib.error.HTTPError):
                post("/api/project-recover", {"id": pid, "file": "../project.json"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    @fixture.unittest.skipUnless(os.name == "nt", "Windows single-instance protection")
    def test_running_old_tool_prevents_upgrade(self):
        from desktop_host import WindowsInstance
        old = WindowsInstance(self.store.root)
        try:
            new = ProjectStore(Path(self.temp.name) / "new")
            with self.assertRaisesRegex(StudioError, "仍在运行"):
                upgrade_projects(new, self.store.root)
            self.assertFalse(list(new.root.iterdir()))
        finally:
            old.close()
