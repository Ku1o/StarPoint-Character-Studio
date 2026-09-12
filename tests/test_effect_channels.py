import base64
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import zlib
import test_studio as fixture
from effect_channels import make_channels,compose_frames,edited,prepare,validate_channels
from studio_core import native_commands,make_zip,StudioError
from studio_compile import compile_effect,compiled_preview
from bridge import AMF3Reader,flatomo

class ChannelTests(unittest.TestCase):
    setUp=fixture.StudioTests.setUp
    tearDown=fixture.StudioTests.tearDown

    def imported(self):
        files,_=compile_effect(self.store,self.p,self.anim,'fixture')
        decoded={k:(AMF3Reader(zlib.decompress(v,-15)).read_value() if k.endswith('deflate') else v) for k,v in files.items()}
        parts=next(v for k,v in decoded.items() if k.endswith('.parts.amf3.deflate'))
        # Reuse the same texture in an independently placed second instance.
        parts['g'][0]['s'].append(copy.deepcopy(parts['g'][0]['s'][0]))
        parts['g'][0]['s'][1]['s']=3
        parts['g'][0]['s'][1]['l'][0]['t']=6
        prefix='reference/effect/fixture/'
        out={'reference/data_readable/identity.json':b'{"name":"fixture","code_name":"fixture"}'}
        for suffix,name in [('.png','fixture.png'),('.atlas.amf3.deflate','fixture.atlas.json'),('.parts.amf3.deflate','decoded/effect.parts.json'),('.timeline.amf3.deflate','decoded/effect.timeline.json')]:
            value=next(v for k,v in decoded.items() if k.endswith(suffix));out[prefix+name]=value if isinstance(value,bytes) else json.dumps(value).encode()
        return self.store.import_archive(make_zip(out))

    def test_instances_are_independent_and_untouched_matches_original(self):
        p=self.imported();e=p['effects'][0];self.assertEqual(len(e['channels']),2)
        self.assertEqual(len({c['sourceAsset'] for c in e['channels']}),1)
        self.assertEqual(compose_frames(e),e['nativeFrames']);self.assertFalse(edited(e))
        e['channels'][1]['x']=25
        self.assertTrue(edited(e));out=compose_frames(e)
        self.assertEqual(out[3][0],e['nativeFrames'][3][0])
        self.assertEqual(out[3][1]['matrix'][4],e['nativeFrames'][3][1]['matrix'][4]+25)

    def test_keys_retime_copy_hidden_and_compiled_readback(self):
        p=self.imported();e=p['effects'][0];first,second=e['channels']
        first.update(start=2,end=8,keys=[{'frame':2,'x':0,'rotation':0,'scale':1,'opacity':1},{'frame':7,'x':30,'rotation':90,'scale':2,'opacity':.5}])
        second['visible']=False
        duplicate=copy.deepcopy(first);duplicate.update(id='duplicate',sourceChannel=first['id'],y=10,keys=[]);e['channels'].append(duplicate)
        self.store.save(p);expected=compose_frames(e);read=compiled_preview(self.store,p['id'],'effects',e['id'])
        self.assertEqual(len(expected),len(read['frames']))
        for source,actual in zip(expected,read['frames']):
            self.assertEqual(len(source),len(actual))
            for a,b in zip(source,actual):
                for wanted,got in zip(a['matrix'],b['matrix']):self.assertAlmostEqual(wanted,got,delta=1/4096)
                self.assertAlmostEqual(a['alpha'],b['alpha'],delta=1/255)
                for key in ('fx','fy','blend'):self.assertEqual(a[key],b[key])
        self.assertEqual(expected[:2],[[],[]]);self.assertEqual(expected[-1],[])

    def test_migrate_old_project_keeps_layer_edits_and_sounds(self):
        p=self.imported();e=p['effects'][0];before=copy.deepcopy(e)
        e.pop('channels');e.pop('channelDuration')
        for frame in e['nativeFrames']:
            for cmd in frame:cmd.pop('channel');cmd.pop('channelOrder')
        next(iter(e['layers'].values()))['x']=17
        p=self.store.save(p);migrated=prepare(self.store,p['id'],p['revision'],e['id']);after=migrated['effects'][0]
        self.assertEqual(after['channels'],before['channels']);self.assertEqual(next(iter(after['layers'].values()))['x'],17)
        self.assertEqual(after['soundEvents'],before['soundEvents'])

    def test_invalid_ranges_and_sources_rejected(self):
        p=self.imported();effect=p['effects'][0]
        for patch in ({'start':9},{'sourceEnd':40},{'asset':'missing'},{'scale':float('nan')},{'id':'missing'},{'keys':[{'frame':5},{'frame':4}]}):
            e=copy.deepcopy(effect);e['channels'][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises((StudioError,ValueError)):validate_channels(e,p['assets'])

    def test_js_composition_matches_python(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable')
        e=self.imported()['effects'][0];e['channels'][1].update(x=3,rotation=36,scale=1.3,keys=[{'frame':3,'opacity':1},{'frame':8,'opacity':.3,'x':12}])
        script=Path(__file__).resolve().parents[1]/'web/effect-channels.js'
        result=subprocess.run([node,'-e','const f=require(process.argv[1]);let s="";process.stdin.on("data",v=>s+=v);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(f.compose(JSON.parse(s)))));',str(script)],input=json.dumps(e),text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout),compose_frames(e))

if __name__=='__main__':unittest.main()
