"""Shared MOD rows inside a portable authoring project; no live data writes."""
from __future__ import annotations
import copy
import hashlib
import json
import csv
import io
from decimal import Decimal, InvalidOperation
from pathlib import Path
import threading

import bridge  # resolves the bundled or repository MOD core
import wf_ability_composer as composer
import wf_describe as describe
from wf_client_legality import client_legality_problems
import wf_mod_tool as core

SCHEMA = 'starpoint-native-gameplay-v1'
PACK_SCHEMA = 'starpoint-character-definitions-v1'
LIMIT = 48 * 1024 * 1024

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def csv_text(rows):
    stream=io.StringIO(newline='')
    csv.writer(stream,lineterminator='\n').writerows(rows)
    return stream.getvalue().removesuffix('\n')

class DefinitionLibrary:
    def __init__(self, root):
        self.root=Path(root).resolve(); self.lock=threading.RLock();self.cache=None;self.stamp=None

    def load(self):
        with self.lock:
            path=self.root/'manifest.json'
            if not path.is_file(): return None
            if path.stat().st_size>65536: raise ValueError('角色定义索引过大')
            meta=json.loads(path.read_bytes());name=meta.get('file','characters.json')
            if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or ':' in name:
                raise ValueError('角色定义索引路径无效')
            target=(self.root/name).resolve()
            if not target.is_relative_to(self.root) or target.stat().st_size>LIMIT: raise ValueError('角色定义文件无效或过大')
            stamp=(meta.get('sha256'),target.stat().st_mtime_ns,target.stat().st_size)
            if self.cache is not None and stamp==self.stamp:return self.cache
            raw=target.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=meta.get('sha256'): raise ValueError('角色定义包校验不一致，请重新解压')
            p=json.loads(raw);validate_pack(p)
            self.cache,self.stamp=p,stamp
            return p

    def catalog(self):
        pack=self.load()
        return {'installed':bool(pack),'version':pack['version'] if pack else '',
                'entries':[{'id':c['id'],'name':c['name'],'code':c['code']} for c in pack['characters'].values()] if pack else []}

    def install(self, files):
        raw=files.get('definitions/characters.json');index=files.get('definitions/manifest.json')
        if not raw or not index or len(raw)>LIMIT or len(index)>65536:raise ValueError('请选择完整的角色定义包 ZIP')
        meta=json.loads(index)
        if hashlib.sha256(raw).hexdigest()!=meta.get('sha256'):raise ValueError('角色定义包内容校验失败')
        pack=json.loads(raw);validate_pack(pack)
        with self.lock:
            self.root.mkdir(parents=True,exist_ok=True)
            name='characters-'+hashlib.sha256(raw).hexdigest()+'.json'
            (self.root/name).write_bytes(raw)
            meta['file']=name
            pending=self.root/'manifest.pending'
            pending.write_bytes(canonical(meta));pending.replace(self.root/'manifest.json')
            self.cache=None
        return self.catalog()

def validate_pack(pack):
    if not isinstance(pack,dict) or pack.get('schema')!=PACK_SCHEMA:raise ValueError('角色定义包版本不支持')
    chars=pack.get('characters')
    if not isinstance(chars,dict) or len(chars)>2000:raise ValueError('角色定义目录无效')
    for key,c in chars.items():
        if not isinstance(c,dict) or c.get('id')!=key or not key.isdigit() or not isinstance(c.get('records'),dict):raise ValueError('角色定义条目无效')
        selection=c['records'].get('character',{}).get('selected',{}).get(key,{})
        rows=selection.get('rows',[])
        if not rows or len(rows[0])<37 or rows[0][0]!=c.get('code'):raise ValueError('角色行与资源代号不一致：'+key)
    for kind in ('ability','leader_ability'):
        _validate_row(pack.get('blankRows',{}).get(kind),kind)

def _validate_row(row,kind,unchanged_source=False):
    width=int(describe.layout(kind)['ncols'])
    if not isinstance(row,list) or not width<=len(row)<=256:raise ValueError('能力行列数无效')
    if any(not isinstance(v,str) or len(v)>4000 or any(c in v for c in '\r\n"') for v in row):raise ValueError('能力单元格包含无效内容')
    problems=client_legality_problems(kind,row)
    if problems and not unchanged_source:raise ValueError('；'.join(problems[:5]))
    if kind=='ability' and row[1] not in ('true','false'):raise ValueError('主位限定必须使用 true/false')

def validate_native(value):
    if value is None:return
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA:raise ValueError('MOD 角色数据版本不支持')
    source=value.get('source',{})
    if not isinstance(source,dict) or source.get('sha256')!=digest(source.get('data')):raise ValueError('原始角色定义校验失败')
    data=source.get('data')
    if not isinstance(data,dict) or not isinstance(data.get('character'),dict):raise ValueError('原始角色定义结构无效')
    original_character=data['character'];cid=original_character.get('id')
    validate_pack({'schema':PACK_SCHEMA,'characters':{cid:original_character},'blankRows':data.get('blankRows')})
    cr=original_character['records']['character']['selected'][cid]['rows'][0]
    groups=value.get('abilities')
    if not isinstance(groups,list) or len(groups)!=6 or any(not isinstance(a,dict) for a in groups) or [a.get('slot') for a in groups]!=list(range(1,7)):raise ValueError('MOD 能力需要六个有序槽位')
    if not isinstance(value.get('leader'),dict):raise ValueError('队长技数据无效')
    if [value['leader'].get('sourceKey'),*[g.get('sourceKey') for g in groups]]!=[cr[17],*cr[19:25]]:raise ValueError('能力来源键与角色真实引用不一致')
    for group in [value.get('leader',{}),*groups]:
        rs=group.get('rows')
        if not isinstance(rs,list) or len(rs)>128:raise ValueError('单个能力槽最多 128 行')
        kind='leader_ability' if group is value['leader'] else 'ability'
        source_groups=source['data']['character']['records']['leader_ability' if kind=='leader_ability' else 'abilities']['selected']
        original=source_groups.get(group.get('sourceKey'),{}).get('rows',[])
        for row in rs:_validate_row(row,kind,row in original)
    skills=value.get('skills')
    if not isinstance(skills,list) or len(skills)>32:raise ValueError('技能版本定义无效')
    if [s.get('inner_key') for s in skills if isinstance(s,dict)]!=[s['inner_key'] for s in original_character['records']['action_skill']['rows']]:raise ValueError('技能版本键与来源不一致')
    for item in skills:
        fields=item.get('fields',[])
        if not isinstance(fields,list) or not 8<=len(fields)<=128 or any(not isinstance(v,str) or len(v)>16000 or '\x00' in v for v in fields):raise ValueError('技能原始行无效')
        if item.get('raw_csv') is not None and core.read_csv_lines(item['raw_csv'])!=[fields]:raise ValueError('技能文本与编辑字段不一致')
        for index in (4,5):
            if not fields[index].isdigit() or not 1<=int(fields[index])<=9999:raise ValueError('技能能量必须为 1 至 9999')
    canonical(value)

def attach(store,pid,revision,library,cid=None):
    pack=library.load()
    if pack is None:raise ValueError('请先安装角色定义包')
    p=store.load(pid)
    if p['revision']!=revision:raise ValueError('工程已更新，请重新打开')
    if p.get('nativeGameplay'):raise ValueError('此工程已载入角色定义；已有能力编辑会继续保留')
    cid=str(cid or (p.get('template') or {}).get('id',''))
    c=pack['characters'].get(cid)
    if not c:raise ValueError('定义包中没有这个参考角色')
    template=p.get('template') or {}
    if template and (str(template.get('id'))!=cid or str(template.get('version'))!=str(pack['version'])):
        raise ValueError('角色定义与美术模板的角色或版本不一致')
    c=copy.deepcopy(c); records=c['records'];cr=records['character']['selected'][cid]['rows'][0]
    def selection(label,key):return copy.deepcopy(records[label]['selected'].get(key,{}).get('rows',[]))
    source={'version':pack['version'],'character':c,'blankRows':copy.deepcopy(pack['blankRows'])}
    p['nativeGameplay']={'schema':SCHEMA,'source':{'sha256':digest(source),'data':source},
        'leader':{'sourceKey':cr[17],'rows':selection('leader_ability',cr[17])},
        'abilities':[{'slot':i+1,'sourceKey':key,'rows':selection('abilities',key)} for i,key in enumerate(cr[19:25])],
        'skills':copy.deepcopy(records['action_skill']['rows'])}
    validate_native(p['nativeGameplay'])
    return store.save(p)

def blank_factory(native,slot):
    kind='leader_ability' if slot=='leader' else 'ability'
    def make(_key):
        row=list(native['source']['data']['blankRows'][kind]);b=describe.layout(kind)['blocks']
        row[0]='';row[b['precondition1']-1]='0'
        if kind=='ability':row[1]='true';row[2]='attack_common';row[3]='0';row[4]=''
        else:row[1]=row[2]='0'
        return {'kind':kind,'row':row}
    return make

def group_for(native,slot):
    if slot=='leader':return native['leader'],'leader_ability'
    if isinstance(slot,bool) or not isinstance(slot,int) or not 1<=slot<=6:raise ValueError('能力槽位无效')
    return native['abilities'][slot-1],'ability'

def scaled(value,factor,label):
    try:
        if isinstance(value,bool):raise ValueError()
        n=Decimal(str(value))*factor
        if not n.is_finite() or n!=n.to_integral_value() or abs(n)>2147483647:raise ValueError()
        return str(int(n))
    except (ValueError,InvalidOperation):raise ValueError(label+'数值超出范围或精度')

def describe_native(native):
    if not native:return {'installed':False}
    validate_native(native)
    out={'installed':True,'source':{k:native['source']['data']['character'][k] for k in ('id','code','name')},'version':native['source']['data']['version'],'groups':[],'skills':native['skills']}
    for slot in ['leader',1,2,3,4,5,6]:
        group,kind=group_for(native,slot);b=describe.layout(kind)['blocks'];entries=[]
        for index,row in enumerate(group['rows']):
            mode=row[b['precondition1']-1];cb=b['instant_content'] if mode=='0' else b['during_content'] if mode=='1' else None
            effect=next((e for e in composer._FXGEN_EFFECTS if cb is not None and e[2]==('instant' if mode=='0' else 'during') and e[3]==row[cb]),None)
            unit=effect[4] if effect else 'raw';factor=composer._unit_mul(unit)
            entries.append({'index':index,'description':describe.describe_line(row,kind),'mainOnly':kind=='ability' and row[1]=='false',
                'issues':client_legality_problems(kind,row),
                'mode':mode,'unit':unit,'editable':cb is not None,
                'value':str(Decimal(row[cb+4])/factor) if cb is not None and row[cb+4].lstrip('-').isdigit() else '',
                'valueMax':str(Decimal(row[cb+5])/factor) if cb is not None and row[cb+5].lstrip('-').isdigit() else '',
                'duration':str(Decimal(row[cb+10])/6000000) if mode=='0' and row[cb+10].lstrip('-').isdigit() else '',
                'row':row})
        out['groups'].append({'slot':slot,'kind':kind,'sourceKey':group['sourceKey'],'rows':entries})
    out['replay']=native['source']['data']['character']['records'].get('battle_replay')
    return out

def edit(store,pid,revision,operation,slot=None,index=None,spec=None):
    p=store.load(pid)
    if p['revision']!=revision:raise ValueError('工程已更新，请重开后编辑')
    native=p.get('nativeGameplay');validate_native(native)
    if not native:raise ValueError('请先载入角色定义')
    spec={} if spec is None else spec
    if not isinstance(spec,dict):raise ValueError('能力编辑参数无效')
    if 'mainOnly' in spec and not isinstance(spec['mainOnly'],bool):raise ValueError('主位条件必须为开关值')
    if spec.get('duration') not in (None,'') and int(scaled(spec['duration'],6000000,'持续时间'))<0:raise ValueError('持续时间不能为负数')
    if operation=='skill':
        if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(native['skills']):raise ValueError('技能版本无效')
        row=native['skills'][index]['fields']
        for k,i in (('name',0),('description',1),('energy',4),('energyMax',5)):
            if k in spec:row[i]=str(spec[k])
        native['skills'][index]['raw_csv']=csv_text([row])
    else:
        group,kind=group_for(native,slot)
        if operation=='add':
            allowed={'trigger_id','effect_id','value','value_max','threshold','target','groups','precondition_kind','precondition_threshold'}
            params={k:v for k,v in spec.items() if k in allowed}
            if not params.get('trigger_id') or not params.get('effect_id'):raise ValueError('请选择触发与效果')
            tr=next((t for t in composer._FXGEN_TRIGGERS if t[0]==params['trigger_id']),None)
            fx=next((e for e in composer._FXGEN_EFFECTS if e[0]==params['effect_id'] and e[3]!='629'),None)
            if not tr or not fx:raise ValueError('请选择支持的触发与效果')
            if str(params.get('target','0')) not in {str(k) for k in describe.TARGET_CN}:raise ValueError('作用对象无效')
            if params.get('groups','') not in dict(composer._FXGEN_GROUPS):raise ValueError('角色组无效')
            if params.get('precondition_kind','') not in ('',None,*describe.enum_options()['precondition']):raise ValueError('前置条件无效')
            for name,unit in (('value',fx[4]),('value_max',fx[4]),('threshold',tr[4] or 'count'),('precondition_threshold','pct')):
                if params.get(name) not in (None,''):scaled(params[name],composer._unit_mul(unit),'能力数值')
            cr=native['source']['data']['character']['records']['character']['selected'][native['source']['data']['character']['id']]['rows'][0]
            value=composer.generate('L:draft' if slot=='leader' else 'draft',**params,blank_factory=blank_factory(native,slot),element_index=lambda _:int(cr[3]))
            row=value['row']
            if kind=='ability':row[1]='false' if spec.get('mainOnly') else 'true'
            if spec.get('duration') not in (None,''):
                cb=describe.layout(kind)['blocks']['instant_content']
                if row[describe.layout(kind)['blocks']['precondition1']-1]!='0':raise ValueError('持续触发条目不使用瞬发持续时间')
                row[cb+10]=row[cb+11]=scaled(spec['duration'],6000000,'持续时间')
            _validate_row(row,kind);group['rows'].append(row)
        else:
            if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(group['rows']):raise ValueError('能力条目无效')
            if operation=='delete':group['rows'].pop(index)
            elif operation=='patch':
                row=group['rows'][index];b=describe.layout(kind)['blocks'];mode=row[b['precondition1']-1]
                if mode not in ('0','1'):raise ValueError('开幕类原始条目暂保留原值')
                cb=b['instant_content'] if mode=='0' else b['during_content']
                info=describe_native(native)['groups'][0 if slot=='leader' else slot]['rows'][index]
                factor=composer._unit_mul(info['unit'])
                for key,offset in (('value',4),('valueMax',5)):
                    if key in spec and spec[key]!='':row[cb+offset]=scaled(spec[key],factor,'能力强度')
                if 'mainOnly' in spec and kind=='ability':row[1]='false' if spec['mainOnly'] else 'true'
                if spec.get('duration') not in (None,'') and mode=='0':row[cb+10]=row[cb+11]=scaled(spec['duration'],6000000,'持续时间')
                _validate_row(row,kind)
            else:raise ValueError('不支持的词条操作')
    validate_native(native)
    return store.save(p)

def compile_native(native):
    """Serialize isolated draft tables using MOD codecs; never a live table overlay."""
    validate_native(native)
    files={};receipt={'kind':'native-gameplay','readback':True,'gameReady':False,'sourceKeysAllocated':False,'tables':[]}
    def table(name,keys,rows,nested=False):
        path='native-draft/'+name+'.orderedmap'
        build=core.build_orderedmap_raw_rows if nested else core.build_orderedmap
        read=core.read_orderedmap_raw_rows_from_bytes if nested else core.read_orderedmap_bytes
        raw=build(core.OrderedMap('<draft>',keys,rows,Path('.')))
        decoded=read(raw,'<draft>')
        if decoded.keys!=keys or decoded.rows!=rows:raise ValueError('MOD 表编译回读失败：'+name)
        files[path]=raw;receipt['tables'].append({'file':path,'keys':keys,'sha256':hashlib.sha256(raw).hexdigest()})
    table('ability',['ability_'+str(g['slot']) for g in native['abilities']],[csv_text(g['rows']).encode('utf-8') for g in native['abilities']])
    table('leader_ability',['leader'],[csv_text(native['leader']['rows']).encode('utf-8')])
    skills=native['skills']
    inner=core.build_orderedmap(core.OrderedMap('<draft-skill>',[s['inner_key'] for s in skills],[csv_text([s['fields']]).encode('utf-8') for s in skills],Path('.')))
    if core.decode_action_skill_row(inner)!=[(s['inner_key'],s['fields']) for s in skills]:raise ValueError('技能版本编译回读失败')
    table('action_skill',['skill'],[inner],nested=True)
    manifest={'schema':'starpoint-native-draft-v1','gameReady':False,'sourceCharacter':native['source']['data']['character']['id'],
              'sourceHash':native['source']['sha256'],'abilitySlots':[{'draftKey':'ability_'+str(g['slot']),'sourceKey':g['sourceKey']} for g in native['abilities']],
              'leaderSourceKey':native['leader']['sourceKey'],'note':'这些是单角色草稿表，使用临时槽位键；接入器必须重新分配 ID 并合并完整主表，不能覆盖游戏资源。'}
    files['native-draft/manifest.json']=canonical(manifest)
    return files,receipt
