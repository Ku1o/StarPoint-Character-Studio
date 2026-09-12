import copy
import unittest
import test_native_gameplay as fixture
import ability_editor as editor
from ability_library import AbilityLibrary
n=fixture.n

class AbilityEditorTests(unittest.TestCase):
    setUp=fixture.NativeTests.setUp

    def test_new_free_row_combines_condition_trigger_and_effect_and_roundtrips(self):
        draft=editor.draft(self.store,self.p['id'],3);row=draft['row'];b=n.describe.layout('ability')['blocks']
        row[b['instant_trigger']]='23';row[b['instant_content']]='34';row[b['instant_content']+4]='45000';row[b['instant_content']+5]='90000'
        row[b['precondition1']]='4';row[1]='false'
        self.assertTrue(editor.preview('ability',row)['valid'])
        p=editor.apply(self.store,self.p['id'],self.p['revision'],3,None,row)
        self.assertEqual(p['nativeGameplay']['abilities'][2]['rows'][-1],row)
        self.assertEqual(p['nativeGameplay']['source'],self.p['nativeGameplay']['source'])
        files,report=n.compile_native(p['nativeGameplay']);self.assertTrue(report['readback'])
        self.assertEqual(self.store.import_archive(self.store.export(p['id']))['nativeGameplay'],p['nativeGameplay'])

    def test_edit_preserves_extension_and_copy_move_single_row(self):
        row=editor.draft(self.store,self.p['id'],1,0)['row']+['future-column'];row[51]='77000'
        p=editor.apply(self.store,self.p['id'],self.p['revision'],1,0,row)
        p=editor.transfer(self.store,p['id'],p['revision'],1,0,2,0,True)
        self.assertEqual(p['nativeGameplay']['abilities'][0]['rows'][0],row)
        self.assertEqual(p['nativeGameplay']['abilities'][1]['rows'][0],row)
        p=editor.transfer(self.store,p['id'],p['revision'],2,0,3,1)
        self.assertEqual(len(p['nativeGameplay']['abilities'][1]['rows']),1)
        self.assertEqual(p['nativeGameplay']['abilities'][2]['rows'][1],row)

    def test_stale_invalid_and_cross_kind_transfer_do_not_save(self):
        row=editor.draft(self.store,self.p['id'],1,0)['row'];row[47]='99999'
        self.assertFalse(editor.preview('ability',row)['valid'])
        for call in [lambda:editor.apply(self.store,self.p['id'],self.p['revision'],1,0,row),lambda:editor.apply(self.store,self.p['id'],0,1,0,fixture.row('ability')),lambda:editor.transfer(self.store,self.p['id'],self.p['revision'],1,0,'leader',0)]:
            with self.assertRaises(ValueError):call()
            self.assertEqual(self.store.load(self.p['id']),self.p)

    def test_library_selects_one_valid_row_despite_another_invalid_row(self):
        rows=self.pack['characters']['10']['records']['abilities']['selected']['81']['rows'];rows.append(copy.deepcopy(rows[0]));rows[1][6]=''
        library=AbilityLibrary(self.library);entry=library.query('ability',key='10:ability:1')['entry']
        self.assertEqual(len(entry['rowDescriptions']),2);self.assertFalse(entry['rowIssues'][0]);self.assertTrue(entry['rowIssues'][1])
        p=library.append(self.store,self.p['id'],self.p['revision'],2,entry['key'],entry['fingerprint'],[0])
        self.assertEqual(len(p['nativeGameplay']['abilities'][1]['rows']),2)
        self.assertEqual(p['nativeGameplay']['borrowedAbilities'][-1]['indices'],[0])

if __name__=='__main__':unittest.main()
