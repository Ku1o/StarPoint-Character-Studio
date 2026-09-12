"""Use the MOD field layouts to edit and combine individual ability components."""
import copy
from functools import lru_cache
import native_gameplay as n

@lru_cache(maxsize=1)
def metadata():
    return n.composer.composer_meta()

def validate_row(kind,row):
    n._validate_row(row,kind)
    meta=metadata();b=meta['kinds'][kind]['blocks'];mode=row[b['precondition1']-1]
    blocks=['precondition1','precondition2','precondition3']+({'0':['instant_trigger','instant_precontent','instant_delay','instant_content'],'1':['during_accumulation_trigger','during_trigger','during_content','even_if_owner_dead'],'2':['opening']}[mode])
    categories={'precondition':'precondition','instant_trigger':'trigger','during_accumulation_trigger':'trigger','during_trigger':'during_trigger','instant_content':'instant_content','during_content':'during_content'}
    for block in blocks:
        name=block.rstrip('123');base=b[block]
        if block in ('instant_precontent','during_accumulation_trigger') and row[base]=='(None)':continue
        enum=meta['enums'].get(categories.get(name),meta['small'].get({'opening':'opening','instant_precontent':'precontent'}.get(name)))
        if enum is not None and row[base] not in enum:raise ValueError('未知的条件或效果编号：'+block+' = '+row[base])
        for off,key,_ in meta['block_fields'].get(name,[]):
            value=row[base+off]
            numeric=any(part in key for part in ('strength','threshold','frame.','number.')) or key in ('instant_delay','cooltime','trigger_limit','max_accumulation','flip_limit','power_flip_limit','end_power_flip_limit','initial_multiply','mt.additional_multiply','mt.trigger_limit')
            if numeric and value not in ('','(None)'):
                if not value.lstrip('-').isdigit() or abs(int(value))>2147483647:raise ValueError('数值需要是范围内的整数：'+key)

def preview(kind,row):
    if kind not in ('ability','leader_ability'):raise ValueError('词条类型无效')
    try:validate_row(kind,row);issues=[]
    except ValueError as error:issues=[str(error)]
    description=n.describe.describe_line(row,kind) if isinstance(row,list) and len(row)>=n.describe.layout(kind)['ncols'] else ''
    return {'description':description,'issues':issues,'valid':not issues}

def draft(store,pid,slot,index=None):
    p=store.load(pid);data=p.get('nativeGameplay');n.validate_native(data)
    if not data:raise ValueError('请先选择参考角色定义')
    group,kind=n.group_for(data,slot)
    if index is None:
        row=n.blank_factory(data,slot)('draft')['row'];b=n.describe.layout(kind)['blocks']
        row[b['instant_trigger']]='0';row[b['instant_content']]='32';row[b['instant_content']+4]='10000';row[b['instant_content']+5]='20000'
    else:
        if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(group['rows']):raise ValueError('词条位置无效')
        row=copy.deepcopy(group['rows'][index])
    return {'row':row,'kind':kind,'revision':p['revision'],**preview(kind,row)}

def apply(store,pid,revision,slot,index,row):
    p=store.load(pid)
    if p['revision']!=revision:raise ValueError('工程已更新，请重新打开编辑器')
    data=p.get('nativeGameplay');n.validate_native(data)
    if not data:raise ValueError('请先选择参考角色定义')
    group,kind=n.group_for(data,slot);validate_row(kind,row)
    if index is None:group['rows'].append(copy.deepcopy(row))
    else:
        if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(group['rows']):raise ValueError('词条位置无效')
        group['rows'][index]=copy.deepcopy(row)
    n.validate_native(data);return store.save(p)

def transfer(store,pid,revision,slot,index,target,position,copy_row=False):
    p=store.load(pid)
    if p['revision']!=revision:raise ValueError('工程已更新，请重新打开')
    data=p.get('nativeGameplay');n.validate_native(data)
    if not data:raise ValueError('请先选择参考角色定义')
    source,kind=n.group_for(data,slot);dest,dest_kind=n.group_for(data,target)
    if kind!=dest_kind:raise ValueError('整条移动需要同类型；跨类型请在拆解编辑器取用条件或效果块')
    if not isinstance(copy_row,bool):raise ValueError('复制操作无效')
    if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(source['rows']):raise ValueError('来源条目位置无效')
    if isinstance(position,bool) or not isinstance(position,int) or not 0<=position<=len(dest['rows']):raise ValueError('目标条目位置无效')
    row=copy.deepcopy(source['rows'][index]);n._validate_row(row,kind)
    if not copy_row:source['rows'].pop(index)
    dest['rows'].insert(min(position,len(dest['rows'])),row)
    n.validate_native(data);return store.save(p)
