"""Preview-stage persistence, rejection, and compilation isolation regressions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import (ProjectStore, StudioError, archive_files, fresh_project,
                         make_zip, png_bytes, validate)
from spatial_preview import validate_preview_stage
from studio_compile import compile_project, compiled_scene_preview
from character_contract import export_contract


def stage(profile="custom"):
    return {"version": 1, "profile": profile, "width": 640.5, "height": 480,
            "originX": 0, "originY": 479.75, "targetX": 640.5, "targetY": 0.125}


class SpatialPreviewTests(unittest.TestCase):
    def setUp(self):
        # No projects, logs or compiled fixtures are written inside source.
        self.temp = tempfile.TemporaryDirectory(prefix="studio-spatial-preview-")
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / "projects")
        self.project = self.store.create("预览场地回归")
        self.path = self.store.directory(self.project["id"]) / "project.json"

    def assert_stage_exact(self, expected, actual):
        self.assertEqual(expected, actual)
        self.assertEqual({k: type(v) for k, v in expected.items()},
                         {k: type(v) for k, v in actual.items()})

    def test_absent_field_stays_absent_through_validate_save_and_transfer(self):
        before = self.path.read_bytes()
        loaded = self.store.load(self.project["id"])
        validate_preview_stage(loaded)
        validate(loaded)
        self.assertNotIn("previewStage", loaded)
        self.assertEqual(before, self.path.read_bytes())
        saved = self.store.save(loaded)
        self.assertNotIn("previewStage", saved)
        self.assertNotIn("previewStage", json.loads(self.path.read_bytes()))
        payload = self.store.export(saved["id"])
        self.assertNotIn("previewStage", json.loads(archive_files(payload)["project.json"]))
        other = ProjectStore(Path(self.temp.name) / "imported")
        restored = other.import_archive(payload)
        self.assertNotIn("previewStage", restored)
        self.assertNotIn("previewStage", other.load(restored["id"]))
        self.assertNotIn("previewStage", json.loads(
            (other.directory(restored["id"]) / "project.json").read_bytes()))

    def test_validator_is_read_only_for_absent_and_valid_metadata(self):
        for project in ({}, {"previewStage": stage("reference")},
                        {"previewStage": stage("custom")}):
            before = copy.deepcopy(project)
            validate_preview_stage(project)
            self.assertEqual(project, before)
        p = fresh_project()
        p["previewStage"] = stage()
        value = p["previewStage"]
        validate(p)
        self.assertIs(p["previewStage"], value)
        self.assert_stage_exact(stage(), value)

    def test_both_profiles_save_load_and_export_import_exact_coordinates(self):
        for profile in ("reference", "custom"):
            with self.subTest(profile=profile):
                p = self.store.load(self.project["id"])
                p["previewStage"] = stage(profile)
                saved = self.store.save(p)
                self.assert_stage_exact(stage(profile), saved["previewStage"])
                self.assert_stage_exact(stage(profile), self.store.load(saved["id"])["previewStage"])
                self.assert_stage_exact(stage(profile), json.loads(self.path.read_bytes())["previewStage"])
                payload = self.store.export(saved["id"])
                self.assert_stage_exact(stage(profile), json.loads(
                    archive_files(payload)["project.json"])["previewStage"])
                other = ProjectStore(Path(self.temp.name) / ("imported-" + profile))
                restored = other.import_archive(payload)
                self.assert_stage_exact(stage(profile), restored["previewStage"])
                self.assert_stage_exact(stage(profile), other.load(restored["id"])["previewStage"])
                self.assert_stage_exact(stage(profile), json.loads(
                    (other.directory(restored["id"]) / "project.json").read_bytes())["previewStage"])

    def test_inclusive_bounds_and_fractional_sizes(self):
        for width, height in ((1, 1), (8192, 8192), (1.25, 8191.5)):
            for profile in ("reference", "custom"):
                p = fresh_project()
                p["previewStage"] = dict(stage(profile), width=width, height=height,
                                         originX=0, originY=0, targetX=width, targetY=height)
                expected = copy.deepcopy(p["previewStage"])
                validate(p)
                self.assert_stage_exact(expected, p["previewStage"])

    def test_metadata_can_be_removed_without_reappearing(self):
        p = self.store.load(self.project["id"])
        p["previewStage"] = stage()
        saved = self.store.save(p)
        del saved["previewStage"]
        self.store.save(saved)
        self.assertNotIn("previewStage", self.store.load(p["id"]))
        self.assertNotIn("previewStage", json.loads(self.path.read_bytes()))

    def test_art_scene_and_game_bindings_are_identical_with_metadata(self):
        p = self.store.load(self.project["id"])
        aid = self.store.add_asset(p, "pose.png", png_bytes(Image.new("RGBA", (3, 4), "red")))
        p["animations"] = [{"id": "idle", "name": "待机", "slot": "neutral",
                            "variant": "normal", "kind": "loop", "fps": 60, "frameScale": 6,
                            "clips": [{"asset": aid, "hold": 3, "x": -1, "y": -4}]}]
        p["scene"] = {"duration": 4, "tracks": [{"id": "actor", "type": "actor",
                         "ref": "idle", "start": 0, "end": 4, "x": 17, "y": 23}]}
        self.store._write(p)
        baseline_zip, baseline_report = compile_project(self.store, p["id"])
        baseline_scene = compiled_scene_preview(self.store, self.store.load(p["id"]))
        baseline_contract = export_contract(self.store, self.store.load(p["id"]))
        files = archive_files(baseline_zip)
        self.assertTrue(any(name.startswith("compiled/") for name in files))
        for profile in ("reference", "custom"):
            with self.subTest(profile=profile):
                p = self.store.load(p["id"])
                original = copy.deepcopy(p)
                p["previewStage"] = stage(profile)
                validate(p)
                self.assertEqual({k: v for k, v in p.items() if k != "previewStage"}, original)
                # Hold revision constant to isolate metadata, not normal save accounting.
                self.store._write(p)
                persisted = self.path.read_bytes()
                compiled_zip, report = compile_project(self.store, p["id"])
                self.assertEqual(compiled_zip, baseline_zip)
                self.assertEqual(report, baseline_report)
                self.assertEqual(compiled_scene_preview(self.store, p), baseline_scene)
                self.assertEqual(export_contract(self.store, p), baseline_contract)
                self.assertEqual(self.path.read_bytes(), persisted)
                self.assert_stage_exact(stage(profile), self.store.load(p["id"])["previewStage"])
                p.pop("previewStage")
                self.store._write(p)

    def test_non_json_numbers_are_rejected_in_memory(self):
        from decimal import Decimal
        for key in ("width", "height", "originX", "originY", "targetX", "targetY"):
            for value in (complex(1, 0), Decimal("1")):
                with self.subTest(key=key, value=value):
                    p = self.store.load(self.project["id"])
                    p["previewStage"] = dict(stage(), **{key: value})
                    before = self.path.read_bytes()
                    for action in (lambda: validate(p), lambda: self.store.save(p)):
                        with self.assertRaises(StudioError) as raised:
                            action()
                        self.assertRegex(str(raised.exception), r"[\u4e00-\u9fff]")
                    self.assertEqual(self.path.read_bytes(), before)

    def reject_at_all_boundaries(self, invalid):
        p = self.store.load(self.project["id"])
        p["previewStage"] = copy.deepcopy(invalid)
        before = self.path.read_bytes()
        for action in (lambda: validate(copy.deepcopy(p)), lambda: self.store.save(p)):
            with self.assertRaises(StudioError) as raised:
                action()
            self.assertRegex(str(raised.exception), r"[\u4e00-\u9fff]")
        self.assertEqual(self.path.read_bytes(), before)
        # Build deliberately malformed external JSON, including NaN/Infinity;
        # the production serializer correctly refuses to emit these itself.
        external_json = json.dumps(p, ensure_ascii=False).encode("utf-8")
        other = ProjectStore(Path(self.temp.name) / "invalid-import")
        with self.assertRaises(StudioError) as raised:
            other.import_archive(make_zip({"project.json": external_json}))
        self.assertRegex(str(raised.exception), r"[\u4e00-\u9fff]")
        self.assertEqual(list(other.root.iterdir()), [])
        # Simulate malformed externally edited metadata, which export must refuse.
        self.path.write_bytes(external_json)
        with self.assertRaises(StudioError) as raised:
            self.store.export(p["id"])
        self.assertRegex(str(raised.exception), r"[\u4e00-\u9fff]")


def invalid_cases():
    for index, value in enumerate((None, [], (), "custom", 1, 1.0, True, False)):
        yield "object_" + str(index), value
    for key in stage():
        value = stage()
        del value[key]
        yield "missing_" + key, value
    for index, version in enumerate((None, True, False, 0, 2, -1, 1.0, "1", [], {}, float("nan"), float("inf"))):
        yield "version_" + str(index), dict(stage(), version=version)
    for index, profile in enumerate((None, True, False, "", "Reference", "CUSTOM", "unknown", 1, [], {})):
        yield "profile_" + str(index), dict(stage(), profile=profile)
    bad_numbers = (None, True, False, "0", "1", [], {},
                   float("nan"), float("inf"), float("-inf"), -(10**1000), 10**1000)
    for key in ("width", "height", "originX", "originY", "targetX", "targetY"):
        for index, number in enumerate(bad_numbers):
            yield key + "_type_" + str(index), dict(stage(), **{key: number})
        lower, upper = ((1, 8192) if key in ("width", "height") else
                        (0, stage()["width" if key.endswith("X") else "height"]))
        for label, number in (("below", lower - 0.001), ("above", upper + 0.001)):
            yield key + "_" + label, dict(stage(), **{key: number})


def rejection_test(value):
    def test(self):
        self.reject_at_all_boundaries(value)
    return test


for name, invalid in invalid_cases():
    setattr(SpatialPreviewTests, "test_reject_" + name, rejection_test(invalid))


if __name__ == "__main__":
    unittest.main()
