import base64
import copy
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_intake import (register_package, register_source, record_derivative,
                           source_intake_payload, verify_source_bytes, preserve_source_identity)
from studio_core import ProjectStore, png_bytes


class SourceIntakeTests(unittest.TestCase):
    def test_read_old_project_is_non_mutating_and_missing_package_has_no_hash(self):
        p = {"assets": {}}
        self.assertEqual(source_intake_payload(p)["sources"], [])
        self.assertNotIn("sourceIntake", p)
        package = register_package(p, "missing-original.zip")
        self.assertIsNone(package["sha256"])
        self.assertIsNone(package["blob"])
        with self.assertRaises(ValueError):
            register_package(p, "invented.zip", status="received")

    def test_raw_identity_and_duplicate_derivatives_remain_independent(self):
        p = {"assets": {"normalized": {"sha256": "f" * 64}}}
        one = register_source(p, "front/image.png", b"original-one")
        two = register_source(p, "back/image.png", b"original-two")
        for source in (one, two):
            record_derivative(p, "normalized", source["id"], rect=[0, 0, 4, 6], mask={"note": "author mask"})
        self.assertEqual(len(source_intake_payload(p)["derivatives"]), 2)
        verify_source_bytes(one, b"original-one")
        with self.assertRaises(ValueError):
            verify_source_bytes(one, b"original-two")
        incoming = copy.deepcopy(p)
        incoming["sourceIntake"]["sources"][0]["path"] = "rewritten.png"
        with self.assertRaises(ValueError):
            preserve_source_identity(p, incoming)
        before = copy.deepcopy(p)
        with self.assertRaises(ValueError):
            record_derivative(p, "normalized", one["id"], mask={"source": "unknown"})
        self.assertEqual(p, before)

    def test_received_package_uses_separate_blob_and_unsafe_source_is_rejected(self):
        p = {"assets": {}}
        package = register_package(p, "author.zip", b"zip-bytes")
        self.assertTrue(package["blob"].startswith("sources/packages/"))
        for path in ("../outside.png", "C:/outside.png", "/root.png", "bad\x00.png"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                register_source(p, path, b"raw")
        before = copy.deepcopy(p)
        with self.assertRaises(ValueError):
            register_source(p, "safe.png", b"raw", metadata={"scale": float("inf")})
        self.assertEqual(p, before)

    def test_pixel_import_preserves_raw_png_and_grid_cells_0_27_28(self):
        with tempfile.TemporaryDirectory(prefix="source-intake-") as root:
            store = ProjectStore(Path(root) / "projects")
            p = store.create("source fixture")
            image = Image.new("RGBA", (58, 3))
            for cell in (0, 27, 28):
                image.paste((cell, 20, 40, 255), (cell * 2, 0, cell * 2 + 2, 3))
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("author", "original pixel draft")
            out = io.BytesIO()
            image.save(out, format="PNG", pnginfo=metadata)
            raw = out.getvalue()
            request = {"revision": p["revision"], "files": [{"path": "draft/author-sheet.png",
                "data": base64.b64encode(raw).decode(), "target": "preset:walk_front",
                "sheet": {"width": 2, "height": 3, "skipEmpty": True}}]}
            result = store.import_pixel_images(p["id"], request)
            p = result["project"]
            source = p["sourceIntake"]["sources"][0]
            self.assertEqual(source["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual((store.directory(p["id"]) / source["blob"]).read_bytes(), raw)
            action = next(a for a in p["animations"] if a["slot"] == "walk_front")
            self.assertEqual([c["sourceRef"]["cell"] for c in action["clips"]], [0, 27, 28])
            self.assertEqual(action["clips"][1]["sourceRef"]["rect"], [54, 0, 2, 3])
            asset = p["assets"][action["clips"][0]["asset"]]
            self.assertNotEqual(asset["sha256"], source["sha256"])
            self.assertNotIn("actionContract", action)
            reopened = store.load(p["id"])
            self.assertEqual(reopened["sourceIntake"], p["sourceIntake"])


if __name__ == "__main__":
    unittest.main()
