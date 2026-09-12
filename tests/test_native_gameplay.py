import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_gameplay as n
from studio_core import ProjectStore
from character_contract import export_contract

def row(kind):
    layout=n.describe.layout(kind);b=layout['blocks'];r=['0']*layout['ncols']
    r[0]='fixture';r[b['precondition1']-1]='0';r[b['instant_precontent']]='(None)';r[b['during_accumulation_trigger']]='(None)';r[b['even_if_owner_dead']]='false'
    if kind=='ability':r[1]='true';r[2]='attack_common';r[4]=''
    r[b['instant_content']]='32';r[b['instant_content']+4]='10000';r[b['instant_content']+5]='20000'
    r[b['instant_content']+25]='false'
    return r

def pack():
    c=['']*37;c[0]=c[8]='fixture';c[17]='3';c[19:25]=[str(i) for i in range(81,87)]
    def selection(key,value):return {'selected':{key:{'rows':value}}}
    records={'character':selection('10',[c]),'character_text':selection('10',[['测试']]),
        'leader_ability':selection('3',[row('leader_ability')]),'abilities':{'selected':{key:{'rows':[row('ability')]} for key in c[19:25]}},
        'action_skill':{'outer_key':'fixture','rows':[{'inner_key':'1','fields':['测试技能','说明','','false','500','400','','fixture_1']}]}}
    return {'schema':n.PACK_SCHEMA,'version':'1.4.54','characters':{'10':{'id':'10','name':'测试','code':'fixture','records':records}},'blankRows':{k:row(k) for k in ('ability','leader_ability')}}

class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=ProjectStore(Path(self.tmp.name)/'projects');self.p=self.store.create('测试')
        self.pack=pack()
        class Library:
            def load(inner):return self.pack
        self.library=Library()
        self.p=n.attach(self.store,self.p['id'],self.p['revision'],self.library,'10')

    def test_actual_reference_keys_and_source_roundtrip(self):
        contract=export_contract(self.store,self.p)
        self.assertEqual(contract['sourceDefinition']['leader']['sourceKey'],'3')
        self.assertEqual(contract['sourceDefinition']['abilities'][0]['sourceKey'],'81')
        self.assertFalse(contract['sourceDefinition']['needsDefinitionPack'])
        restored=self.store.import_archive(self.store.export(self.p['id']))
        self.assertEqual(self.p['nativeGameplay'],restored['nativeGameplay'])

    def test_value_edit_preserves_unknown_columns_and_source(self):
        before=copy.deepcopy(self.p['nativeGameplay']);before['abilities'][0]['rows'][0]+=['future-extension']
        self.p['nativeGameplay']=before;self.p=self.store.save(self.p)
        old=copy.deepcopy(before['abilities'][0]['rows'][0]);b=n.describe.layout('ability')['blocks']['instant_content']
        edited=n.edit(self.store,self.p['id'],self.p['revision'],'patch',1,0,{'value':12.5,'valueMax':33,'mainOnly':True})['nativeGameplay']
        expect=old[:];expect[b+4]='12500';expect[b+5]='33000';expect[1]='false'
        self.assertEqual(edited['abilities'][0]['rows'][0],expect)
        self.assertEqual(edited['source'],before['source'])

    def test_generated_units_duration_and_main(self):
        p=n.edit(self.store,self.p['id'],self.p['revision'],'add',2,spec={'trigger_id':'skill','effect_id':'atk','value':15,'value_max':30,'duration':2,'mainOnly':True})
        r=p['nativeGameplay']['abilities'][1]['rows'][-1]
        self.assertEqual(r[27],'23');self.assertEqual(r[30],'100000');self.assertEqual(r[51:53],['15000','30000']);self.assertEqual(r[57:59],['12000000','12000000']);self.assertEqual(r[1],'false')

    def test_source_hash_and_stale_revision_rejected(self):
        bad=copy.deepcopy(self.p['nativeGameplay']);bad['source']['data']['version']='wrong'
        with self.assertRaises(ValueError):n.validate_native(bad)
        with self.assertRaises(ValueError):n.edit(self.store,self.p['id'],0,'delete',1,0,{})
        self.assertEqual(self.store.load(self.p['id']),self.p)

    def test_mode_mismatch_and_nonfinite_rejected_without_save(self):
        with self.assertRaises(ValueError):n.edit(self.store,self.p['id'],self.p['revision'],'add',1,spec={'trigger_id':'hp_high','effect_id':'atk','value':3})
        with self.assertRaises(ValueError):n.edit(self.store,self.p['id'],self.p['revision'],'patch',1,0,{'value':'NaN'})
        self.assertEqual(self.store.load(self.p['id']),self.p)

    def test_original_anomalous_row_preserved_but_edits_checked(self):
        abnormal=self.pack['characters']['10']['records']['abilities']['selected']['81']['rows'][0]
        abnormal[6]=''
        fresh=self.store.create('原始异常');p=n.attach(self.store,fresh['id'],0,self.library,'10')
        self.assertTrue(n.describe_native(p['nativeGameplay'])['groups'][1]['rows'][0]['issues'])
        with self.assertRaises(ValueError):n.edit(self.store,p['id'],p['revision'],'patch',1,0,{'value':30})

    def test_compiled_skill_multiline_and_quoted_text_roundtrip(self):
        text='第一行，含逗号, 与 "引号"\n第二行'
        p=n.edit(self.store,self.p['id'],self.p['revision'],'skill',index=0,spec={'description':text,'energy':520})
        native=p['nativeGameplay'];files,receipt=n.compile_native(native)
        outer=n.core.read_orderedmap_raw_rows_from_bytes(files['native-draft/action_skill.orderedmap'])
        rows=n.core.decode_action_skill_row(outer.rows[0])
        self.assertEqual(rows[0][1][1],text);self.assertEqual(rows[0][1][4],'520')
        self.assertTrue(receipt['readback']);self.assertFalse(receipt['gameReady'])
        decoded=n.core.read_orderedmap_bytes(files['native-draft/ability.orderedmap'],'<test>')
        self.assertEqual(n.core.read_csv_lines(decoded.rows[0].decode()),native['abilities'][0]['rows'])
        self.assertEqual(native['source'],self.p['nativeGameplay']['source'])

    def test_invalid_edit_parameters_do_not_change_project(self):
        base={'trigger_id':'skill','effect_id':'atk','value':3}
        for patch in ({'value':'Infinity'},{'value':True},{'value':1e9},{'value':.00001},
                      {'mainOnly':'false'},{'duration':-2},{'target':'100'},
                      {'groups':'NoSuchGroup'},{'effect_id':'invoke'},{'precondition_kind':'99999'}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                n.edit(self.store,self.p['id'],self.p['revision'],'add',1,spec={**base,**patch})
            self.assertEqual(self.store.load(self.p['id']),self.p)

    def test_definition_install_verifies_hash_before_writing(self):
        library=n.DefinitionLibrary(Path(self.tmp.name)/'definitions');raw=n.canonical(self.pack)
        files={'definitions/characters.json':raw,'definitions/manifest.json':n.canonical({'sha256':'incorrect'})}
        with self.assertRaises(ValueError):library.install(files)
        self.assertFalse(library.root.exists())
        files['definitions/manifest.json']=n.canonical({'sha256':n.hashlib.sha256(raw).hexdigest()})
        self.assertTrue(library.install(files)['installed'])
        self.assertEqual(library.load(),self.pack)

if __name__=='__main__':unittest.main()
