"""Single-reference playback preserves model, disk bytes and native draft gates."""
import base64
import copy
import hashlib
import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import author_reuse
import reference_preview
from effect_channels import compose_frames, make_channels
from studio_core import ProjectStore, StudioError


class ReferencePreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / 'projects')
        self.p = self.store.create('原声画参考')
        stream = io.BytesIO(); Image.new('RGBA', (4, 6), (20, 30, 40, 127)).save(stream, 'PNG')
        self.png = stream.getvalue()
        self.add_asset('pixel', 'pixel.png', self.png, 'image/png')
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000); out.writeframes(b'\0\0' * 80)
        self.wav = stream.getvalue()
        self.add_asset('tone', 'tone.wav', self.wav, 'audio/wav')
        self.p['animations'] = [{'id': 'action', 'name': '动作', 'kind': 'loop', 'frameScale': 1.5,
                                  'runtimeSpeed': .5, 'clips': [
                                      {'asset': 'pixel', 'hold': 3, 'x': 3, 'y': -2, 'scale': 2, 'rotation': 90, 'flip': True, 'opacity': .4},
                                      {'asset': 'pixel', 'hold': 2, 'x': -5, 'y': 7, 'scale': .5, 'rotation': -20, 'opacity': .8}]}]

    def add_asset(self, aid, name, raw, mime):
        folder = self.store.directory(self.p['id']) / 'assets'; folder.mkdir(exist_ok=True)
        (folder / name).write_bytes(raw)
        self.p['assets'][aid] = {'id': aid, 'file': name, 'mime': mime, 'sha256': hashlib.sha256(raw).hexdigest()}

    def option(self, kind='animation'):
        return next(item for item in author_reuse.catalog(self.store, self.p)['options'] if item['kind'] == kind)

    def play(self, kind='animation'):
        option = self.option(kind)
        return reference_preview.preview(self.store, self.p, option['id'], option['identity']['sha256'])

    def test_clip_hold_transform_opacity_speed_and_original_png_are_preserved(self):
        before = copy.deepcopy(self.p)
        disk = (self.store.directory(self.p['id']) / 'project.json').read_bytes()
        with mock.patch('studio_compile.compiled_preview', side_effect=AssertionError('must not compile')):
            result = self.play()
        self.assertEqual(len(result['frames']), 5)
        self.assertEqual(result['frames'][0:3], [result['frames'][0]] * 3)
        cmd = result['frames'][0][0]
        for got, expected in zip(cmd['matrix'], [0, -2, -2, 0, 7, 4]):
            self.assertAlmostEqual(got, expected)
        self.assertEqual((cmd['fx'], cmd['fy'], cmd['alpha']), (2, 3, .4))
        self.assertEqual(result['scale'], 1.5); self.assertEqual(result['runtimeSpeed'], .5)
        self.assertEqual(base64.b64decode(result['assets']['pixel'].split(',')[1]), self.png)
        self.assertTrue(result['readonly']); self.assertFalse(result['gameReady']); self.assertFalse(result['behaviorVerified'])
        self.assertEqual(self.p, before)
        self.assertEqual((self.store.directory(self.p['id']) / 'project.json').read_bytes(), disk)

    def test_original_sound_bytes_and_animation_event_times_are_not_transcoded(self):
        self.p['sounds'] = [{'id': 'original', 'name': '实际声音', 'asset': 'tone'}]
        result = self.play('sound')
        self.assertEqual(result['mode'], 'sound')
        self.assertEqual(base64.b64decode(result['audio'][0]['url'].split(',')[1]), self.wav)
        self.p['animations'][0]['soundEvents'] = [{'id': 's', 'asset': 'tone', 'start': 2, 'end': 4, 'loop': -1, 'volume': .37}]
        result = self.play()
        sound = result['audio'][0]
        self.assertEqual((sound['start'], sound['end'], sound['loop'], sound['volume']), (2, 4, -1, .37))
        self.assertEqual(base64.b64decode(sound['url'].split(',')[1]), self.wav)

    def native_effect(self):
        effect = {'id': 'effect', 'name': '骨架', 'kind': 'pass', 'native': {}, 'frameScale': .25,
                  'nativeFrames': [[{'asset': 'pixel', 'matrix': [1, .3, -.2, 2, 12, -8], 'alpha': .6,
                                     'fx': 2, 'fy': 1, 'channel': 'source', 'colorTransform': [.8, 3, 5, 7]}] for _ in range(4)],
                  'layers': {'pixel': {'asset': 'pixel', 'x': 2, 'y': -3, 'visible': True}}, 'clips': []}
        effect['native'] = {'sequence': 'normal'}
        self.p['effects'] = [effect]
        return effect

    def test_legacy_native_layer_offsets_preserve_original_commands(self):
        effect = self.native_effect(); before = copy.deepcopy(effect)
        result = self.play('effect')
        command = result['frames'][0][0]
        self.assertEqual(command['matrix'], effect['nativeFrames'][0][0]['matrix'])
        self.assertEqual((command['fx'], command['fy']), (0, 4))
        self.assertEqual(command['colorTransform'], [.8, 3, 5, 7])
        self.assertEqual(effect, before)

    def test_channel_retime_keys_and_replacement_match_shared_runtime_composer(self):
        effect = self.native_effect(); make_channels(effect)
        effect['channels'][0].update(start=1, end=6, sourceEnd=4, keys=[
            {'frame': 1, 'x': 2, 'rotation': 30, 'scale': 1, 'opacity': .9},
            {'frame': 5, 'x': 18, 'rotation': 120, 'scale': 2, 'opacity': .2}])
        effect['channelDuration'] = 7
        before = copy.deepcopy(effect)
        self.assertEqual(self.play('effect')['frames'], compose_frames(effect))
        self.assertEqual(effect, before)

    def test_stale_or_missing_digest_and_changed_object_are_rejected(self):
        selected = self.option()
        for digest in (None, '', '0' * 64):
            with self.subTest(digest=digest), self.assertRaises(StudioError):
                reference_preview.preview(self.store, self.p, selected['id'], digest)
        self.p['animations'][0]['clips'][0]['hold'] = 4
        with self.assertRaises(StudioError):
            reference_preview.preview(self.store, self.p, selected['id'], selected['identity']['sha256'])

    def test_corrupt_missing_or_escaped_asset_never_plays(self):
        self.p['assets']['pixel']['sha256'] = '0' * 64
        with self.assertRaisesRegex(StudioError, 'SHA'):
            self.play()
        self.p['assets']['pixel']['file'] = '../outside.png'
        with self.assertRaisesRegex(StudioError, '缺少'):
            self.play()
        self.p['assets'].pop('pixel')
        with self.assertRaisesRegex(StudioError, '缺少'):
            self.play()

    def test_limits_and_nan_refuse_before_animation_or_audio_start(self):
        self.p['animations'][0]['clips'][0]['hold'] = 4096
        with self.assertRaises(StudioError):
            self.play()
        self.p['animations'][0]['clips'][0]['hold'] = 3
        with mock.patch.object(reference_preview, 'MAX_RESPONSE_BYTES', 1), self.assertRaises(StudioError):
            self.play()
        self.native_effect()['nativeFrames'][0][0]['matrix'][0] = 1000001
        with self.assertRaises(StudioError):
            self.play('effect')

    def test_old_illegal_native_rows_do_not_require_removal_or_character_compile(self):
        from test_native_gameplay import pack
        import native_gameplay
        definition = pack()
        class Library:
            def load(inner): return definition
        self.p = native_gameplay.attach(self.store, self.p['id'], 0, Library(), '10')
        self.p['animations'] = [{'id': 'saved', 'kind': 'once', 'clips': [{'asset': 'pixel', 'hold': 2}]}]
        self.add_asset('pixel', 'pixel.png', self.png, 'image/png')
        native = self.p['nativeGameplay']
        native['source']['data']['character']['records']['abilities']['selected']['81']['rows'][0][6] = ''
        native['source']['sha256'] = native_gameplay.digest(native['source']['data'])
        native['abilities'][0]['rows'][0][6] = ''
        before = copy.deepcopy(native)
        self.assertEqual(len(self.play()['frames']), 2)
        self.assertEqual(native, before)

    def test_skill_and_summon_are_pending_without_fabricated_damage_or_media(self):
        for kind in ('skill', 'summon'):
            entry = {'id': 'bounded', 'kind': kind, 'label': '待核参考', 'model': {}, 'identity': {'sha256': 'a' * 64}}
            with self.subTest(kind=kind), mock.patch.object(author_reuse, '_snapshot', return_value=([entry], {}, {}, [])):
                result = reference_preview.preview(self.store, self.p, 'bounded', 'a' * 64)
            self.assertEqual(result['mode'], 'pending'); self.assertEqual(result['status'], 'pending')
            self.assertEqual(result['frames'], []); self.assertEqual(result['audio'], [])
            self.assertTrue(result['issues']); self.assertFalse(result['gameReady'])

    def test_actual_summon_command_list_is_pending_and_unchanged(self):
        from test_native_summon_dependencies import summon_command
        model = summon_command(1110022)
        self.assertIsInstance(model, list)
        before = copy.deepcopy(model)
        entry = {'id': 'actual-summon', 'kind': 'summon', 'label': '实际召唤参考',
                 'model': model, 'identity': {'sha256': 'b' * 64}}
        with mock.patch.object(author_reuse, '_snapshot', return_value=([entry], {}, {}, [])), \
                mock.patch('studio_compile.compiled_preview', side_effect=AssertionError('must not compile')):
            result = reference_preview.preview(self.store, self.p, 'actual-summon', 'b' * 64)
        self.assertEqual(result['kind'], 'once')
        self.assertEqual(result['mode'], 'pending'); self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['frames'], []); self.assertEqual(result['audio'], [])
        self.assertTrue(result['issues']); self.assertFalse(result['gameReady'])
        self.assertEqual(model, before); self.assertEqual(entry['model'], before)

    def test_dynamic_asset_notes_stay_pending_and_model_unknowns_survive(self):
        self.p['animations'][0]['issues'] = ['运行时对象坐标尚待核验']
        self.p['animations'][0]['customUnknown'] = {'retained': [2, 3]}
        before = copy.deepcopy(self.p)
        result = self.play()
        self.assertEqual(result['status'], 'pending')
        self.assertIn('运行时对象坐标尚待核验', result['issues'])
        self.assertEqual(self.p, before)


if __name__ == '__main__':
    unittest.main()
