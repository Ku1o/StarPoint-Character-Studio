import base64
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib
from types import SimpleNamespace
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import ProjectStore, StudioError, archive_files, png_bytes, make_zip, validate, FAKE_PNG, native_commands
from studio_compile import compile_project, compile_pixelart, compile_effect, compiled_preview
from bridge import AMF3Reader, flatomo
from studio import create_server
from template_library import TemplateLibrary
from audio_rules import voice_usage


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="character-studio-test-")
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.p = self.store.create("测试原创角色")
        image = Image.new("RGBA", (8, 12))
        image.putpixel((1, 2), (255, 10, 40, 255))
        image.putpixel((6, 10), (0, 180, 255, 160))
        self.raw = png_bytes(image)
        self.aid = self.store.add_asset(self.p, "姿势.png", self.raw)
        self.anim = {"id": "action1", "name": "待机", "slot": "neutral", "variant": "normal", "kind": "loop", "fps": 60, "frameScale": 6,
                     "clips": [{"asset": self.aid, "hold": 9, "x": -4, "y": -12, "flip": False, "rotation": 0, "scale": 1, "opacity": 1}]}
        self.p["animations"] = [self.anim]
        self.store._write(self.p)

    def tearDown(self):
        self.temp.cleanup()

    def test_edit_save_reopen_and_stale_revision(self):
        updated = self.store.load(self.p["id"])
        updated["animations"][0]["clips"][0]["hold"] = 17
        saved = self.store.save(updated)
        self.assertEqual(self.store.load(saved["id"])["animations"][0]["clips"][0]["hold"], 17)
        with self.assertRaises(StudioError):
            self.store.save(updated)
        self.assertTrue((self.store.directory(saved["id"]) / "history/000000.json").exists())

    def test_transfer_roundtrip_preserves_images_and_timing(self):
        exported = self.store.export(self.p["id"])
        other = ProjectStore(Path(self.temp.name) / "other")
        restored = other.import_archive(exported)
        self.assertNotEqual(restored["id"], self.p["id"])
        self.assertEqual(restored["animations"], self.p["animations"])
        self.assertEqual(other.asset_bytes(restored, self.aid), self.raw)

    def test_reject_archive_escape_duplicate_and_changed_asset(self):
        for path in ("../evil", "C:/evil", "/abs"):
            with self.assertRaises(StudioError):
                archive_files(make_zip({path: b"bad"}))
        with self.assertRaises(StudioError):
            archive_files(make_zip({"a/evil": b"bad"}).replace(b"a/evil", b"a\\evil"))
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as z:
            z.writestr("A.png", b"one")
            z.writestr("a.png", b"two")
        with self.assertRaises(StudioError):
            archive_files(raw.getvalue())
        files = archive_files(self.store.export(self.p["id"]))
        key = next(k for k in files if k.startswith("assets/"))
        files[key] = b"changed"
        with self.assertRaises(StudioError):
            self.store.import_archive(make_zip(files))

    def test_invalid_frame_and_missing_references_rejected(self):
        self.anim["clips"][0]["hold"] = 0
        with self.assertRaises(StudioError):
            validate(self.p)
        self.anim["clips"][0]["hold"] = 9
        self.anim["clips"][0]["asset"] = "missing"
        with self.assertRaises(StudioError):
            validate(self.p)

    def test_upload_enforces_artist_format_and_size_rules(self):
        oversized = png_bytes(Image.new("RGBA", (1023, 3)))
        with self.assertRaisesRegex(StudioError, "1022"):
            self.store.upload(self.p["id"], [{"name": "too-wide.png", "category": "pixel", "data": base64.b64encode(oversized).decode()}])
        self.assertEqual(self.store.load(self.p["id"])["revision"], 0)
        frames = io.BytesIO()
        Image.new("RGBA", (3, 3), "red").save(frames, "PNG", save_all=True, append_images=[Image.new("RGBA", (3, 3), "blue")], duration=100)
        with self.assertRaisesRegex(StudioError, "逐帧"):
            self.store.add_asset(self.p, "animation.png", frames.getvalue())

    def test_native_sound_events_compile_and_read_back_with_audio(self):
        # Four CBR MPEG frame envelopes exercise the storage-header codec.
        raw = (bytes.fromhex("fffb9000") + bytes(413)) * 4
        aid = self.store.add_asset(self.p, "cast.mp3", raw, "sfx")
        self.p["sounds"] = [{"id": "sound1", "asset": aid, "name": "施放", "usage": "skill_sfx", "text": ""}]
        effect = dict(self.anim, id="effect1", soundEvents=[{"id": "event1", "asset": aid, "start": 3, "volume": .7}])
        self.p["effects"] = [effect]
        self.store._write(self.p)
        result = compiled_preview(self.store, self.p["id"], "effects", "effect1")
        self.assertEqual(result["audio"][0]["start"], 3)
        self.assertAlmostEqual(result["audio"][0]["volume"], .7)
        self.assertEqual(base64.b64decode(result["audio"][0]["url"].split(",")[1]), raw)
        self.assertTrue(any(f["path"].endswith(".mp3") for f in result["files"]))
        effect["soundEvents"][0].update(loop=-1, end=8)
        self.store._write(self.p)
        files, _ = compile_effect(self.store, self.p, effect, "test_character")
        timeline = AMF3Reader(zlib.decompress(next(v for k,v in files.items() if k.endswith('.timeline.amf3.deflate')), -15)).read_value()
        self.assertEqual(timeline["sounds"][0]["volume"], 7)
        result = compiled_preview(self.store, self.p["id"], "effects", "effect1")
        self.assertEqual((result["audio"][0]["loop"],result["audio"][0]["end"]), (-1,8))

    def test_template_library_is_separate_and_checks_archive_hash(self):
        import hashlib
        root = Path(self.temp.name) / "templates"
        library = TemplateLibrary(root)
        self.assertFalse(library.catalog()["installed"])
        (root / "packs").mkdir(parents=True)
        raw = self.store.export(self.p["id"])
        (root / "packs/one.zip").write_bytes(raw)
        data = {"schema": "starpoint-template-library-v1", "entries": [{"id": "1", "file": "packs/one.zip", "sha256": hashlib.sha256(raw).hexdigest()}]}
        (root / "catalog.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(library.catalog()["entries"][0]["available"])
        self.assertEqual(library.archive("1"), raw)
        (root / "packs/one.zip").write_bytes(b"changed")
        with self.assertRaises(StudioError):
            library.archive("1")
        data["entries"][0]["file"] = "../private.zip"
        (root / "catalog.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(StudioError):
            library.catalog()
        self.assertEqual(voice_usage("battle/skill_ready.mp3"), "skill_ready")
        self.assertEqual(voice_usage("battle/skill_0.mp3"), "skill_voice")
        self.assertEqual(voice_usage("words/surprised.mp3"), "story_words")

    def test_pixelart_compiler_preserves_hold_and_offset(self):
        second = self.store.add_asset(self.p, "第二帧.png", png_bytes(Image.new("RGBA", (8, 12), "blue")))
        self.anim["clips"].append(dict(self.anim["clips"][0], asset=second, hold=4))
        out, seq = compile_pixelart(self.store, self.p, [self.anim], "normal", "test_character")
        self.assertEqual(seq, [{"name": "neutral", "kind": "loop", "begin": 1, "end": 13}])
        atlas = AMF3Reader(zlib.decompress(next(v for k, v in out.items() if k.endswith(".atlas.amf3.deflate")), -15)).read_value()
        # Independent transcription of accepted client FrameAnimationSource.
        image_frames = []
        for i, record in enumerate(atlas):
            endpoint = int(record["n"].rsplit("pixelart", 1)[1])
            while len(image_frames) < endpoint:
                image_frames.append(i)
        self.assertEqual(image_frames, [0]*9+[1]*4)
        self.assertEqual((-atlas[0]["fx"] - 128, -atlas[0]["fy"] - 128), (-4, -12))
        self.assertTrue(next(v for k, v in out.items() if k.endswith(".png")).startswith(FAKE_PNG))

    def test_effect_duration_can_be_read_by_existing_renderer(self):
        self.anim["kind"] = "once"
        files, error = compile_effect(self.store, self.p, self.anim, "test_character")
        self.assertIsNone(error)
        parts = AMF3Reader(zlib.decompress(next(v for k, v in files.items() if k.endswith(".parts.amf3.deflate")), -15)).read_value()
        frames = flatomo._build_frames(parts)
        self.assertEqual(len(frames[0]), 9)
        for tick in range(9):
            commands = flatomo._flatten(frames, 0, tick, (1, 0, 0, 1, 0, 0), 1)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][1][-2:], (-4.0, -12.0))

    def test_compile_is_not_false_game_readiness(self):
        raw, report = compile_project(self.store, self.p["id"])
        self.assertFalse(report["gameReady"])
        self.assertGreater(len(report["pending"]), 0)
        files = archive_files(raw)
        self.assertIn("report.json", files)
        self.assertTrue(any(k.startswith("compiled/common/character/") for k in files))
        self.assertFalse(any(k.startswith(".cdn/") for k in files))

    def test_compiled_preview_reads_transformed_cells_and_native_timeline(self):
        self.anim["clips"][0].update(flip=True, opacity=0.5, hold=7)
        self.store._write(self.p)
        result = compiled_preview(self.store, self.p["id"], "animations", "action1")
        self.assertEqual(len(result["frames"]), 7)
        cmd = result["frames"][0][0]
        cell = Image.open(io.BytesIO(base64.b64decode(result["assets"][cmd["asset"]].split(",")[1])))
        self.assertEqual(cell.getpixel((6, 2)), (255, 10, 40, 128))
        self.assertEqual(cmd["matrix"][-2] - cmd["fx"], -4)
        self.p["effects"] = [dict(self.anim, id="effect1")]
        self.store._write(self.p)
        effect = compiled_preview(self.store, self.p["id"], "effects", "effect1")
        self.assertEqual(len(effect["frames"]), 7)
        self.assertEqual(effect["frames"][6][0]["matrix"][-2:], [-4.0, -12.0])

    def test_native_layer_edits_survive_compilation(self):
        out, _ = compile_effect(self.store, self.p, self.anim, "test_character")
        decoded = {k: (AMF3Reader(zlib.decompress(v, -15)).read_value() if k.endswith("deflate") else v) for k, v in out.items()}
        root = "reference/effect/fixture/"
        files = {"reference/data_readable/identity.json": b'{"name":"fixture","code_name":"fixture"}'}
        for suffix, target in ((".png", "fixture.png"), (".atlas.amf3.deflate", "fixture.atlas.json"), (".parts.amf3.deflate", "decoded/effect.parts.json"), (".timeline.amf3.deflate", "decoded/effect.timeline.json")):
            value = next(v for k, v in decoded.items() if k.endswith(suffix))
            files[root + target] = value if isinstance(value, bytes) else json.dumps(value).encode()
        p = self.store.import_archive(make_zip(files))
        effect = p["effects"][0]
        layer = next(iter(effect["layers"].values()))
        layer.update(x=13, y=-7)
        self.store.save(p)
        result = compiled_preview(self.store, p["id"], "effects", effect["id"])
        cmd = result["frames"][0][0]
        self.assertEqual((cmd["matrix"][-2] - cmd["fx"], cmd["matrix"][-1] - cmd["fy"]), (9, -19))

    def test_parent_color_composition_and_blend_inheritance(self):
        def state(kind, item, blend=0, color=0x64000000):
            return SimpleNamespace(kind=kind, item_id=item, child_frame=0,
                                   parameters=SimpleNamespace(matrix=(1, 0, 0, 1, 0, 0), alpha=1, blend=blend, color=color))
        frames = [[[state(2, 1, blend=3, color=0x12345678)]], [[state(0, 0)]]]
        result = native_commands(frames, {"i": [{"p": "cell"}]}, {"cell": (self.aid, {})}, 0, 0)
        self.assertEqual(result[0]["blend"], 3)
        self.assertEqual(result[0]["color"], 0x12345678)
        self.assertEqual(result[0]["colorTransform"], [.18, 52, 86, 120])
        frames[1][0][0].parameters.color = 0x3214283C
        frames[1][0][0].parameters.blend = 4
        result = native_commands(frames, {"i": [{"p": "cell"}]}, {"cell": (self.aid, {})}, 0, 0)
        self.assertEqual(result[0]["colorTransform"], [.09, 55.6, 93.2, 130.8])
        self.assertEqual(result[0]["blend"], 4)

    def test_combined_preview_reads_compiled_frames_with_saved_tracks(self):
        self.p["scene"] = {"duration": 40, "tracks": [{"id": "track1", "type": "actor", "ref": "action1", "start": 5, "x": 90, "y": -30, "scale": 2, "rotation": 90, "opacity": .5, "speed": .5}]}
        self.store._write(self.p)
        one = compiled_preview(self.store, self.p["id"], "animations", "action1")
        combined = compiled_preview(self.store, self.p["id"], "scene", "")
        self.assertEqual(combined["frames"][:5], [[], [], [], [], []])
        c = combined["frames"][5][0]
        expected = flatomo._concat(one["frames"][0][0]["matrix"], (0, 12, -12, 0, 90, -30))
        for actual, wanted in zip(c["matrix"], expected):
            self.assertAlmostEqual(actual, wanted)
        self.assertEqual(c["alpha"], .5)
        self.assertEqual(combined["frames"][5], combined["frames"][23])
        self.assertEqual(combined["assets"], one["assets"])

    def test_reference_import_uses_client_endpoints_and_invalid_frame_fallback(self):
        atlas = [{"n": "character/test/pixelart/pixelart0001", "x": 0, "y": 0, "w": 8, "h": 12, "fx": -124, "fy": -116, "fw": 256, "fh": 256}]
        reference = {"reference/data_readable/identity.json": json.dumps({"name": "参考", "character_id": "1", "code_name": "test"}).encode(),
                     "reference/pixelart/sprite_sheet.png": self.raw,
                     "reference/pixelart/sprite_sheet.atlas.json": json.dumps(atlas).encode(),
                     "reference/pixelart/pixelart.frame.json": json.dumps({"x": -128, "y": -128, "scale": 6}).encode(),
                     "reference/pixelart/pixelart.timeline.json": json.dumps({"sequences": [{"name": "stun_ready", "kind": "stop", "begin": 1, "end": 10}]}).encode()}
        p = self.store.import_archive(make_zip(reference))
        self.assertEqual(p["animations"][0]["kind"], "stop")
        self.assertEqual(p["animations"][0]["clips"][0]["hold"], 10)
        self.assertEqual(p["animations"][0]["clips"][0]["x"], -4)
        atlas[0]["n"] = "character/test/pixelart/pixelart0006"
        reference["reference/pixelart/sprite_sheet.atlas.json"] = json.dumps(atlas).encode()
        p = self.store.import_archive(make_zip(reference))
        clips = p["animations"][0]["clips"]
        self.assertEqual([c["hold"] for c in clips], [10])
        self.assertIsNotNone(Image.open(io.BytesIO(self.store.asset_bytes(p, clips[0]["asset"]))).getbbox())
        atlas.append(dict(atlas[0], n="character/test/pixelart/pixelart0010", fx=-110))
        reference["reference/pixelart/sprite_sheet.atlas.json"] = json.dumps(atlas).encode()
        p = self.store.import_archive(make_zip(reference))
        self.assertEqual([(c["hold"],c["x"]) for c in p["animations"][0]["clips"]], [(6,-4),(4,-18)])
        reference["reference/pixelart/pixelart.timeline.json"] = json.dumps({"sequences": [{"name": "special_pose", "kind": "once", "begin": 202, "end": 132}, {"name": "neutral", "kind": "loop", "begin": 1, "end": 10}]}).encode()
        p = self.store.import_archive(make_zip(reference))
        self.assertEqual([a["slot"] for a in p["animations"]], ["neutral"])
        self.assertTrue(any("special_pose" in issue and "202" in issue for issue in p["warnings"]))
        self.assertIn("pixelart/pixelart.timeline.json", p["referenceFiles"])

    def test_http_auth_host_and_actual_routes(self):
        server = create_server(Path(self.temp.name) / "http")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            session = json.load(urllib.request.urlopen(url + "/api/session"))
            req = urllib.request.Request(url + "/api/new", data=b'{"name":"test"}', headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(req)
            req.add_header("X-Studio-Token", session["token"])
            p = json.load(urllib.request.urlopen(req))
            self.assertEqual(p["name"], "test")
            req.add_header("Origin", "https://unrelated.example")
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(req)
            self.assertIn(b"app.js", urllib.request.urlopen(url).read())
            self.assertEqual(json.load(urllib.request.urlopen(url + "/api/project?id=" + p["id"]))["id"], p["id"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
