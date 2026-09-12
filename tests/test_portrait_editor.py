import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import ProjectStore, StudioError, png_bytes, image_from, archive_files, validate
from portrait_editor import render, selection
from studio_compile import compile_project
from atlas_editor import ui_atlas
from studio import create_server


class PortraitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(Path(self.tmp.name) / 'projects')
        master = Image.new('RGBA', (33, 41), (100, 40, 200, 120))
        master.putpixel((4, 5), (10, 20, 30, 255))
        self.master = png_bytes(master)
        ui = Image.new('RGBA', (7, 9), (15, 89, 42, 50))
        ui.putpixel((2, 3), (101, 210, 145, 0))
        self.ui = png_bytes(ui)
        self.p = self.store.import_reference({
            'reference/data_readable/identity.json': json.dumps({'name': '模板', 'code_name': 'test'}).encode(),
            'reference/ui/full_shot_1440_1920_0.png': self.master,
            'reference/ui/square_132_132_0.png': self.ui,
            'reference/ui/square_132_132_1.png': self.ui,
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_official_images_are_exact_and_full_shot_not_resized(self):
        self.assertEqual(render(self.store, self.p, 'base', 'full_shot'), self.master)
        for form in ('base', 'evolved'):
            self.assertEqual(render(self.store, self.p, form, 'square_132_132'), self.ui)
        self.assertIsNone(selection(self.p, 'base', 'thumb_party_main')['asset'])

    def test_legacy_mapping_uses_pixels_not_overwritten_names(self):
        original = dict(self.p['uiSources'])
        del self.p['uiSources']
        for a in self.p['assets'].values():
            a['name'] = 'some-upload.png'
        self.store._write(self.p)
        path = self.store.directory(self.p['id']) / 'project.json'
        before = path.read_bytes()
        hydrated = self.store.load(self.p['id'])
        self.assertEqual(hydrated['uiSources'], original)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(render(self.store, hydrated, 'evolved', 'square_132_132'), self.ui)

    def test_legacy_crop_and_custom_portrait_survive_load(self):
        self.p['crops']['base:square_132_132'] = {'x': .25, 'y': .3, 'zoom': 2}
        self.store._write(self.p)
        loaded = self.store.load(self.p['id'])
        spec = selection(loaded, 'base', 'square_132_132')
        self.assertEqual(spec['mode'], 'crop')
        self.assertTrue(spec['legacy'])
        self.assertEqual(image_from(render(self.store, loaded, 'base', 'square_132_132')).size, (132, 132))
        self.assertEqual(render(self.store, loaded, 'evolved', 'square_132_132'), self.ui)

    def test_crop_export_import_and_compile_pixels_match(self):
        spec = {'mode': 'crop', 'asset': self.p['portraits']['base'], 'width': 7, 'height': 9,
                'rect': {'x': 2, 'y': 3, 'width': 7, 'height': 9}, 'mask': 'none'}
        self.p['uiImages'] = {'base:square_132_132': spec}
        expected = image_from(self.master).crop((2, 3, 9, 12))
        preview = render(self.store, self.p, 'base', 'square_132_132')
        self.assertEqual(image_from(preview).tobytes(), expected.tobytes())
        saved = self.store.save(self.p)
        packed, report = compile_project(self.store, saved['id'])
        files = archive_files(packed)
        png = files['compiled/common/character/new_test/ui/square_132_132_0.png']
        self.assertEqual(image_from(png).tobytes(), expected.tobytes())
        self.assertNotIn('compiled/common/character/new_test/ui/thumb_party_main_0.png', files)
        self.assertFalse(report['gameReady'])
        imported = self.store.import_archive(self.store.export(saved['id']))
        self.assertEqual(render(self.store, imported, 'base', 'square_132_132'), preview)
        self.assertEqual(render(self.store, imported, 'evolved', 'square_132_132'), self.ui)

    def test_ui_atlas_preserves_every_rgba_byte_and_gutters(self):
        sheet, records = ui_atlas(self.store, self.p)
        self.assertEqual(len(records), 2)
        for r in records:
            cell = sheet.crop((r['x'], r['y'], r['x'] + r['w'], r['y'] + r['h']))
            self.assertEqual(cell.tobytes(), image_from(self.ui).tobytes())
            self.assertEqual(sheet.getpixel((r['x'] - 1, r['y'])), (0, 0, 0, 0))

    def test_invalid_edit_rejected_before_project_changes(self):
        self.p['uiImages'] = {'base:square_132_132': {'mode': 'crop', 'asset': self.p['portraits']['base'],
            'width': 132, 'height': 132, 'rect': {'x': 0, 'y': 0, 'width': 0, 'height': 20}}}
        with self.assertRaises(StudioError):
            self.store.save(self.p)
        self.assertEqual(self.store.load(self.p['id'])['revision'], self.p['revision'])
        self.p['uiImages'] = {'base:garbage': {'mode': 'image', 'asset': self.p['portraits']['base']}}
        with self.assertRaises(StudioError):
            validate(self.p)

    def test_http_download_is_file_and_live_crop_uses_export_renderer(self):
        server = create_server(self.store.root)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            token = json.load(urllib.request.urlopen(url + '/api/session'))['token']
            aid = self.p['uiSources']['base:square_132_132']
            with urllib.request.urlopen(f'{url}/api/asset?project={self.p["id"]}&id={aid}&download=1') as r:
                self.assertIn('attachment;', r.headers['Content-Disposition'])
                self.assertEqual(r.read(), self.ui)
            spec = {'mode': 'crop', 'asset': self.p['portraits']['base'], 'width': 7, 'height': 9,
                    'rect': {'x': 2, 'y': 3, 'width': 7, 'height': 9}, 'mask': 'none'}
            request = urllib.request.Request(url + '/api/portrait-render', data=json.dumps({'id': self.p['id'], 'form': 'base', 'slot': 'square_132_132', 'selection': spec}).encode(), headers={'Content-Type': 'application/json', 'X-Studio-Token': token})
            with urllib.request.urlopen(request) as r:
                self.assertEqual(r.read(), render(self.store, self.p, 'base', 'square_132_132', spec))
            with urllib.request.urlopen(f'{url}/api/atlas-export?id={self.p["id"]}&group=ui&cell=0') as r:
                self.assertEqual(image_from(r.read()).tobytes(), image_from(self.ui).tobytes())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
