import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import ProjectStore, StudioError, png_bytes


class MediaCatalogTests(unittest.TestCase):
    def test_batch_reuses_metadata_and_revisions_and_hashes_stay_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(Path(directory)/'projects')
            p=store.create('atlas')
            raw=png_bytes(Image.new('RGBA',(2,2),'red'))
            aid=store.add_asset(p,'red.png',raw,'pixel')
            store._write(p)
            with patch.object(store,'load',wraps=store.load) as load:
                for _ in range(40):
                    self.assertEqual(store.media_asset(p['id'],aid),(raw,'image/png'))
                self.assertEqual(load.call_count,1,'Image batch must not reparse the full animation project per image')
                blue=store.add_asset(p,'blue.png',png_bytes(Image.new('RGBA',(2,2),'blue')),'pixel')
                store._write(p)
                store.media_asset(p['id'],blue)
                self.assertEqual(load.call_count,2,'A new asset must invalidate the cached catalog')
            path=store.directory(p['id'])/'assets'/p['assets'][aid]['file']
            path.write_bytes(raw+b'changed')
            with self.assertRaises(StudioError):
                store.media_asset(p['id'],aid)


if __name__=='__main__':
    unittest.main()
