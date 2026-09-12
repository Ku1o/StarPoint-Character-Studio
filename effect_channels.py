"""Editable per-instance effect channels and deterministic frame composition."""
from __future__ import annotations
import copy
import hashlib
import math

VALUES={'x':0,'y':0,'rotation':0,'scale':1,'opacity':1}

def make_channels(effect):
    found={}
    for tick,commands in enumerate(effect.get('nativeFrames',[])):
        for command in commands:
            key=command.get('channel')
            if not key:continue
            if key not in found:
                found[key]={'id':key,'name':'图层 '+str(len(found)+1),'sourceAsset':command['asset'],'sourceStart':tick,'sourceEnd':tick+1,
                            'start':tick,'end':tick+1,'asset':None,'visible':True,**VALUES,'keys':[],
                            'sourceOrder':command.get('channelOrder',[])}
            found[key]['sourceEnd']=found[key]['end']=tick+1
    effect['channels']=sorted(found.values(),key=lambda c:c['sourceOrder'])
    for index,channel in enumerate(effect['channels']):channel['name']='图层 '+str(index+1)
    effect['channelDuration']=len(effect.get('nativeFrames',[]))
    return effect['channels']

def validate_channels(effect,assets):
    if 'channels' not in effect:return
    from studio_core import StudioError,integer,number,identifier
    channels=effect['channels']
    known={c.get('channel') for frame in effect.get('nativeFrames',[]) for c in frame}
    if not isinstance(channels,list) or len(channels)>max(2048,len(known)+256):raise StudioError('新增通道过多，请拆分为多个特效')
    integer(effect.get('channelDuration'),1,4096,'特效总时长')
    known={c.get('channel') for frame in effect.get('nativeFrames',[]) for c in frame}
    seen=set()
    for c in channels:
        cid=identifier(c.get('id'))
        if cid in seen or (c.get('sourceChannel',cid) not in known and not c.get('custom')):raise StudioError('特效通道重复或来源不存在')
        seen.add(cid)
        if not isinstance(c.get('name'),str) or len(c['name'])>150:raise StudioError('通道名称无效')
        if not isinstance(c.get('visible',True),bool):raise StudioError('通道显示状态无效')
        for k in ('start','sourceStart'):integer(c.get(k),0,4095,'通道开始帧')
        for k in ('end','sourceEnd'):integer(c.get(k),1,4096,'通道结束帧')
        if c['end']<=c['start'] or c['sourceEnd']<=c['sourceStart']:raise StudioError('通道结束帧必须晚于开始帧')
        if c['end']>effect['channelDuration']:raise StudioError('通道超出特效总时长')
        if not c.get('custom') and c['sourceEnd']>len(effect.get('nativeFrames',[])):raise StudioError('通道取材范围超出原动画')
        if c.get('asset') and assets.get(c['asset'],{}).get('mime')!='image/png':raise StudioError('通道替换图片不存在或不是 PNG')
        if c.get('custom') and not c.get('asset'):raise StudioError('新增通道需要一张 PNG')
        def values(v):
            for k,lo,hi in [('x',-4096,4096),('y',-4096,4096),('rotation',-3600,3600),('scale',.05,20),('opacity',0,1)]:number(v.get(k,VALUES[k]),lo,hi,'通道 '+k)
        values(c);keys=c.get('keys',[])
        if not isinstance(keys,list) or len(keys)>4096:raise StudioError('通道关键帧过多')
        frames=[]
        for key in keys:integer(key.get('frame'),0,4095,'关键帧');values(key);frames.append(key['frame'])
        if frames!=sorted(set(frames)):raise StudioError('关键帧需要按帧数排列且不能重复')

def parameters(channel,tick):
    keys=channel.get('keys',[])
    if not keys:return {k:channel.get(k,v) for k,v in VALUES.items()}
    left=keys[0];right=keys[-1]
    if tick<=left['frame']:return {k:left.get(k,v) for k,v in VALUES.items()}
    if tick>=right['frame']:return {k:right.get(k,v) for k,v in VALUES.items()}
    for first,second in zip(keys,keys[1:]):
        if first['frame']<=tick<=second['frame']:
            ratio=(tick-first['frame'])/(second['frame']-first['frame'])
            return {k:first.get(k,v)+(second.get(k,v)-first.get(k,v))*ratio for k,v in VALUES.items()}

def edited(effect):
    if 'channels' not in effect:return False
    base={'nativeFrames':effect.get('nativeFrames',[])};make_channels(base)
    def relevant(channels):return [{k:v for k,v in c.items() if k not in ('name','sourceOrder')} for c in channels]
    return relevant(effect['channels'])!=relevant(base['channels']) or effect.get('channelDuration')!=base['channelDuration']

def compose_frames(effect):
    from bridge import flatomo
    indexed={}
    for frame,commands in enumerate(effect.get('nativeFrames',[])):
        for command in commands:indexed.setdefault(command.get('channel'),{}).setdefault(frame,[]).append(command)
    result=[]
    for tick in range(effect['channelDuration']):
        commands=[]
        for channel in effect['channels']:
            if channel.get('visible') is False or not channel['start']<=tick<channel['end']:continue
            source=channel['sourceStart']+int((tick-channel['start'])*(channel['sourceEnd']-channel['sourceStart'])/(channel['end']-channel['start']))
            original=indexed.get(channel.get('sourceChannel',channel['id']),{}).get(source,[])
            if channel.get('custom'):original=[{'asset':channel['asset'],'matrix':[1,0,0,1,0,0],'alpha':1,'fx':0,'fy':0,'blend':0,'colorTransform':[1,0,0,0]}]
            values=parameters(channel,tick);angle=math.radians(values['rotation']);c=math.cos(angle)*values['scale'];s=math.sin(angle)*values['scale']
            for source_command in original:
                cmd=copy.deepcopy(source_command);layer=effect.get('layers',{}).get(cmd['asset'],{})
                if layer.get('visible') is False:continue
                cmd['asset']=channel.get('asset') or layer.get('asset') or cmd['asset']
                cmd['fx']=cmd.get('fx',0)-layer.get('x',0);cmd['fy']=cmd.get('fy',0)-layer.get('y',0)
                matrix=list(flatomo._concat((c,s,-s,c,0,0),cmd['matrix']));matrix[4]+=values['x'];matrix[5]+=values['y']
                cmd['matrix']=matrix;cmd['alpha']*=values['opacity'];cmd['channel']=channel['id'];commands.append(cmd)
        result.append(commands)
    return result

def prepare(store,pid,revision,effect_id):
    from studio_core import StudioError
    p=store.load(pid)
    if p['revision']!=revision:raise StudioError('工程已更新，请重新打开')
    effect=next((a for a in p['effects'] if a['id']==effect_id),None)
    if not effect or not effect.get('native'):raise StudioError('请选择原生模板特效')
    if effect.get('channels'):return p
    path=effect['native']['path'];folder=path.split('/')[1]
    names=[path,path.replace('.parts.json','.timeline.json'),f'effect/{folder}/{folder}.png',f'effect/{folder}/{folder}.atlas.json']
    root=(store.directory(pid)/'reference').resolve();reference={}
    for name in names:
        target=(root/name).resolve()
        if not target.is_relative_to(root) or name not in p['referenceFiles']:raise StudioError('缺少原生特效来源')
        reference[name]=target.read_bytes()
    scratch=copy.deepcopy(p);scratch['effects']=[];store.import_effects(scratch,reference)
    rebuilt=next(a for a in scratch['effects'] if a['native']['path']==path and a['native']['sequence']==effect['native']['sequence'])
    if not rebuilt.get('channels'):raise StudioError('此特效未能解析出通道：'+'；'.join(rebuilt.get('issues',[])))
    effect['nativeFrames']=rebuilt['nativeFrames'];make_channels(effect)
    p['assets']=scratch['assets']
    return store.save(p)

def compile_channels(store,p,effect,code):
    """Bake edited transforms into legal PartsAnimation frames and preserve sound."""
    from PIL import Image
    from studio_core import png_bytes,image_from,FAKE_PNG,StudioError
    from studio_compile import amf_bytes
    from audio_compile import effect_audio
    validate_channels(effect,p['assets']);frames=compose_frames(effect)
    if sum(map(len,frames))>200000:raise StudioError('编辑后的特效指令超过 20 万条，请缩短或拆分特效')
    root=f"battle/effect/skill_unique/{code}/{effect['id']}"
    cells=[];atlas=[];images=[];segments=[];matrices=[];matrix_index={};cell_index={};x=y=1;row_h=0
    for tick,commands in enumerate(frames):
        for cmd in commands:
            color=tuple(cmd.get('colorTransform',[1,0,0,0]));key=(cmd['asset'],color,cmd.get('fx',0),cmd.get('fy',0))
            if key not in cell_index:
                cell=image_from(store.asset_bytes(p,cmd['asset']))
                if color!=(1,0,0,0):
                    bands=list(cell.split())
                    for i in range(3):bands[i]=bands[i].point([max(0,min(255,round(v*color[0]+color[i+1]))) for v in range(256)])
                    cell=Image.merge('RGBA',bands)
                if cell.width>2046 or cell.height>2046:raise StudioError('通道图片超出 2046 px')
                if x+cell.width+1>2048:x=1;y+=row_h+2;row_h=0
                index=len(images);name=f'{root}/.gen/channel/{index}';cell_index[key]=index
                images.append({'s':False,'p':name});atlas.append({'n':name,'x':x,'y':y,'w':cell.width,'h':cell.height,'fx':cmd.get('fx',0),'fy':cmd.get('fy',0)})
                cells.append((cell,x,y));x+=cell.width+2;row_h=max(row_h,cell.height)
            matrix=tuple(round(v*4096) for v in cmd['matrix'])
            if matrix not in matrix_index:matrix_index[matrix]=len(matrices);matrices.append(dict(zip(('a','b','c','d','x','y'),matrix)))
            packed=(matrix_index[matrix]<<12)|(int(cmd.get('blend',0))<<8)|max(0,min(255,round(cmd['alpha']*255)))
            segments.append({'s':tick,'i':cell_index[key],'l':[{'m':packed,'t':1}]})
    height=y+row_h+1
    if height>8192:raise StudioError('通道图集超过 8192 px，请缩小替换图片')
    if not matrices:matrices=[{'a':4096,'b':0,'c':0,'d':4096,'x':0,'y':0}]
    sheet=Image.new('RGBA',(2048,max(2,height)))
    for cell,x,y in cells:sheet.paste(cell,(x,y))
    parts={'i':images,'g':[{'t':len(frames),'s':segments}],'m':[],'a':[1]*len(images),'o':[],'t':matrices,'c':[],'s':effect.get('frameScale',1)}
    sounds,audio_files,issues=effect_audio(store,p,effect,code)
    timeline={'sequences':[{'begin':1,'end':len(frames),'name':effect['native']['sequence'],'kind':effect['kind']}],'sounds':sounds,'points':[],'circles':[],'rectangles':[],'matrices':[]}
    return {**audio_files,f"{root}/{effect['id']}.png":FAKE_PNG+png_bytes(sheet)[8:],f"{root}/{effect['id']}.atlas.amf3.deflate":amf_bytes(atlas),f'{root}/effect.parts.amf3.deflate':amf_bytes(parts),f'{root}/effect.timeline.amf3.deflate':amf_bytes(timeline)},'；'.join(issues) or None
