"""Existing ability selection: the live MOD reader or the separate offline pack."""
from __future__ import annotations
import copy
import threading
import native_gameplay as native

KINDS=('ability','leader_ability')

class AbilityLibrary:
    def __init__(self,definitions,provider=None):
        self.definitions=definitions;self.provider=provider;self.cached_pack=None;self.entries=[];self.lock=threading.RLock()

    def _index(self):
        pack=self.definitions.load()
        if not pack:raise ValueError('请先解压完整角色资源包，或导入旧版角色定义包')
        with self.lock:
            if self.cached_pack is pack:return self.entries
            entries=[]
            for cid,c in pack['characters'].items():
                cr=c['records']['character']['selected'][cid]['rows'][0]
                for kind,keys,label in [('leader_ability',[cr[17]],'leader_ability'),('ability',cr[19:25],'abilities')]:
                    for slot,key in enumerate(keys,1):
                        rows=c['records'][label]['selected'].get(key,{}).get('rows',[])
                        if not rows:continue
                        entries.append({'key':f'{cid}:{kind}:{slot}','kind':kind,'owner':c['name'],'character':cid,'code':c['code'],
                            'slot':slot if kind=='ability' else 'leader','sourceKey':key,'rows':copy.deepcopy(rows),
                            'description':' ┃ '.join(native.describe.describe_rows(rows,kind))})
            self.cached_pack=pack;self.entries=entries
            return entries

    def query(self,kind,query='',offset=0,key=None):
        if kind not in KINDS:raise ValueError('请选择角色能力或队长技')
        if not isinstance(query,str) or len(query)>200:raise ValueError('搜索文字过长')
        if isinstance(offset,bool) or not isinstance(offset,int) or not 0<=offset<=100000:raise ValueError('分页位置无效')
        if self.provider:
            result=copy.deepcopy(self.provider(kind,query,offset,key))
        else:
            values=self._index()
            if key is not None:
                entry=next((e for e in values if e['key']==key and e['kind']==kind),None)
                if not entry:raise ValueError('词条不存在，请重新选择')
                result={'source':'官方离线词条库','entry':copy.deepcopy(entry)}
            else:
                words=query.strip().casefold().split()
                found=[e for e in values if e['kind']==kind and all(word in (e['owner']+' '+e['character']+' '+e['code']+' '+e['sourceKey']+' '+e['description']).casefold() for word in words)]
                result={'source':'官方离线词条库','total':len(found),'offset':offset,'entries':[{k:copy.deepcopy(v) for k,v in e.items() if k!='rows'}|{'lines':len(e['rows'])} for e in found[offset:offset+40]]}
        if key is not None:
            entry=result['entry']
            if entry['kind']!=kind:raise ValueError('词条类型与当前槽位不一致')
            if not isinstance(entry.get('rows'),list) or not 1<=len(entry['rows'])<=128:raise ValueError('来源词条行数无效')
            entry['fingerprint']=native.digest({'kind':kind,'key':key,'rows':entry['rows']})
            issues=[];row_issues=[]
            for row in entry['rows']:
                try:native._validate_row(row,kind);row_issues.append([])
                except ValueError as error:issues.append(str(error));row_issues.append([str(error)])
            entry['issues']=list(dict.fromkeys(issues))
            entry['rowIssues']=row_issues
            entry['rowDescriptions']=[native.describe.describe_line(row,kind) for row in entry['rows']]
        return result

    def append(self,store,pid,revision,slot,key,fingerprint,indices=None):
        p=store.load(pid)
        if p['revision']!=revision:raise ValueError('工程已更新，请重新打开')
        data=p.get('nativeGameplay');native.validate_native(data)
        if not data:raise ValueError('请先载入参考角色定义，再选择能力词条')
        group,kind=native.group_for(data,slot)
        result=self.query(kind,key=key);entry=result['entry']
        if entry['fingerprint']!=fingerprint:raise ValueError('来源词条已更新，请重新预览后选用')
        if indices is None:indices=list(range(len(entry['rows'])))
        if not isinstance(indices,list) or not indices or any(isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(entry['rows']) for i in indices) or len(set(indices))!=len(indices):raise ValueError('请选择有效的效果条目')
        rows=[entry['rows'][i] for i in sorted(indices)]
        for row in rows:native._validate_row(row,kind)
        group['rows'].extend(copy.deepcopy(rows))
        # Preserve provenance independently of the immutable starting character.
        data.setdefault('borrowedAbilities',[]).append({'source':result['source'],'kind':kind,'targetSlot':slot,'key':key,
            'owner':entry['owner'],'fingerprint':fingerprint,'rows':copy.deepcopy(rows),'indices':sorted(indices)})
        native.validate_native(data)
        return store.save(p)
