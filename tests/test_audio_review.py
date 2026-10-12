import io
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_review import measure, profile, create_candidate, project_report
from studio_core import ProjectStore


def tone(channels, amplitude=.06):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((channels, 2, 44100, 0, 'NONE', 'not compressed'))
        audio.writeframes(b''.join(struct.pack('<h', round(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / 44100))) * channels for i in range(44100 * 3)))
    return output.getvalue()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe unavailable; no audio acceptance claim')
class AudioReviewTests(unittest.TestCase):
    def test_identical_stereo_folds_to_matched_mono_without_hidden_gain(self):
        mono, stereo = measure(tone(1)), measure(tone(2))
        self.assertAlmostEqual(mono['integratedLufs'], stereo['integratedLufs'], delta=.1)
        self.assertEqual(stereo['foldMethod'], 'L/2+R/2')
        self.assertEqual(stereo['sourceChannels'], 2)
        self.assertTrue(stereo['fullDecode'])
        self.assertEqual(stereo['clippedSamples'], 0)
        self.assertAlmostEqual(stereo['decodedSeconds'], 3, places=5)
        native_stereo = measure(tone(2), mono=False)
        self.assertGreater(native_stereo['integratedLufs'] - stereo['integratedLufs'], 2.8)

    def test_silence_has_unknown_loudness_not_zero_or_pass(self):
        result = measure(tone(1, 0))
        self.assertIsNone(result['integratedLufs'])
        self.assertTrue(result['silentOrTooShort'])

    def test_default_recipe_does_not_apply_other_character_target(self):
        self.assertIsNone(profile({})['targetLufs'])
        self.assertIsNone(profile({})['truePeakCeilingDbtp'])
        with tempfile.TemporaryDirectory() as root:
            store = ProjectStore(Path(root) / 'projects'); p = store.create('quiet draft')
            aid = store.add_asset(p, 'raw.wav', tone(2), 'voice'); store._write(p)
            before = (store.directory(p['id']) / 'project.json').read_bytes()
            with self.assertRaises(ValueError):
                create_candidate(store, p['id'], p['revision'], aid)
            self.assertEqual((store.directory(p['id']) / 'project.json').read_bytes(), before)

    def test_candidate_full_decoded_profile_and_original_relation(self):
        with tempfile.TemporaryDirectory() as root:
            store = ProjectStore(Path(root) / 'projects'); p = store.create('quiet voice')
            raw = tone(2, .015); aid = store.add_asset(p, 'source/original.wav', raw, 'voice')
            p['audioProfile'] = {'voice': {'targetLufs': -20, 'toleranceLu': 2, 'truePeakCeilingDbtp': -1}}
            store._write(p)
            result = create_candidate(store, p['id'], p['revision'], aid)
            p = result['project']; cid = result['candidate']['candidateAsset']
            p['voices'] = [{'id': 'voice', 'name': 'voice', 'asset': cid, 'candidateOf': aid, 'usage': 'join', 'entry': 'ally', 'text': 'complete sentence'}]
            report = project_report(store, p)['rows'][0]
            self.assertEqual(report['status'], 'profile_pass')
            self.assertTrue(report['postEncodeDecode']['fullDecode'])
            self.assertTrue(report['packagingRoundtrip'])
            self.assertLessEqual(abs(report['durationDeltaSeconds']), .08)
            self.assertEqual(store.asset_bytes(p, aid), raw)
            source = next(row for row in p['sourceIntake']['derivatives'] if row['asset'] == cid)
            self.assertEqual(source['transform']['inputAsset'], aid)
            self.assertFalse(report['runtimeAccepted'])
            self.assertEqual(report['pathStatus'], 'needs_native_registration')


if __name__ == '__main__':
    unittest.main()
