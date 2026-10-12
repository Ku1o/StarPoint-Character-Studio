"""Native frame fallback and actual PNG/atlas identities, without byte changes."""
import copy
import io
import json
import sys
import unittest
import tempfile
import hashlib
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from character_dependencies import analyze, analyze_project, resource_catalog
from atlas_optimizer import _amf_bytes
from test_character_dependencies import record, root, fixture


def frame_files():
    base='character/fixture/pixelart/pixelart'
    sheet='character/fixture/pixelart/sprite_sheet'
    image=io.BytesIO(); Image.new('RGBA',(8,8)).save(image,'PNG')
    return base, sheet, {
        base+'.frame.json':json.dumps({'name':base,'x':-128,'y':-128,'scale':6,'smoothing':False}).encode(),
        base+'.timeline.json':b'{"sounds":[]}',
        sheet+'.atlas.json':json.dumps([{'n':base+'0002','x':0,'y':0,'w':4,'h':4},
                                       {'n':base+'0004','x':4,'y':0,'w':4,'h':4}]).encode(),
        sheet+'.png':image.getvalue()}


class NativeResourceFormatTests(unittest.TestCase):
    def test_readable_dsl_cannot_replace_actual_program_hash_or_hide_conflict(self):
        tree=['Block', [['Command', ['Trace', 'retained']]]]
        logical='battle/action/skill/fixture'
        encoded=logical+'.action.dsl.amf3.deflate'
        raw=_amf_bytes(tree)
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            class Store:
                def directory(self, pid):return base
            files={encoded:raw,'data_readable/skill_dependencies.json':json.dumps({'programs':[{'logical':logical,'tree':tree}]}).encode()}
            for name,data in files.items():
                path=base/'reference'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            p={'id':'p','revision':0,'referenceFiles':list(files)}
            report=analyze_project(Store(),p)
            programs=[d for d in report['dependencies'] if d['kind']=='dsl']
            self.assertTrue(programs)
            self.assertTrue(all(d['sha256']==hashlib.sha256(raw).hexdigest() for d in programs))
            (base/'reference/data_readable/skill_dependencies.json').write_bytes(json.dumps({'programs':[{'logical':logical,'tree':['Block',[]]}]}).encode())
            report=analyze_project(Store(),p)
            self.assertFalse(report['closure']['compiledResourceClosure'])
            self.assertTrue(any('身份树冲突' in item['reason'] for item in report['unsupported']))
            self.assertEqual((base/'reference'/encoded).read_bytes(),raw)

    def test_frame_uses_exact_sheet_and_all_prefix_frames_without_mutating_bytes(self):
        base,sheet,files=frame_files(); before=copy.deepcopy(files)
        report=analyze([root(base)],resource_catalog(files))
        self.assertTrue(report['closure']['compiledResourceClosure'])
        self.assertEqual(report['missingReferences'],[])
        self.assertEqual({d['logical'] for d in report['dependencies'] if d['kind']=='atlas-cell'}, {base+'0002',base+'0004'})
        self.assertEqual(files,before)
        self.assertFalse(report['gameReady'])

    def test_special_frame_maps_to_special_sheet(self):
        base,sheet,files=frame_files()
        rename=lambda s:s.replace('/pixelart/pixelart','/pixelart/special').replace('/sprite_sheet','/special_sprite_sheet')
        files={rename(name):raw.replace(base.encode(),rename(base).encode()) if name.endswith('.json') else raw for name,raw in files.items()}
        report=analyze([root(rename(base))],resource_catalog(files))
        self.assertTrue(report['closure']['compiledResourceClosure'])
        self.assertIn(rename(sheet)+'.png',[d['logical'] for d in report['dependencies']])

    def test_parts_are_preferred_and_bad_present_parts_do_not_fall_back(self):
        base,sheet,files=frame_files(); catalog=resource_catalog(files)
        catalog[base+'.parts.amf3.deflate']=record('parts',{'i':[],'g':[]})
        report=analyze([root(base)],catalog)
        self.assertFalse(report['closure']['compiledResourceClosure'])
        self.assertTrue(report['unsupported'])
        self.assertNotIn(base+'.frame.json',[d['logical'] for d in report['dependencies']])

    def test_missing_prefix_or_sheet_is_real_missing_and_malformed_frame_is_open(self):
        base,sheet,files=frame_files()
        files[sheet+'.atlas.json']=b'[]'
        report=analyze([root(base)],resource_catalog(files))
        self.assertFalse(report['closure']['compiledResourceClosure'])
        self.assertIn(base,[m['logical'] for m in report['missingReferences']])
        del files[sheet+'.atlas.json']
        report=analyze([root(base)],resource_catalog(files))
        self.assertTrue(report['missingReferences'])
        files[base+'.frame.json']=b'{"name":"character/fixture/pixelart/pixelart"}'
        report=analyze([root(base)],resource_catalog(files))
        self.assertTrue(report['unsupported'])

    def test_native_ui_png_alias_keeps_byte_identity_and_invalid_image_open(self):
        _,_,files=frame_files(); raw=next(raw for name,raw in files.items() if name.endswith('.png'))
        name='character/fixture/ui/square_0'
        catalog=resource_catalog({name+'.png':raw})
        report=analyze([root(name)],catalog)
        self.assertTrue(report['closure']['compiledResourceClosure'])
        self.assertEqual(report['dependencies'][0]['sha256'],catalog[name+'.png']['sha256'])
        self.assertEqual(report['dependencies'][0]['file'],name+'.png')
        report=analyze([root(name)],resource_catalog({name+'.png':b'invalid'}))
        self.assertFalse(report['closure']['compiledResourceClosure'])

    def test_parts_s_true_uses_declared_atlas_instead_of_guessing_direct_png(self):
        catalog=fixture(); catalog['parts']['data']['i'][0]['s']=True
        report=analyze([root()],catalog)
        self.assertTrue(report['closure']['compiledResourceClosure'])
        self.assertEqual(report['missingReferences'],[])
        self.assertFalse(any(edge['to'].endswith('/.gen/0.png') for edge in report['edges']))


if __name__=='__main__': unittest.main()
