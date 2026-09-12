import ast
import copy
from pathlib import Path
import unittest
import test_native_gameplay as fixture
n=fixture.n
from ability_library import AbilityLibrary


class AbilityLibraryTests(unittest.TestCase):
    setUp=fixture.NativeTests.setUp

    def test_offline_search_copy_all_rows_and_export(self):
        rows=self.pack['characters']['10']['records']['abilities']['selected']['81']['rows']
        rows[0]+=['future-field'];rows.append(copy.deepcopy(rows[0]))
        catalog=AbilityLibrary(self.library)
        found=catalog.query('ability','测试 81');self.assertEqual(found['total'],1)
        entry=catalog.query('ability',key=found['entries'][0]['key'])['entry'];self.assertFalse(entry['issues'])
        before=copy.deepcopy(self.pack)
        p=catalog.append(self.store,self.p['id'],self.p['revision'],2,entry['key'],entry['fingerprint'])
        self.assertEqual(p['nativeGameplay']['abilities'][1]['rows'][1:],rows)
        self.assertEqual(p['nativeGameplay']['source'],self.p['nativeGameplay']['source'])
        self.assertEqual(self.pack,before)
        self.assertEqual(self.store.import_archive(self.store.export(p['id']))['nativeGameplay'],p['nativeGameplay'])
        files,receipt=n.compile_native(p['nativeGameplay']);self.assertTrue(receipt['readback'])
        self.assertFalse(receipt['gameReady'])

    def test_changed_source_or_stale_revision_does_not_save(self):
        catalog=AbilityLibrary(self.library);e=catalog.query('ability',key='10:ability:1')['entry']
        for revision,fingerprint in [(0,e['fingerprint']),(self.p['revision'],'wrong')]:
            with self.assertRaises(ValueError):catalog.append(self.store,self.p['id'],revision,1,e['key'],fingerprint)
            self.assertEqual(self.store.load(self.p['id']),self.p)

    def test_wrong_kind_and_original_anomaly_rejected(self):
        catalog=AbilityLibrary(self.library);e=catalog.query('leader_ability',key='10:leader_ability:1')['entry']
        with self.assertRaises(ValueError):catalog.append(self.store,self.p['id'],self.p['revision'],1,e['key'],e['fingerprint'])
        self.pack=copy.deepcopy(self.pack)
        self.pack['characters']['10']['records']['abilities']['selected']['81']['rows'][0][6]=''
        e=catalog.query('ability',key='10:ability:1')['entry'];self.assertTrue(e['issues'])
        with self.assertRaises(ValueError):catalog.append(self.store,self.p['id'],self.p['revision'],1,e['key'],e['fingerprint'])
        self.assertEqual(self.store.load(self.p['id']),self.p)

    def test_pagination_and_search_validation(self):
        catalog=AbilityLibrary(self.library)
        self.assertEqual(catalog.query('ability',offset=40)['entries'],[])
        for kind,q,offset in [('weapon','',0),('ability','a'*201,0),('ability','',-1)]:
            with self.assertRaises(ValueError):catalog.query(kind,q,offset)

    def test_live_provider_overrides_offline_and_rechecks_rows(self):
        row=copy.deepcopy(self.p['nativeGameplay']['abilities'][0]['rows'][0])
        def provider(kind,q,offset,key):
            return {'source':'当前 MOD 词条库','entry':{'key':key,'kind':kind,'owner':'本地角色','rows':[row]}}
        catalog=AbilityLibrary(self.library,provider)
        e=catalog.query('ability',key='current')['entry'];row[51]='99900'
        with self.assertRaises(ValueError):catalog.append(self.store,self.p['id'],self.p['revision'],1,'current',e['fingerprint'])
        self.assertEqual(self.store.load(self.p['id']),self.p)

    def test_actual_mod_provider_uses_library_and_row_reader(self):
        path=Path(__file__).resolve().parents[2]/'fantasy-gauntlet-mod-tools/wf_gui.py'
        if not path.exists():self.skipTest('原 MOD 宿主不在独立源码分发中')
        node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='studio_ability_library')
        entries=[{'key':'81','kind':'ability','owner':'MOD 自定义角色','slot':2,'desc':'攻击力上升','sid':'custom','lines':2},
                 {'key':'L:3','kind':'leader_ability','owner':'队长','slot':0,'desc':'全体攻击力','sid':'leader','lines':1}]
        calls=[]
        def read(key,line):calls.append((key,line));return {'row':['custom',str(line)]}
        scope={'_build_search_index':lambda:(entries,{}),'composer_row':read}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
        provider=scope['studio_ability_library'];found=provider('ability','自定义 攻击力')
        self.assertEqual(found['total'],1);self.assertEqual(found['source'],'当前 MOD 词条库')
        self.assertEqual(provider('ability',key='81')['entry']['rows'],[['custom','1'],['custom','2']])
        self.assertEqual(calls,[('81',1),('81',2)])
        with self.assertRaises(ValueError):provider('ability',key='L:3')

if __name__=='__main__':unittest.main()
