"""Meaningful local-equivalence and conservative failure cases for repacking."""
import copy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zlib

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atlas_optimizer as optimizer


def png(image, fake=True):
    result = io.BytesIO()
    image.save(result, format="PNG")
    return (optimizer.FAKE_PNG if fake else optimizer.PNG) + result.getvalue()[8:]


def bundle(root="battle/effect/skill_unique/test/one", nested=False, fake=True):
    image = Image.new("RGBA", (64, 40))
    # Hidden RGB is part of the lossless contract, even at zero alpha.
    cell = Image.new("RGBA", (6, 5), (191, 29, 87, 0))
    cell.putpixel((2, 1), (42, 85, 170, 230))
    image.paste(cell, (25, 19))
    name = root + "/.gen/effect/0"
    records = [{"n": name, "x": 25, "y": 19, "w": 6, "h": 5,
                "fx": -3, "fy": 5, "fw": 48, "fh": 64, "r": True,
                "extension": {"note": "untouched", "values": [1, False, 3.5]}}]
    parts = {"i": [{"p": name, "s": False}], "g": [{"t": 4, "s": [{"s": 0, "i": 0,
                "l": [{"m": 255, "t": 2, "c": 0x64112233}, {"m": 4096 | 128 | (2 << 8), "t": 2}]}]}],
             "t": [{"a": 4096, "b": 0, "c": 0, "d": 4096, "x": 4096, "y": -8192},
                   {"a": 8192, "b": 0, "c": 0, "d": -4096, "x": -4096, "y": 12288}],
             "m": [], "a": [1], "o": [], "c": [], "s": 2.5}
    if nested:
        parts["g"] = [{"t": 8, "s": [{"s": 2 << 30, "i": 1, "l": [{"m": 4096 | 200, "r": 2 << 30, "t": 8}]}]}, parts["g"][0]]
    timeline = {"sequences": [{"name": "effect", "begin": 1, "end": parts["g"][0]["t"], "kind": "loop"}],
                "sounds": [{"path": "sound_effect/test", "begin": 2, "end": -1, "volume": 7}],
                "points": [], "circles": [], "rectangles": [], "matrices": []}
    return {root + "/one.png": png(image, fake), root + "/one.atlas.amf3.deflate": optimizer._amf_bytes(records),
            root + "/effect.parts.amf3.deflate": optimizer._amf_bytes(parts),
            root + "/effect.timeline.amf3.deflate": optimizer._amf_bytes(timeline),
            "sound_effect/test.mp3": b"exact opaque audio bytes", "character/test/skill.dsl": b"exact ActionDSL bytes",
            "handoff/readme.txt": b"other artifact"}


def change_amf(files, suffix, callback):
    path = next(p for p in files if p.endswith(suffix))
    value = optimizer._amf(files[path])
    callback(value)
    files[path] = optimizer._amf_bytes(value)


class AtlasOptimizerTests(unittest.TestCase):
    def assert_skipped(self, files, fragment, options=None):
        result, report = optimizer.optimize_files(files, options)
        self.assertEqual(files, result)
        self.assertEqual(0, report["optimizedBundles"])
        self.assertIn(fragment, report["bundles"][0]["reason"])
        self.assertFalse(report["gameReady"])
        return report

    def test_whole_rect_rgba_rotation_metadata_and_nonatlas_bytes(self):
        files = bundle()
        original = copy.deepcopy(files)
        result, report = optimizer.optimize_files(files)
        self.assertEqual(original, files)
        receipt = report["bundles"][0]
        self.assertEqual("optimized", receipt["status"])
        self.assertEqual(1, report["optimizedBundles"])
        self.assertFalse(report["nativeAccepted"])
        self.assertTrue(all(receipt["checks"].values()))
        self.assertLess(receipt["after"]["paddedArea"], receipt["before"]["paddedArea"])
        self.assertLessEqual(receipt["after"]["width"], receipt["before"]["width"])
        self.assertLessEqual(receipt["after"]["height"], receipt["before"]["height"])
        for path in files:
            if path not in (receipt["png"], receipt["atlas"]):
                self.assertEqual(files[path], result[path])
        self.assertEqual(optimizer.FAKE_PNG, result[receipt["png"]][:8])
        before = optimizer._amf(files[receipt["atlas"]])
        after = optimizer._amf(result[receipt["atlas"]])
        for old, new in zip(before, after):
            self.assertEqual({k: v for k, v in old.items() if k not in ("x", "y")},
                             {k: v for k, v in new.items() if k not in ("x", "y")})
        old_cells = optimizer._cells(optimizer._image(files[receipt["png"]], 10000), before)
        new_cells = optimizer._cells(optimizer._image(result[receipt["png"]], 10000), after)
        self.assertEqual(old_cells, new_cells)
        image = optimizer._image(result[receipt["png"]], 10000)
        self.assertEqual((191, 29, 87, 0), image.getpixel((after[0]["x"], after[0]["y"])))

    def test_serialized_candidate_hidden_rgb_and_anchor_rotation_faults_rejected(self):
        files = bundle()
        encoder = optimizer._png_bytes
        def corrupt_hidden_rgb(image, header):
            damaged = image.copy()
            for y in range(image.height):
                for x in range(image.width):
                    r, g, b, a = image.getpixel((x, y))
                    if a == 0 and (r or g or b):
                        damaged.putpixel((x, y), (0, 0, 0, 0))
                        return encoder(damaged, header)
            self.fail("fixture requires hidden RGB")
        with patch.object(optimizer, "_png_bytes", side_effect=corrupt_hidden_rgb):
            self.assert_skipped(files, "RGBA/metadata equivalence failed")
        amf_encoder = optimizer._amf_bytes
        for key, changed in (("fx", 123), ("fy", -27), ("fw", 13), ("fh", 19), ("r", False)):
            def corrupt_metadata(records):
                damaged = copy.deepcopy(records)
                damaged[0][key] = changed
                return amf_encoder(damaged)
            with patch.object(optimizer, "_amf_bytes", side_effect=corrupt_metadata):
                self.assert_skipped(files, "RGBA/metadata equivalence failed")

    def test_nested_loop_replay_preserves_all_groups_ticks_and_commands(self):
        result, report = optimizer.optimize_files(bundle(nested=True, fake=False))
        receipt = report["bundles"][0]
        self.assertTrue(receipt["accepted"])
        self.assertEqual(12, receipt["replay"]["ticks"])
        self.assertEqual(2, receipt["replay"]["groups"])
        self.assertEqual(12, receipt["replay"]["leafCommands"])
        self.assertEqual(optimizer.PNG, result[receipt["png"]][:8])

    def test_duplicate_exact_source_rect_shares_position_not_logical(self):
        files = bundle()
        def duplicate(records):
            records.append(dict(records[0], n=records[0]["n"] + "_other", fx=101))
        change_amf(files, optimizer.ATLAS_SUFFIX, duplicate)
        result, report = optimizer.optimize_files(files)
        receipt = report["bundles"][0]
        records = optimizer._amf(result[receipt["atlas"]])
        self.assertTrue(receipt["accepted"])
        self.assertEqual(2, len(records))
        self.assertEqual(1, receipt["after"]["uniqueRegions"])
        self.assertEqual((records[0]["x"], records[0]["y"]), (records[1]["x"], records[1]["y"]))
        self.assertNotEqual(records[0]["n"], records[1]["n"])
        self.assertEqual(101, records[1]["fx"])

    def test_illegal_partial_overlap_and_out_of_bounds_are_reported(self):
        files = bundle()
        change_amf(files, optimizer.ATLAS_SUFFIX, lambda r: r.append(dict(r[0], n=r[0]["n"] + "_x", x=26)))
        self.assert_skipped(files, "overlapping")
        files = bundle()
        change_amf(files, optimizer.ATLAS_SUFFIX, lambda r: r[0].update(x=63))
        self.assert_skipped(files, "outside sheet")

    def test_bad_image_matrix_and_group_references_are_rejected(self):
        for callback, expected in [
            (lambda p: p["i"][0].update(p="missing"), "image reference"),
            (lambda p: p["g"][0]["s"][0]["l"][0].update(m=99999), "matrix reference"),
            (lambda p: p["g"][0]["s"][0].update(i=99), "segment reference")]:
            files = bundle()
            change_amf(files, ".parts.amf3.deflate", callback)
            self.assert_skipped(files, expected)

    def test_recursion_and_unsupported_movieclips_are_skipped(self):
        files = bundle()
        change_amf(files, ".parts.amf3.deflate", lambda p: p["g"][0]["s"][0].update(s=2 << 30))
        self.assert_skipped(files, "cycle")
        files = bundle()
        change_amf(files, ".parts.amf3.deflate", lambda p: p.update(m=[{"path": "unknown"}]))
        self.assert_skipped(files, "unsupported MovieClip")

    def test_timeline_required_and_sequence_bounds_checked(self):
        files = bundle()
        del files[next(p for p in files if p.endswith(".timeline.amf3.deflate"))]
        self.assert_skipped(files, "missing effect timeline")
        files = bundle()
        change_amf(files, ".timeline.amf3.deflate", lambda t: t["sequences"][0].update(end=5))
        self.assert_skipped(files, "sequence end")

    def test_opaque_pixels_outside_rect_not_silently_discarded(self):
        files = bundle()
        path = next(p for p in files if p.endswith(".png"))
        image = optimizer._image(files[path], 10000)
        image.putpixel((0, 0), (1, 2, 3, 1))
        files[path] = png(image)
        self.assert_skipped(files, "opaque pixels outside")

    def test_budgets_refuse_pixels_ticks_expansion_and_rectangles(self):
        for options, expected in [({"max_pixels": 10}, "pixel budget"), ({"max_ticks": 3}, "group ticks"),
                                  ({"max_commands": 3}, "state budget")]:
            self.assert_skipped(bundle(), expected, {"enabled": True, **options})
        files = bundle()
        change_amf(files, optimizer.ATLAS_SUFFIX, lambda r: r.append(dict(r[0], n=r[0]["n"] + "other")))
        self.assert_skipped(files, "rectangle budget", {"enabled": True, "max_rects": 1})
        with patch.object(optimizer, "MAX_PACK_WORK", 1):
            self.assert_skipped(bundle(), "packing work exhausted")

    def test_tweens_and_child_loop_modes_are_validated(self):
        files = bundle(nested=True)
        change_amf(files, ".parts.amf3.deflate", lambda p: p["g"][0]["s"][0]["l"][0].update(r=(3 << 30)))
        self.assert_skipped(files, "unsupported loop")
        files = bundle()
        change_amf(files, ".parts.amf3.deflate", lambda p: p["g"][0]["s"][0]["l"][0].update(t=(3 << 16) | 2))
        self.assert_skipped(files, "unsupported tween")
        for loop_mode in (0, 1, 2):
            files = bundle(nested=True)
            change_amf(files, ".parts.amf3.deflate", lambda p: p["g"][0]["s"][0]["l"][0].update(r=(loop_mode << 30) | 1))
            self.assertTrue(optimizer.optimize_files(files)[1]["bundles"][0]["accepted"])

    def test_nested_depth_and_adversarial_command_expansion_are_bounded(self):
        files = bundle(nested=True)
        change_amf(files, ".parts.amf3.deflate", lambda p: p["g"].insert(0, {"t": 8, "s": [{"s": 2 << 30, "i": 2, "l": [{"m": 255, "t": 8}]}]}))
        # Existing group 1 now points to itself: cycle must fail before expansion.
        self.assert_skipped(files, "cycle")
        files = bundle(nested=True)
        def chain(parts):
            parts["g"][0]["s"][0]["i"] = 1
            parts["g"].insert(1, {"t": 8, "s": [{"s": 2 << 30, "i": 2, "l": [{"m": 255, "r": 2 << 30, "t": 8}]}]})
        change_amf(files, ".parts.amf3.deflate", chain)
        self.assert_skipped(files, "depth budget", {"enabled": True, "max_depth": 1})
        files = bundle(nested=True)
        # State keys are within budget; replay from all groups expands 20 states.
        self.assert_skipped(files, "expanded command budget", {"enabled": True, "max_commands": 15})

    def test_pixelart_endpoint_hold_replay(self):
        source = bundle()
        image = optimizer._image(next(raw for p, raw in source.items() if p.endswith(".png")), 10000)
        root = "character/test/pixelart"
        records = [{"n": root + "/pixelart0002", "x": 25, "y": 19, "w": 6, "h": 5, "fx": 5, "fy": -4},
                   {"n": root + "/pixelart0005", "x": 25, "y": 19, "w": 6, "h": 5, "fx": -5, "fy": 4}]
        frame = {"name": root + "/pixelart", "x": -128, "y": -128, "scale": 6, "smoothing": False}
        timeline = {"sequences": [{"begin": 1, "end": 5, "name": "idle", "kind": "loop"}],
                    "sounds": [], "points": [], "circles": []}
        files = {root + "/sprite_sheet.png": png(image), root + "/sprite_sheet.atlas.amf3.deflate": optimizer._amf_bytes(records),
                 root + "/pixelart.frame.amf3.deflate": optimizer._amf_bytes(frame),
                 root + "/pixelart.timeline.amf3.deflate": optimizer._amf_bytes(timeline)}
        result, report = optimizer.optimize_files(files)
        self.assertTrue(report["bundles"][0]["accepted"])
        self.assertEqual(5, report["bundles"][0]["replay"]["ticks"])
        self.assertEqual("pixelart", report["bundles"][0]["replay"]["kind"])
        self.assertEqual(files[root + "/pixelart.frame.amf3.deflate"], result[root + "/pixelart.frame.amf3.deflate"])
        wrapped = {"compiled/common/" + path: raw for path, raw in files.items()}
        result, report = optimizer.optimize_files(wrapped)
        self.assertTrue(report["bundles"][0]["accepted"])
        self.assertEqual(root, report["bundles"][0]["scope"])
        self.assertEqual("compiled/common/" + root, report["bundles"][0]["fileRoot"])

    def test_compile_export_namespace_wrapper_preserves_logical_paths(self):
        files = {"compiled/common/" + path: raw for path, raw in bundle().items()}
        result, report = optimizer.optimize_files(files)
        self.assertTrue(report["bundles"][0]["accepted"])
        path = report["bundles"][0]["atlas"]
        self.assertEqual(optimizer._amf(files[path])[0]["n"], optimizer._amf(result[path])[0]["n"])

    def test_no_global_dedup_and_external_consumers_are_conservative(self):
        files = bundle(root="battle/effect/skill_unique/test/one")
        files.update(bundle(root="battle/effect/skill_unique/test/two"))
        result, report = optimizer.optimize_files(files)
        self.assertEqual(2, report["optimizedBundles"])
        self.assertEqual(2, sum(v["after"]["uniqueRegions"] for v in report["bundles"]))
        self.assertEqual(2 * 64 * 40, report["budgetUsed"]["pixels"])
        foreign = optimizer._amf(files["battle/effect/skill_unique/test/one/effect.parts.amf3.deflate"])
        files["elsewhere/foreign.parts.amf3.deflate"] = optimizer._amf_bytes(foreign)
        result, report = optimizer.optimize_files(files)
        self.assertFalse(report["bundles"][0]["accepted"])
        self.assertIn("external parts", report["bundles"][0]["reason"])

    def test_unknown_json_atlas_disabled_and_options_strict(self):
        files = {"handoff/ui-images.atlas.json": b"[]", "handoff/ui-images.png": b"literal"}
        result, report = optimizer.optimize_files(files)
        self.assertEqual(files, result)
        self.assertIn("unsupported JSON/UI", report["bundles"][0]["reason"])
        result, report = optimizer.optimize_files(bundle(), {"future": {"x": 3}})
        self.assertEqual("disabled", report["status"])
        self.assertEqual({"x": 3}, report["options"]["future"])
        for invalid in ({"enabled": 1}, {"max_ticks": True}, {"max_depth": 0}, {"max_pixels": 128000001}, []):
            with self.assertRaises(optimizer.AtlasOptimizationError):
                optimizer.validate_options(invalid)

    def test_determinism_malformed_deflate_and_safe_paths(self):
        files = bundle()
        self.assertEqual(optimizer.optimize_files(files), optimizer.optimize_files(files))
        path = next(p for p in files if p.endswith(optimizer.ATLAS_SUFFIX))
        files[path] += b"not allowed trailing bytes"
        self.assert_skipped(files, "trailing-data")
        for unsafe in ("../escape", "/absolute", "C:/foreign", "a\\b"):
            with self.assertRaises(optimizer.AtlasOptimizationError):
                optimizer.optimize_files({unsafe: b"value"})

    def test_unknown_amf_encoding_not_rewritten_as_different_type(self):
        files = bundle()
        path = next(p for p in files if p.endswith(optimizer.ATLAS_SUFFIX))
        records = optimizer._amf(files[path])
        records[0]["unknownNull"] = None
        encoded = bytearray(optimizer.encode_amf3(records))
        self.assertEqual(b"\x01\x01", encoded[-2:])
        encoded[-2] = 0  # AMF undefined, deliberately collapsed by small reader.
        compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
        files[path] = compressor.compress(encoded) + compressor.flush()
        self.assert_skipped(files, "noncanonical atlas AMF")


if __name__ == "__main__":
    unittest.main()
