"""Independent integration checks for additive workshop contracts and originals."""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import wave

from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_review
import degree_editor
import entry_layout
import portrait_editor
import project_storage
from audio_compile import encoded_sound
from bridge import mp3_decode
from studio_core import ProjectStore, StudioError, archive_files, json_bytes, make_zip, png_bytes, UI_SLOTS


def tree_state(root):
    return {path.relative_to(root).as_posix(): 'directory' if path.is_dir() else
            hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*')}


def draft_png(size=(16, 24), color=(32, 50, 80, 255)):
    image = Image.new('RGBA', size, color)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('author-description', 'original source bytes')
    out = io.BytesIO()
    image.save(out, format='PNG', pnginfo=metadata)
    return out.getvalue()


def sine_wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(44100)
        # Full three-second sentence fixture; distinct channels make folding observable.
        writer.writeframes(b''.join(struct.pack('<hh',
            int(6000 * math.sin(2 * math.pi * 440 * i / 44100)),
            int(3500 * math.sin(2 * math.pi * 440 * i / 44100))) for i in range(132300)))
    return out.getvalue()


def reference_bundle():
    """Distinct original sheets yield one identical derived image: source refs matter."""
    prefix = 'delivered/author-character/reference/'
    files = {prefix + 'data_readable/identity.json': json_bytes({
        'character_id': 'fixture', 'name': '原参考角色', 'code_name': 'reference_fixture'}),
        prefix + 'author-notes.txt': '正面、作者俯视姿态分别按稿定义'.encode()}
    for variant, stem, sheet_name in (('normal', 'pixelart', 'sprite_sheet'),
                                      ('special', 'special', 'special_sprite_sheet')):
        sheet = Image.new('RGBA', (8, 5))
        sheet.paste((30, 70, 110, 255), (2, 1, 5, 3))
        note = PngImagePlugin.PngInfo()
        note.add_text('author-variant', variant)
        out = io.BytesIO()
        sheet.save(out, format='PNG', pnginfo=note)
        files[prefix + f'pixelart/{sheet_name}.png'] = out.getvalue()
        files[prefix + f'pixelart/{sheet_name}.atlas.json'] = json_bytes([
            {'n': f'character/fixture/{stem}1', 'x': 2, 'y': 1, 'w': 3, 'h': 2,
             'fx': -2, 'fy': -3, 'fw': 16, 'fh': 24}])
        files[prefix + f'pixelart/{stem}.timeline.json'] = json_bytes({
            'sequences': [{'name': 'neutral' if variant == 'normal' else 'special_pose',
                           'kind': 'loop' if variant == 'normal' else 'once', 'begin': 1, 'end': 2}],
            'sounds': [], 'points': [], 'circles': []})
        files[prefix + f'pixelart/{stem}.frame.json'] = json_bytes({'x': -8, 'y': -24, 'scale': 6})
    return files, make_zip(files), prefix


class WorkshopUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workshop-upgrade-independent-')
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / 'projects')
        self.p = self.store.create('Independent workshop fixture')

    def tearDown(self):
        self.temp.cleanup()

    def receive(self):
        raw = make_zip({'draft/author.png': draft_png(), 'draft/intent.txt': '作者俯视移动姿态'.encode()})
        result = self.store.import_source_archive(self.p['id'], 'author-original.zip', raw,
                                                  self.p['revision'])
        self.p = result['project']
        return raw, result['package']

    def test_source_zip_roundtrip_keeps_actual_package_and_original_member_bytes(self):
        raw, package = self.receive()
        self.p['sourceIntake']['futureIntake'] = {'preserve': True}
        self.p['sourceIntake']['packages'][0]['futurePackage'] = {'transport': 'author unknown extension'}
        self.p['sourceIntake']['sources'][0]['futureSource'] = {'maskDescription': 'author draft'}
        package = copy.deepcopy(self.p['sourceIntake']['packages'][0])
        self.store._write(self.p)
        again = self.store.import_source_archive(self.p['id'], 'same-author.zip', raw, self.p['revision'])
        self.p = again['project']
        self.assertEqual(len(self.p['sourceIntake']['packages']), 1)
        self.assertEqual(len(self.p['sourceIntake']['sources']), 2)
        self.assertEqual(again['package'], package)
        exported = self.store.export(self.p['id'])
        target = ProjectStore(self.root / 'restored')
        restored = target.import_archive(exported)
        self.assertEqual(restored['sourceIntake'], self.p['sourceIntake'])
        self.assertEqual((target.directory(restored['id']) / package['blob']).read_bytes(), raw)
        received_members = archive_files(raw)
        for source in restored['sourceIntake']['sources']:
            self.assertEqual((target.directory(restored['id']) / source['blob']).read_bytes(),
                             received_members[source['path']])
        self.assertFalse(json.loads(archive_files(exported)['制作交接.json'])['gameReady'])

    def test_archive_tampered_raw_or_missing_source_rejects_before_writing(self):
        self.receive()
        files = archive_files(self.store.export(self.p['id']))
        source = self.p['sourceIntake']['sources'][0]
        for changed in ('tampered', 'missing'):
            target = ProjectStore(self.root / changed)
            payload = copy.deepcopy(files)
            if changed == 'tampered':
                payload[source['blob']] = b'changed original'
            else:
                payload.pop(source['blob'])
            before = tree_state(target.root)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                target.import_archive(make_zip(payload))
            self.assertEqual(tree_state(target.root), before)

    def test_package_member_relation_cannot_be_forged_with_self_consistent_new_hash(self):
        self.receive()
        files = archive_files(self.store.export(self.p['id']))
        project = json.loads(files['project.json'])
        source = project['sourceIntake']['sources'][0]
        forged = b'not a member of the preserved original ZIP'
        digest = hashlib.sha256(forged).hexdigest()
        source.update(sha256=digest, size=len(forged), blob='sources/' + digest + '.raw')
        files[source['blob']] = forged
        files['project.json'] = json_bytes(project)
        files['source-intake.json'] = json_bytes(project['sourceIntake'])
        target = ProjectStore(self.root / 'forged-member')
        before = tree_state(target.root)
        with self.assertRaises(ValueError):
            target.import_archive(make_zip(files))
        self.assertEqual(tree_state(target.root), before)

    def test_rejected_source_zip_with_existing_corrupted_blob_has_no_partial_write(self):
        self.receive()
        source = next(row for row in self.p['sourceIntake']['sources'] if row['path'].endswith('intent.txt'))
        (self.store.directory(self.p['id']) / source['blob']).write_bytes(b'external corruption')
        before = tree_state(self.store.root)
        second = make_zip({'new/first.txt': b'new original input',
                           'draft/intent.txt': '作者俯视移动姿态'.encode()})
        with self.assertRaises(ValueError):
            self.store.import_source_archive(self.p['id'], 'second.zip', second, self.p['revision'])
        self.assertEqual(tree_state(self.store.root), before)

    def test_source_identity_edit_rejection_does_not_add_snapshot_or_write(self):
        self.receive()
        incoming = copy.deepcopy(self.p)
        incoming['sourceIntake']['sources'][0]['path'] = 'rewritten-path.png'
        before = tree_state(self.store.root)
        with self.assertRaises(ValueError):
            self.store.save(incoming)
        self.assertEqual(tree_state(self.store.root), before)

    def test_legacy_read_export_and_first_edit_keep_unknown_fields_exact_initial_snapshot(self):
        legacy = copy.deepcopy(self.p)
        for key in ('productionBrief', 'sourceIntake', 'degrees', 'audioProfile', 'formatVersion'):
            legacy.pop(key, None)
        legacy['futureField'] = {'authorIntent': ['front', 'top-down'], 'evidence': {'unknown': True}}
        legacy['animations'][0]['futureAnimation'] = {'notes': 'legacy author draft'}
        original = (json.dumps(legacy, ensure_ascii=False, indent=3) + '\n').encode()
        path = self.store.directory(legacy['id']) / 'project.json'
        path.write_bytes(original)
        before = tree_state(self.store.root)
        loaded = self.store.load(legacy['id'])
        self.store.export(legacy['id'])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(tree_state(self.store.root), before)
        self.assertNotIn('sourceIntake', loaded)
        self.assertNotIn('degrees', loaded)
        loaded['identity']['title'] = 'updated character title'
        saved = self.store.save(loaded)
        self.assertEqual(saved['futureField'], legacy['futureField'])
        self.assertEqual(saved['animations'][0]['futureAnimation'], legacy['animations'][0]['futureAnimation'])
        snapshots = list((path.parent / 'history').glob('*.json'))
        self.assertTrue(any(snapshot.read_bytes() == original for snapshot in snapshots))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg measurement unavailable')
    def test_audio_candidate_is_separate_original_bindings_and_packaging_stay_intact(self):
        raw = sine_wav()
        aid = self.store.add_asset(self.p, 'voice/full-original.wav', raw, 'voice')
        self.p['voices'] = [{'id': 'full_sentence', 'name': '完整语音', 'asset': aid,
                             'usage': 'join', 'text': '完整的原始台词。'}]
        self.p['audioProfile'] = {'voice': {'targetLufs': -23, 'truePeakCeilingDbtp': -2}}
        self.store._write(self.p)
        before_intake = copy.deepcopy(self.p['sourceIntake'])
        result = audio_review.create_candidate(self.store, self.p['id'], self.p['revision'], aid)
        p, candidate = result['project'], result['candidate']
        cid = candidate['candidateAsset']
        self.assertNotEqual(cid, aid)
        self.assertEqual(self.store.asset_bytes(p, aid), raw)
        self.assertEqual(p['voices'][0]['asset'], aid)
        self.assertEqual(p['sourceIntake']['sources'], before_intake['sources'])
        self.assertTrue(candidate['candidateNotApplied'])
        self.assertFalse(candidate['nativeVerified'])
        self.assertEqual(candidate['postEncodeDecode']['measurementChannels'], 1)
        self.assertLess(abs(candidate['durationDeltaSeconds']), .08)
        self.assertEqual(mp3_decode(encoded_sound(self.store, p, cid)), self.store.asset_bytes(p, cid))
        pending = audio_review.project_report(self.store, p)
        self.assertEqual(pending['rows'][0]['status'], 'handoff_only')
        bound = copy.deepcopy(p)
        bound['voices'][0].update(asset=cid, candidateOf=aid)
        checked = audio_review.project_report(self.store, bound)['rows'][0]
        self.assertTrue(checked['packagingRoundtrip'])
        self.assertTrue(checked['postEncodeDecode']['fullDecode'])
        self.assertFalse(checked['runtimeAccepted'])
        restored_store = ProjectStore(self.root / 'audio-restored')
        restored = restored_store.import_archive(self.store.export(p['id']))
        self.assertEqual(restored['audioCandidates'], p['audioCandidates'])
        self.assertEqual(restored_store.asset_bytes(restored, aid), raw)
        self.assertEqual(restored_store.asset_bytes(restored, cid), self.store.asset_bytes(p, cid))

    def test_entry_candidate_reports_word_changes_without_mutating_original_or_approval(self):
        original = '这是原始台词……\n最后一句必须保留。'
        voice = {'id': 'join_text', 'asset': '', 'usage': 'join', 'text': original,
                 'entryLayout': {'original': original, 'candidate': original.replace('\n', ''),
                                 'authorConfirmed': False, 'futureLayout': {'reason': 'line break only'}}}
        self.p['voices'] = [voice]
        before = copy.deepcopy(self.p)
        report = entry_layout.report(self.p)
        self.assertFalse(report['entries'][0]['wordingChanged'])
        self.assertFalse(report['entries'][0]['authorConfirmed'])
        self.assertFalse(report['entries'][0]['nativeVerified'])
        self.assertEqual(self.p, before)
        shortened = entry_layout.preview(original, '这是原始台词。')
        self.assertTrue(shortened['wordingChanged'])
        self.assertTrue(shortened['changes'])
        markup = entry_layout.preview(original, '<font size="10">台词</font>')
        self.assertIn('<font', ''.join(markup['lines']))
        self.assertTrue(markup['approximate'])

    def test_degree_preview_and_handoff_preserve_character_title_and_full_artwork(self):
        raw = draft_png((320, 50))
        aid = self.store.add_asset(self.p, 'degree/original.png', raw, 'image')
        mask = Image.new('RGBA', (320, 50))
        mask.paste((0, 0, 0, 255), (5, 5, 315, 45))
        mid = self.store.add_asset(self.p, 'degree/safe-mask.png', png_bytes(mask), 'image')
        self.p['identity']['title'] = '角色资料头衔'
        self.p['degrees'] = [{'id': 'wearable_one', 'name': '可佩戴铭牌', 'asset': aid,
                             'safeMaskAsset': mid, 'safeAreaEvidence': 'fixture real frame geometry',
                             'futureDegree': {'reward': 'maker pending'}}]
        before = copy.deepcopy(self.p)
        full, half, report = degree_editor.preview(self.store, self.p, self.p['degrees'][0])
        self.assertEqual(Image.open(io.BytesIO(full)).size, (320, 50))
        self.assertEqual(Image.open(io.BytesIO(half)).size, (160, 25))
        self.assertGreater(report['outsideSafePixels'], 0)
        self.assertEqual(report['safeAreaStatus'], 'needs_lettering_layer')
        self.assertEqual(report['safeAreaCheckObject'], 'whole_artwork_candidate')
        self.assertIsNone(report['letteringOutsideSafePixels'])
        self.assertFalse(report['nativeVerified'])
        self.assertFalse(report['gameReady'])
        self.assertEqual(self.p, before)
        with_lettering = copy.deepcopy(self.p)
        with_lettering['degrees'][0]['letteringAsset'] = aid
        _, _, lettering_report = degree_editor.preview(self.store, with_lettering, with_lettering['degrees'][0])
        self.assertEqual(lettering_report['safeAreaStatus'], 'outside')
        self.assertEqual(lettering_report['safeAreaCheckObject'], 'lettering_with_outline_and_shadow')
        self.assertEqual(Image.open(io.BytesIO(full)).tobytes(), Image.open(io.BytesIO(raw)).tobytes())
        exported = degree_editor.compile_files(self.store, self.p)
        self.assertIn('handoff/degrees/wearable_one.png', exported)
        self.assertEqual(self.store.asset_bytes(self.p, aid), png_bytes(Image.open(io.BytesIO(raw)).convert('RGBA')))
        self.store._write(self.p)
        target = ProjectStore(self.root / 'degree-restored')
        restored = target.import_archive(self.store.export(self.p['id']))
        self.assertEqual(restored['identity']['title'], '角色资料头衔')
        self.assertEqual(restored['degrees'], self.p['degrees'])

    def test_degree_numeric_identifier_is_rejected_before_compile(self):
        p = copy.deepcopy(self.p)
        p['degrees'] = [{'id': 123, 'name': 'invalid ID'}]
        with self.assertRaises(ValueError):
            degree_editor.validate(p)

    def test_reference_original_zip_full_paths_and_atlas_derivatives_roundtrip(self):
        files, raw, prefix = reference_bundle()
        p = self.store.import_archive(raw, 'actual-original-reference.zip')
        intake = p['sourceIntake']
        self.assertEqual(len(intake['packages']), 1)
        package = intake['packages'][0]
        self.assertEqual(package['name'], 'actual-original-reference.zip')
        self.assertEqual(package['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual((self.store.directory(p['id']) / package['blob']).read_bytes(), raw)
        # Untrimmed generated cell names are deliberately absent from author originals.
        self.assertEqual({s['path'] for s in intake['sources']}, set(files))
        self.assertTrue(all(s['path'].startswith(prefix) for s in intake['sources']))
        source_index = {s['id']: s for s in intake['sources']}
        for mapping in intake['derivatives']:
            source = source_index[mapping['source']]
            self.assertEqual((self.store.directory(p['id']) / source['blob']).read_bytes(), files[source['path']])
            self.assertTrue(source['path'].endswith('.png'))
            self.assertEqual(mapping['rect'], [2, 1, 3, 2])
            self.assertEqual(mapping['transform']['operation'], 'atlas-untrim')
            atlas_source = source_index[mapping['transform']['atlasSource']]
            self.assertTrue(atlas_source['path'].endswith('.atlas.json'))
            self.assertEqual(mapping['transform']['trim']['fw'], 16)
            self.assertEqual(mapping['transform']['trim']['fh'], 24)
        actions = {a['variant']: a for a in p['animations']}
        self.assertEqual(actions['normal']['clips'][0]['asset'], actions['special']['clips'][0]['asset'])
        self.assertEqual((actions['normal']['clips'][0]['x'], actions['normal']['clips'][0]['y']), (-6, -21))
        self.assertEqual(Image.open(io.BytesIO(self.store.asset_bytes(p, actions['normal']['clips'][0]['asset']))).size, (3, 2))
        target = ProjectStore(self.root / 'reference-roundtrip')
        restored = target.import_archive(self.store.export(p['id']))
        self.assertEqual(restored['sourceIntake'], intake)
        self.assertEqual(restored['animations'], p['animations'])
        self.assertEqual((target.directory(restored['id']) / package['blob']).read_bytes(), raw)

    def test_identical_normal_special_cells_keep_each_frame_source_reference(self):
        _, raw, prefix = reference_bundle()
        p = self.store.import_archive(raw)
        sources = {row['id']: row for row in p['sourceIntake']['sources']}
        for action in p['animations']:
            sheet = 'sprite_sheet' if action['variant'] == 'normal' else 'special_sprite_sheet'
            for clip in action['clips']:
                self.assertIn('sourceRef', clip)
                self.assertEqual(sources[clip['sourceRef']['source']]['path'], prefix + f'pixelart/{sheet}.png')
                self.assertEqual(sources[clip['sourceRef']['transform']['atlasSource']]['path'],
                                 prefix + f'pixelart/{sheet}.atlas.json')

    def test_reference_folder_import_without_package_does_not_invent_original_zip_hash(self):
        files, _, _ = reference_bundle()
        p = self.store.import_reference(files)
        package = p['sourceIntake']['packages'][0]
        self.assertEqual(package['status'], 'missing')
        self.assertIsNone(package['sha256'])
        self.assertIsNone(package['blob'])
        self.assertEqual(len(p['sourceIntake']['sources']), len(files))
        restored_store = ProjectStore(self.root / 'loose-reference-roundtrip')
        restored = restored_store.import_archive(self.store.export(p['id']))
        self.assertEqual(restored['sourceIntake'], p['sourceIntake'])

    def test_migration_rejects_tampered_original_or_forged_zip_member_and_preserves_trees(self):
        for changed in ('rawsource', 'package', 'memberpath'):
            with self.subTest(changed=changed):
                files, raw, _ = reference_bundle()
                p = self.store.import_archive(raw)
                directory = self.store.directory(p['id'])
                if changed == 'rawsource':
                    (directory / p['sourceIntake']['sources'][0]['blob']).write_bytes(b'changed original bytes')
                elif changed == 'package':
                    (directory / p['sourceIntake']['packages'][0]['blob']).write_bytes(b'changed package bytes')
                else:
                    p['sourceIntake']['sources'][0]['path'] = 'safe/path/not-in-original-zip.png'
                    # Simulate an older project carrying a false path declaration.
                    (directory / 'project.json').write_bytes(json_bytes(p))
                target = ProjectStore(self.root / ('migration-' + changed))
                before_source, before_target = tree_state(directory), tree_state(target.root)
                with self.assertRaises(ValueError):
                    project_storage.copy_project(target, directory, p)
                self.assertEqual(tree_state(directory), before_source)
                self.assertEqual(tree_state(target.root), before_target)

    def test_migration_reference_success_keeps_original_zip_and_unknown_extensions(self):
        _, raw, _ = reference_bundle()
        p = self.store.import_archive(raw)
        p['futureMigration'] = {'keep': 'original branch author annotation'}
        self.store._write(p)
        source_dir = self.store.directory(p['id'])
        before = tree_state(source_dir)
        target = ProjectStore(self.root / 'migration-success')
        result = project_storage.copy_project(target, source_dir, p)
        self.assertEqual(result['status'], 'copied')
        restored = target.load(result['id'])
        self.assertEqual(restored['sourceIntake'], p['sourceIntake'])
        self.assertEqual(restored['futureMigration'], p['futureMigration'])
        package = p['sourceIntake']['packages'][0]
        self.assertEqual((target.directory(restored['id']) / package['blob']).read_bytes(), raw)
        self.assertEqual(tree_state(source_dir), before)

    def test_legacy_auto_mask_resolves_by_slot_without_read_write_or_source_changes(self):
        raw = draft_png((256, 256))
        aid = self.store.add_asset(self.p, 'legacy-portrait.png', raw, 'portrait')
        self.p['portraits']['base'] = aid
        self.p['crops']['base:battle_member_status'] = {'x': .5, 'y': .5, 'zoom': 1}
        self.p['uiDeclarations'] = {'base:battle_member_status': {'mask': 'auto', 'autoCrop': True}}
        self.store._write(self.p)
        directory = self.store.directory(self.p['id'])
        before = tree_state(directory)
        loaded = self.store.load(self.p['id'])
        spec = portrait_editor.selection(loaded, 'base', 'battle_member_status')
        self.assertEqual(spec['mask'], 'auto')
        self.assertTrue(spec['legacy'])
        portrait_editor.validate_selection(loaded, spec)
        self.assertEqual(portrait_editor.resolve_mask('battle_member_status', spec), 'member_status')
        self.assertEqual(portrait_editor.resolve_mask('full_shot', {'mask': 'auto'}), 'none')
        rendered = Image.open(io.BytesIO(portrait_editor.render(self.store, loaded, 'base', 'battle_member_status')))
        self.assertEqual(rendered.size, UI_SLOTS['battle_member_status'][1:])
        alpha = rendered.getchannel('A')
        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertGreater(alpha.getpixel((rendered.width // 2, rendered.height // 2)), 0)
        self.assertEqual(tree_state(directory), before)
        self.assertEqual(self.store.asset_bytes(loaded, aid), png_bytes(Image.open(io.BytesIO(raw)).convert('RGBA')))


if __name__ == '__main__':
    unittest.main()
