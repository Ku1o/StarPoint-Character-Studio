"""Compare actual author-declaration JavaScript with Python source classification."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio_core import COMPANION_SUFFIXES, animation_variant, clip_variant


NODE_RUNNER = r"""
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({
  S: {p: null},
  esc: value => String(value == null ? '' : value).replace(/[&<>"']/g, char =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'})[char])
});
vm.runInContext(fs.readFileSync(input.source, 'utf8'), context);
function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
const results = input.samples.map(sample => {
  const before = JSON.stringify(sample);
  context.S.p = freeze(sample.project);
  context.animation = freeze(sample.animation);
  const source = vm.runInContext('authorAnimationSource(animation)', context);
  const badge = vm.runInContext('authorAnimationBadge(animation)', context);
  const row = sample.render ? vm.runInContext('authorAnimationRow(animation)', context) : null;
  const repeat = vm.runInContext('authorAnimationSource(animation)', context);
  if (JSON.stringify(sample) !== before || JSON.stringify(source) !== JSON.stringify(repeat)) {
    throw new Error('Source classification or rendering mutated its input');
  }
  return {source, badge, row};
});
process.stdout.write(JSON.stringify(results));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend parity tests")
class AuthorAnimationSourceTests(unittest.TestCase):
    def sample(self, asset, **animation_fields):
        animation = {"id": "idle", "slot": "neutral", "name": "Idle",
                     "kind": "loop", "clips": [{"asset": "frame", "hold": 1}]}
        animation.update(animation_fields)
        return {"project": {"assets": {"frame": asset}}, "animation": animation}

    def evaluate(self, samples):
        before = copy.deepcopy(samples)
        completed = subprocess.run(
            [shutil.which("node"), "-e", NODE_RUNNER],
            input=json.dumps({"source": str(ROOT / "web" / "author-declarations.js"),
                              "samples": samples}),
            text=True, encoding="utf-8", capture_output=True, check=True, timeout=30,
        )
        self.assertEqual(samples, before)
        results = json.loads(completed.stdout)
        for sample, result in zip(samples, results):
            project, animation = sample["project"], sample["animation"]
            clips = animation.get("clips")
            clips = clips if isinstance(clips, list) else []
            expected_counts = dict.fromkeys(("plain", "composite", "unknown"), 0)
            for clip in clips:
                if isinstance(clip, dict):
                    expected_counts[clip_variant(project, clip.get("asset"))] += 1
            with self.subTest(sample=sample):
                self.assertEqual(result["source"]["counts"], expected_counts)
                # The UI deliberately labels an empty animation as unknown, not "".
                self.assertEqual(result["source"]["kind"], animation_variant(project, animation) or "unknown")
                self.assertIn("author-source-" + result["source"]["kind"], result["badge"])
        return results

    def test_companion_suffixes_outrank_labels_in_every_source_field(self):
        samples = []
        for field in ("name", "file", "sourceFile", "sourceName", "logical"):
            for suffix in COMPANION_SUFFIXES:
                for variant in (None, "plain", "composite", "effect", "ui", "unknown"):
                    asset = {"name": "frame.png", field: "FRAME" + suffix.upper() + ".PNG"}
                    if variant is not None:
                        asset["variant"] = variant
                    samples.append(self.sample(asset))
        results = self.evaluate(samples)
        self.assertTrue(all(result["source"]["kind"] == "composite" for result in results))

    def test_multi_source_evidence_and_legacy_sp_regression(self):
        samples = [self.sample(asset) for asset in (
            {"name": "idle_sp.png"},
            {"name": "idle.png", "file": "hash.png", "sourceName": "idle_sp.png", "variant": "plain"},
            {"name": "idle_sp.png", "sourceFile": "idle.png", "variant": "plain"},
            {"file": "legacy_SuMmOn.PNG"},
            {"logical": "folder/idle_glow.png"},
            {"sourceFile": "idle_eff"},
            {"name": "idle_sp.png\n", "variant": "plain"},
        )]
        results = self.evaluate(samples)
        self.assertTrue(all(result["source"]["kind"] == "composite" for result in results))
        self.assertTrue(all(result["source"]["inferred"] == 1 for result in results))

    def test_plain_fallback_and_exact_suffix_boundaries(self):
        samples = [self.sample(asset) for asset in (
            {"name": "legacy.png"}, {"file": "hash.png"}, {"sourceFile": "legacy.png"},
            {"sourceName": "legacy.png"}, {"logical": "legacy"}, {"name": " "},
            {"name": "idle_sp_extra.png"}, {"name": "idle_sp.png.backup"},
            {"name": "sp.png"}, {"name": "idle_glowing.png"}, {"name": "idle_sp\n"},
            {"name": "idle.png", "variant": "invalid"},
            {"name": "idle.png", "variant": "PLAIN"},
        )]
        results = self.evaluate(samples)
        self.assertTrue(all(result["source"]["kind"] == "plain" for result in results))
        self.assertTrue(all(result["source"]["inferred"] == 1 for result in results))

    def test_valid_labels_without_filename_evidence(self):
        results = self.evaluate([self.sample(asset) for asset in (
            {"variant": "plain"}, {"variant": "composite"},
            {"name": "ordinary.png", "variant": "composite"},
            {"name": "ordinary.png", "variant": "plain"},
        )])
        self.assertEqual([r["source"]["kind"] for r in results],
                         ["plain", "composite", "composite", "plain"])
        self.assertTrue(all(r["source"]["inferred"] == 0 for r in results))

    def test_effect_ui_unknown_and_missing_evidence_stay_unknown(self):
        assets = [{"name": "ordinary.png", "variant": variant}
                  for variant in ("effect", "ui", "unknown")]
        assets += [{}, {"name": "", "file": None},
                   {"name": 7, "sourceName": [], "logical": {}}, None, [], "invalid"]
        results = self.evaluate([self.sample(asset) for asset in assets])
        self.assertTrue(all(r["source"]["kind"] == "unknown" for r in results))
        self.assertTrue(all(r["source"]["inferred"] == 0 for r in results))

    def test_mixed_counts_unknown_clips_and_empty_animation(self):
        project = {"assets": {"p": {"name": "idle.png"},
                              "c": {"sourceFile": "idle_sp.png", "variant": "plain"},
                              "u": {"name": "effect.png", "variant": "effect"}}}
        samples = []
        for ids in (("p", "c", "c", "u", "missing"), ("p", "u"), ("c", "u"), ()):
            samples.append({"project": project,
                            "animation": {"clips": [{"asset": aid} for aid in ids]}})
        results = self.evaluate(samples)
        self.assertEqual(results[0]["source"]["counts"], {"plain": 1, "composite": 2, "unknown": 2})
        self.assertEqual(results[0]["source"]["inferred"], 3)
        self.assertEqual([r["source"]["kind"] for r in results],
                         ["mixed", "unknown", "composite", "unknown"])

    def test_invalid_containers_and_clip_records(self):
        samples = [{"project": {"assets": assets}, "animation": {"clips": [
            None, "invalid", [], {}, {"asset": None}, {"asset": 7}]}}
                   for assets in ({}, [], None)]
        samples += [{"project": {"assets": {}}, "animation": {"clips": clips}}
                    for clips in (None, {}, "invalid")]
        self.evaluate(samples)

    def test_badge_warning_inference_and_rendering_are_read_only(self):
        samples = []
        for variant in (None, "plain", "composite"):
            asset = {"name": "idle_sp.png"}
            if variant is not None:
                asset["variant"] = variant
            sample = self.sample(asset, includesCompanion=False, companionNote="",
                                 purpose="Idle purpose")
            sample["project"]["authorNotes"] = "Do not rewrite"
            sample["render"] = True
            samples.append(sample)
        results = self.evaluate(samples)
        for result in results:
            self.assertIn("来源：合成帧（composite）", result["badge"])
            self.assertIn("author-warning", result["row"])
            self.assertIn("说明不会自动替换画稿", result["row"])
        self.assertIn("文件名推断仅供核对，不代表作者已确认", results[0]["row"])
        self.assertIn("文件名推断仅供核对，不代表作者已确认", results[1]["row"])
        self.assertNotIn("文件名推断仅供核对，不代表作者已确认", results[2]["row"])


if __name__ == "__main__":
    unittest.main()
