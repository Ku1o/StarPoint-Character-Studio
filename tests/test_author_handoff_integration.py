"""Source-export and HTTP regression for honest draft/candidate handoff."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import ProjectStore, StudioError, png_bytes
from studio_compile import compile_project


class AuthorHandoffIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-handoff-")
        self.root = Path(self.temp.name) / "projects"
        self.store = ProjectStore(self.root)
        self.p = self.store.create("作者交付")
        self.p["identity"]["code"] = "author_handoff"
        image = Image.new("RGBA", (12, 14), (0, 0, 0, 0))
        image.putpixel((5, 6), (200, 60, 80, 255))
        aid = self.store.add_asset(self.p, "neutral_001_sp.png", png_bytes(image), "pixel")
        self.p["animations"] = [{
            "id": "idle", "name": "待机", "slot": "neutral", "variant": "normal",
            "kind": "loop", "fps": 60, "frameScale": 6,
            "clips": [{"asset": aid, "hold": 6, "x": 0, "y": 0, "flip": False,
                       "rotation": 0, "scale": 1, "opacity": 1}],
        }]
        self.store._write(self.p)

    def tearDown(self):
        self.temp.cleanup()

    def test_draft_remains_exportable_with_blockers_and_truthful_readme(self):
        raw = self.store.export(self.p["id"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn("README-稿主必读.md", archive.namelist())
            self.assertIn("declarations.json", archive.namelist())
            self.assertIn("检查报告.json", archive.namelist())
            checks = json.loads(archive.read("检查报告.json"))
            self.assertFalse(checks["readiness"]["canCompile"])
            self.assertFalse(checks["gameReady"])
            self.assertTrue(any(i.get("blocking") for i in checks["issues"]))
        with self.assertRaisesRegex(StudioError, "需先修正"):
            compile_project(self.store, self.p["id"])

    def test_confirmed_selection_produces_candidate_with_same_check_evidence(self):
        p = self.store.load(self.p["id"])
        p["animations"][0].update(includesCompanion=True, companionNote="待机状态始终显示身旁的小鸟")
        self.store.save(p)
        raw, report = compile_project(self.store, p["id"])
        self.assertFalse(report["gameReady"])
        self.assertTrue(report["readiness"]["canCompile"])
        self.assertTrue(report["checks"]["issues"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(report, json.loads(archive.read("report.json")))
            self.assertIn("README-稿主必读.md", archive.namelist())
            payload = json.loads(archive.read("declarations.json"))
            self.assertIs(True, payload["animations"][0]["includesCompanion"])
        self.assertTrue(all(not receipt.get("swaps") for receipt in report["receipts"]))

    def test_draft_and_candidate_export_resolved_v1_declarations_without_rewriting_project(self):
        p = self.store.load(self.p["id"])
        p["animations"][0].update(includesCompanion=True, companionNote="待机保持附属物")
        p["uiDeclarations"] = {"base:square": {"mask": "", "autoCrop": "", "note": "待确认"}}
        aid = self.store.add_asset(p, "join.mp3", (bytes.fromhex("fffb9000") + bytes(413)) * 4, "voice")
        p["voices"] = [{"id": "join", "asset": aid, "name": "join.mp3", "sourceFile": "voice/ally/join.mp3",
                        "usage": "join", "text": "加入台词"}]
        self.store._write(p)
        before = (self.store.directory(p["id"]) / "project.json").read_bytes()
        candidate, report = compile_project(self.store, p["id"])
        self.assertTrue(report["readiness"]["canCompile"])
        for raw in (self.store.export(p["id"]), candidate):
            with self.subTest(candidate=raw is candidate), zipfile.ZipFile(io.BytesIO(raw)) as archive:
                payload = json.loads(archive.read("declarations.json"))
                self.assertNotIn("mask", payload["uiDeclarations"]["base:square"])
                self.assertEqual("", payload["uiDeclarations"]["base:square"]["autoCrop"])
                self.assertEqual(1, len(payload["voiceDeclarations"]))
                row = payload["voiceDeclarations"][0]
                self.assertEqual(("ally", "join", "加入台词"), tuple(row[k] for k in ("entry", "usage", "text")))
                self.assertEqual("", row["reused"])
        self.assertEqual(before, (self.store.directory(p["id"]) / "project.json").read_bytes())
        self.assertEqual([], self.store.load(p["id"])["voiceDeclarations"])

    def test_http_compile_and_download_cannot_bypass_blocker(self):
        server = create_server(self.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(base + "/api/session") as response:
                token = json.load(response)["token"]
            def post(path):
                return urllib.request.urlopen(urllib.request.Request(
                    base + path, data=json.dumps({"id": self.p["id"]}).encode(),
                    headers={"Content-Type": "application/json", "X-Studio-Token": token}))
            with post("/api/check") as response:
                self.assertFalse(json.load(response)["readiness"]["canCompile"])
            for path in ("/api/compile",):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post(path)
                self.assertEqual(400, error.exception.code)
                self.assertIn("需先修正", json.load(error.exception)["error"])
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + "/api/compile-export?id=" + self.p["id"])
            self.assertEqual(400, error.exception.code)
            with urllib.request.urlopen(base + "/api/export?id=" + self.p["id"]) as response:
                self.assertTrue(zipfile.is_zipfile(io.BytesIO(response.read())))
            for name in ("author-declarations.js", "author-declarations.css"):
                with urllib.request.urlopen(base + "/" + name) as response:
                    self.assertEqual(200, response.status)
                    self.assertTrue(response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
