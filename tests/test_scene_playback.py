import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import ProjectStore, png_bytes
from studio_compile import compiled_scene_preview


class ScenePlaybackTests(unittest.TestCase):
    def test_native_modes_and_exclusive_lifetime_use_compiled_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory)/'projects')
            p = store.create('timing')
            clips = []
            for color in ('red', 'blue'):
                aid = store.add_asset(p, color+'.png', png_bytes(Image.new('RGBA',(2,2),color)), 'pixel')
                clips.append(dict(asset=aid,hold=1,x=0,y=0,rotation=0,scale=1,opacity=1,flip=False))
            p['animations'] = [dict(id='motion',name='motion',slot='neutral',variant='normal',kind='once',fps=60,frameScale=1,clips=clips)]
            p['scene'] = {'duration':8,'tracks':[dict(id='view',type='actor',ref='motion',start=1,end=5,playMode='once')]}
            store._write(p)
            once = compiled_scene_preview(store,p)['frames']
            self.assertFalse(once[0])
            self.assertNotEqual(once[1],once[2])
            self.assertEqual(once[2],once[4], 'Once must hold its last picture for the remaining lifetime')
            self.assertFalse(once[5], 'End is exclusive')
            p['scene']['tracks'][0]['playMode']='stop'
            stop=compiled_scene_preview(store,p)['frames']
            self.assertEqual(stop[1],stop[4], 'Stop pauses on the first picture')
            self.assertEqual(stop[1],once[1])
            p['scene']['tracks'][0]['playMode']='loop'
            loop=compiled_scene_preview(store,p)['frames']
            self.assertEqual(loop[1],loop[3])
            self.assertEqual(loop[2],loop[4])
            p['scene']['tracks'][0]['playMode']='pass'
            passed=compiled_scene_preview(store,p)['frames']
            self.assertFalse(passed[3], 'Pass is joined to its successor by the planner, not held here')


if __name__=='__main__':
    unittest.main()
