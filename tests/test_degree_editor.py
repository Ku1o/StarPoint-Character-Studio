"""Lettering-only safety checks, with opt-in read-only real title fixtures."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degree_editor
from studio_core import ProjectStore, png_bytes


def inside_convex(x, y, polygon):
    crosses = [(b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
               for a, b in zip(polygon, polygon[1:] + polygon[:1])]
    return min(crosses) >= -1e-9 or max(crosses) <= 1e-9


class DegreeEditorTests(unittest.TestCase):
    def setUp(self):
        output = Path(os.environ.get('STUDIO_UPGRADE_TEST_ROOT', tempfile.gettempdir())).resolve()
        output.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='degree-lettering-', dir=output)
        self.store = ProjectStore(Path(self.temp.name) / 'projects')
        self.project = self.store.create('Lettering fixture')
        self.row = {'id': 'one', 'name': 'Nameplate', 'safeAreaEvidence': 'fixture inner frame geometry'}
        self.project['degrees'] = [self.row]

    def tearDown(self):
        self.temp.cleanup()

    def asset(self, image, name='layer.png'):
        return self.store.add_asset(self.project, name, png_bytes(image), 'image')

    def fixture(self):
        artwork = Image.new('RGBA', (320, 50)); artwork.putpixel((0, 0), (20, 40, 80, 255))
        lettering = Image.new('RGBA', (320, 50)); lettering.putpixel((120, 25), (255, 250, 20, 255))
        artwork.alpha_composite(lettering)
        mask = Image.new('RGBA', (320, 50)); mask.paste((0, 0, 0, 255), (100, 10, 220, 40))
        self.row.update(asset=self.asset(artwork, 'artwork.png'), letteringAsset=self.asset(lettering, 'lettering.png'),
                        safeMaskAsset=self.asset(mask, 'safe.png'))
        return artwork, lettering, mask

    def test_frame_and_decoration_are_not_counted_as_lettering(self):
        artwork, _, _ = self.fixture()
        before = copy.deepcopy(self.project)
        full, _, result = degree_editor.preview(self.store, self.project, self.row)
        self.assertEqual(result['wholeArtworkCandidateOutsideSafePixels'], 1)
        self.assertEqual(result['letteringOutsideSafePixels'], 0)
        self.assertEqual(result['safeAreaStatus'], 'inside_declared_mask')
        self.assertEqual(result['safeAreaCheckObject'], 'lettering_with_outline_and_shadow')
        self.assertFalse(result['letteringCompositionVerified'])
        self.assertFalse(result['nativeVerified'])
        self.assertEqual(Image.open(io.BytesIO(full)).tobytes(), artwork.tobytes())
        self.assertEqual(self.project, before)

    def test_low_alpha_lettering_shadow_outside_is_detected(self):
        _, lettering, _ = self.fixture()
        lettering.putpixel((99, 25), (0, 0, 0, 1))
        self.row['letteringAsset'] = self.asset(lettering, 'shadow-outside.png')
        _, _, result = degree_editor.preview(self.store, self.project, self.row)
        self.assertEqual(result['letteringOutsideSafePixels'], 1)
        self.assertEqual(result['safeAreaStatus'], 'outside')
        self.assertEqual(result['letteringAlphaPositivePixels'], 2)

    def test_old_without_layer_is_unknown_even_when_whole_artwork_fits(self):
        _, lettering, _ = self.fixture()
        self.row['asset'] = self.asset(lettering, 'small-whole.png')
        self.row.pop('letteringAsset')
        _, _, result = degree_editor.preview(self.store, self.project, self.row)
        self.assertEqual(result['outsideSafePixels'], 0)
        self.assertIsNone(result['letteringOutsideSafePixels'])
        self.assertEqual(result['safeAreaStatus'], 'needs_lettering_layer')
        self.assertEqual(result['safeAreaCheckObject'], 'whole_artwork_candidate')

    def test_old_frame_outside_is_candidate_not_text_failure(self):
        self.fixture(); self.row.pop('letteringAsset')
        _, _, result = degree_editor.preview(self.store, self.project, self.row)
        self.assertEqual(result['wholeArtworkCandidateOutsideSafePixels'], 1)
        self.assertEqual(result['safeAreaStatus'], 'needs_lettering_layer')

    def test_empty_layer_or_missing_mask_evidence_does_not_turn_green(self):
        self.fixture()
        self.row['letteringAsset'] = self.asset(Image.new('RGBA', (320, 50)), 'empty.png')
        self.assertEqual(degree_editor.preview(self.store, self.project, self.row)[2]['safeAreaStatus'], 'empty_lettering_layer')
        self.fixture(); self.row.pop('safeMaskAsset')
        self.assertEqual(degree_editor.preview(self.store, self.project, self.row)[2]['safeAreaStatus'], 'needs_review')
        self.fixture(); self.row['safeAreaEvidence'] = ' '
        self.assertEqual(degree_editor.preview(self.store, self.project, self.row)[2]['safeAreaStatus'], 'needs_review')

    def test_lettering_dimensions_and_references_are_validated(self):
        self.fixture(); self.row['letteringAsset'] = self.asset(Image.new('RGBA', (160, 25)), 'wrong-size.png')
        with self.assertRaises(ValueError):
            degree_editor.preview(self.store, self.project, self.row)
        self.row['letteringAsset'] = 'missing'
        with self.assertRaises(ValueError):
            degree_editor.validate(self.project)

    def test_export_keeps_original_and_complete_lettering_separate(self):
        artwork, lettering, _ = self.fixture()
        files = degree_editor.compile_files(self.store, self.project)
        self.assertEqual(Image.open(io.BytesIO(files['handoff/degrees/one.png'])).tobytes(), artwork.tobytes())
        self.assertEqual(Image.open(io.BytesIO(files['handoff/degrees/one-lettering-complete.png'])).tobytes(), lettering.tobytes())
        report = degree_editor.report(self.store, self.project)
        self.assertEqual(report['degrees'][0]['safeAreaCheckObject'], 'lettering_with_outline_and_shadow')
        self.assertFalse(report['gameReady'])

    @unittest.skipUnless(all(os.environ.get(k) for k in ('STUDIO_TEST_DEGREE_RECEIPT', 'STUDIO_TEST_DEGREE_ARTWORK_ROOT', 'STUDIO_TEST_DEGREE_LAYER_ROOT', 'STUDIO_UPGRADE_TEST_ROOT')), 'real nameplate inputs and temporary mask output root not selected')
    def test_real_vyrn_lettering_and_inner_border_masks_read_only(self):
        receipt_path = Path(os.environ['STUDIO_TEST_DEGREE_RECEIPT']).resolve()
        receipt_bytes = receipt_path.read_bytes(); receipt = json.loads(receipt_bytes)
        artwork_root = Path(os.environ['STUDIO_TEST_DEGREE_ARTWORK_ROOT']).resolve()
        layer_root = Path(os.environ['STUDIO_TEST_DEGREE_LAYER_ROOT']).resolve()
        output = Path(os.environ['STUDIO_UPGRADE_TEST_ROOT']).resolve()
        records, protected = [], {receipt_path: receipt_bytes}
        for title in receipt['titles']:
            identifier = str(title['id']); safety = title['text_safety']; polygon = safety['safe_polygon']
            self.assertTrue(all(inside_convex(x, y, safety['actual_inner_border_polygon']) for x, y in polygon))
            paths = {'artwork': artwork_root / (identifier + '.png'), 'lettering': layer_root / identifier / 'lettering-complete.png',
                     'frame': layer_root / identifier / 'frame.png'}
            raw = {key: path.read_bytes() for key, path in paths.items()}; protected.update({paths[key]: value for key, value in raw.items()})
            self.assertEqual(hashlib.sha256(raw['artwork']).hexdigest(), title['sha256'])
            # Unlike drawing a polygon into a raster, this conservative mask
            # authorizes a pixel only when all four corners fit the receipt's
            # exact polygon. It adds no default border/margin of its own.
            mask = Image.new('RGBA', (320, 50))
            for y in range(50):
                for x in range(320):
                    if all(inside_convex(x + dx, y + dy, polygon) for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1))):
                        mask.putpixel((x, y), (0, 0, 0, 255))
            mask_path = output / (identifier + '-safe-mask.png'); mask.save(mask_path)
            images = {key: Image.open(io.BytesIO(value)).convert('RGBA') for key, value in raw.items()}
            self.assertEqual(list(images['lettering'].getchannel('A').getbbox()), safety['complete_ink_bbox'])
            row = {'id': identifier, 'name': title['name'], 'asset': self.asset(images['artwork'], identifier + '.png'),
                   'frameAsset': self.asset(images['frame'], identifier + '-frame.png'), 'letteringAsset': self.asset(images['lettering'], identifier + '-lettering.png'),
                   'safeMaskAsset': self.asset(mask, identifier + '-safe.png'),
                   'safeAreaEvidence': 'artwork-receipt text_safety.safe_polygon; all four pixel corners; threshold 0'}
            self.project['degrees'] = [row]
            _, _, result = degree_editor.preview(self.store, self.project, row)
            self.assertEqual(result['letteringOutsideSafePixels'], 0)
            self.assertEqual(result['letteringAlphaPositivePixels'], safety['alpha_positive_pixels'])
            self.assertGreater(result['wholeArtworkCandidateOutsideSafePixels'], 0)
            self.assertEqual(result['safeAreaStatus'], 'inside_declared_mask')
            original = degree_editor.compile_files(self.store, self.project)['handoff/degrees/' + identifier + '.png']
            self.assertEqual(Image.open(io.BytesIO(original)).tobytes(), images['artwork'].tobytes())
            records.append({'id': identifier, 'inputs': {key: {'path': str(paths[key]), 'sha256': hashlib.sha256(value).hexdigest()} for key, value in raw.items()},
                            'actualInnerBorderPolygon': safety['actual_inner_border_polygon'], 'safePolygon': polygon,
                            'mask': str(mask_path), 'maskMethod': 'all four corners of every pixel inside exact receipt polygon', 'result': result})
        self.assertTrue(all(path.read_bytes() == value for path, value in protected.items()))
        report = {'scope': 'offline lettering layer and declared inner-frame safe polygons; no native acceptance',
                  'receiptSHA256': hashlib.sha256(receipt_bytes).hexdigest(), 'originalsUnchanged': True, 'passed': True, 'titles': records}
        (output / 'degree-lettering-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')


if __name__ == '__main__':
    unittest.main()
