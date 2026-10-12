'use strict';
const audioUses={home:'主界面语音',join:'加入角色',evolution:'进化语音',battle_start:'战斗开始',skill_voice:'技能喊声',skill_ready:'技能就绪',power_flip:'强化弹射喊声',attack:'攻击喊声',outhole:'落穴语音',win:'胜利语音',login:'登录语音',story_words:'剧情短语/语料',battle:'其他战斗语音',other:'其他角色语音',skill_sfx:'技能音效',hit_sfx:'命中音效',charge_sfx:'蓄力音效',move_sfx:'移动音效',other_sfx:'其他音效'};
let audioTab='voices',audioFilter='',audioLimit=100;
const briefAudioUsage={home_base:'home',home_evolved:'home',acquisition:'join',detail:'other',enhancement:'other',evolution:'evolution',battle_start:'battle_start',skill:'skill_voice',pf:'power_flip',victory:'win',defeat:'battle',damage:'outhole',down:'outhole',skill_sfx:'skill_sfx',hit_sfx:'hit_sfx',pf_sfx:'power_flip',charge_sfx:'charge_sfx'};
function briefAudioList(kind){const brief=S.p.productionBrief||{};return kind==='sounds'?(brief.sounds||[]):(brief.voices||[]);}
function briefAudioStatus(item){if(!item)return '未配置';const state=pbRowGuidance(item,audioTab==='sounds'?'sounds':'voices');if(!state.authorComplete)return '作者待补 / 关联待核';if(state.makerPending)return '作者已说明 · 接入待核';return '有效关联 · 原生待验';}
function audioRequirementPanel(kind){
  const items=briefAudioList(kind),required=items.filter(item=>item.required),done=required.filter(item=>pbRowGuidance(item,kind).authorComplete).length;
  if(!items.length)return '';
  const rows=items.map(item=>'<div class="audio-requirement-row '+(item.required?'required':'')+'"><div><strong>'+esc(item.label)+'</strong><small>'+(kind==='sounds'?'音效用途':'语音用途')+(item.pairId?' · 成对':'')+'</small></div><span class="audio-requirement-status">'+briefAudioStatus(item)+'</span><button data-audio-requirement="'+esc(item.id)+'" data-audio-requirement-kind="'+kind+'">导入并绑定</button></div>').join('');
  return '<section class="audio-requirements"><div class="audio-requirements-head"><div><strong>'+(kind==='sounds'?'技能 / 战斗音效':'角色语音')+'制作清单</strong><p>按用途绑定文件，状态会同步到“角色制作包”。作者意图已说明 '+done+' / '+required.length+'。</p></div><span class="audio-requirements-note">'+(kind==='sounds'?'施放、命中、PF、蓄力可在技能时间轴继续调整':'按角色意图选择复用、无配音或申请协助；台词保留完整原文')+'</span></div><div class="audio-requirement-list">'+rows+'</div></section>';
}
function importBriefAudio(kind,id){
  const item=briefAudioList(kind).find(row=>row.id===id);if(!item)return;
  upload(kind==='sounds'?'sfx':'voice',ids=>{
    if(!ids.length)return;
    const first=ids[0],asset=S.p.assets[first],list=kind==='sounds'?S.p.sounds:S.p.voices,usage=briefAudioUsage[item.id]||(kind==='sounds'?'other_sfx':'other');
    let record=list.find(row=>row.productionId===item.id);
    if(!record){record={id:uid(),productionId:item.id,name:item.label,text:item.textJapanese??'',entry:item.entry??'',usage};list.push(record);}
    record.name=item.label;item.status='provided';item.source='new_recording';item.assetId=first;item.filename=asset?.name||'';
    // Importing a recording changes its binding, not the existing confirmed
    // script. The same migration is used by selecting an already imported file.
    pbApplyAudioRecord(record,item,kind);
    if(ids.length>1)for(const extra of ids.slice(1)){const extraAsset=S.p.assets[extra];list.push({id:uid(),productionId:item.id+'-'+uid(),name:item.label+' · '+(extraAsset?.name||'补充'),asset:extra,text:'',usage});}
  },'audio/wav,audio/mpeg,audio/ogg');
}
function renderVoices(){
  S.p.voices??=[];
  S.p.sounds??=[];
  const isSound=audioTab==='sounds',list=S.p[audioTab],uses=Object.entries(audioUses).filter(([key])=>key.endsWith('_sfx')===isSound);
  $('#content').innerHTML=header('声音与台词','按游戏用途整理角色喊声与环境/技能声音。',`<button id="voice-upload" class="primary">＋ 导入${isSound?'音效':'语音'}</button>`)+
    `<div class="audio-explainer"><div><b>角色语音：角色说的话</b><p>主界面、加入、进化、战斗开始、技能喊声、胜利等；剧情短语另外分类。</p></div><div><b>技能音效：招式发出的声音</b><p>例如蓄力、挥砍、雷鸣、爆炸和命中。可以在特效时间轴上指定播放帧，与画面一起预览。</p></div><div><b>台词文字：文本与交接信息</b><p>模板登记的文本会带入。自填文字用于字幕设计和交接，不会自动显示成游戏字幕；剧情还需要事件与对话脚本。</p></div></div>
    <div class="audio-tabs"><button data-audio-tab="voices" class="${isSound?'':'primary'}">角色语音 ${S.p.voices.length}</button><button data-audio-tab="sounds" class="${isSound?'primary':''}">技能 / 战斗音效 ${S.p.sounds.length}</button><select id="audio-filter"><option value="">全部用途</option>${uses.map(([v,t])=>`<option value="${v}" ${v===audioFilter?'selected':''}>${t}</option>`).join('')}</select></div>${audioRequirementPanel(isSound?"sounds":"voices")}
    <div class="hint">导入标准 WAV、MP3、OGG，每个文件 ≤ 64 MiB。推荐无削波、去除多余首尾静音的音频；恒定码率（CBR）MP3 可编译为游戏存储格式，WAV/OGG 先用于预览交接。</div>
    <div id="audio-rows"></div><p class="footer-note">用途分类用于整理素材。实际主界面语音表、技能触发和剧情字幕仍需在角色接入时绑定。</p>`;
  function rows(){const filtered=list.filter(v=>!audioFilter||(v.usage||'other')===audioFilter);$('#audio-rows').innerHTML=filtered.slice(0,audioLimit).map(v=>{const declaration=typeof authorVoiceView==='function'&&!isSound?authorVoiceView(v):null;return `<section class="audio-row"><div class="audio-row-info"><input data-audio-name="${v.id}" value="${esc(v.name)}" aria-label="声音名称"><select data-audio-usage="${v.id}" aria-label="声音用途"><option value="" ${(declaration?.usage??v.usage??'')===''?'selected':''}>未标注 · 请确认</option>${(declaration?.usage??v.usage)&&!uses.some(([key])=>key===(declaration?.usage??v.usage))?'<option value="'+esc(declaration?.usage??v.usage)+'" selected>'+esc(declaration?.usage??v.usage)+'</option>':''}${uses.map(([key,label])=>`<option value="${key}" ${key===(declaration?.usage??v.usage??'')?'selected':''}>${label}</option>`).join('')}</select><audio controls preload="none" src="${assetUrl(v.asset)}"></audio><button data-audio-track="${v.id}">加入演出</button><button data-audio-replace="${v.id}">替换</button><button data-audio-delete="${v.id}" aria-label="移除声音">×</button></div><textarea data-audio-text="${v.id}" aria-label="台词或声音说明" placeholder="${isSound?'声音说明、用途或制作备注':'台词文字 / 字幕设计'}">${esc(declaration?.text??v.text)}</textarea>${!isSound&&typeof authorVoiceExtras==='function'?authorVoiceExtras(v):''}${v.logical?`<small>模板来源：${esc(v.logical)}</small>`:''}</section>`;}).join('')+(filtered.length>audioLimit?`<button id="audio-more">继续显示（已显示 ${audioLimit} / ${filtered.length}）</button>`:'')+(filtered.length?'':'<div class="empty">此分类尚未添加声音，可导入文件或选择包含声音的角色模板。</div>');
    if(typeof wireAuthorDeclarations==='function')wireAuthorDeclarations($('#audio-rows'));
    if($('#audio-more'))$('#audio-more').onclick=()=>{audioLimit+=100;rows();};
    for(const key of ['name','usage','text'])$$('[data-audio-'+key+']').forEach(input=>input.onchange=()=>mutate(()=>{const v=list.find(v=>v.id===input.dataset['audio'+key[0].toUpperCase()+key.slice(1)]);if(!isSound&&['usage','text'].includes(key)&&typeof authorSyncVoiceFields==='function')authorSyncVoiceFields(v,key,input.value);else v[key]=input.value;},false));
    $$('[data-audio-track]').forEach(b=>b.onclick=()=>mutate(()=>{const v=list.find(v=>v.id===b.dataset.audioTrack);S.p.scene.tracks.push({id:uid(),type:'audio',ref:v.asset,start:0,speed:1,volume:1});toast('已加入演出轨道，可在演出页调整开始帧');},false));
    $$('[data-audio-replace]').forEach(b=>b.onclick=()=>{const v=list.find(v=>v.id===b.dataset.audioReplace),old=v.asset;upload(isSound?'sfx':'voice',ids=>{if(!ids[0])return;if(!isSound&&typeof authorReplaceVoiceAsset==='function')authorReplaceVoiceAsset(v,ids[0]);else v.asset=ids[0];if(!isSound)syncVoiceDeclaration(v,'asset');for(const a of S.p.effects)for(const ev of a.soundEvents||[])if(ev.asset===old)ev.asset=ids[0];for(const t of S.p.scene.tracks)if(t.type==='audio'&&t.ref===old)t.ref=ids[0];},'audio/wav,audio/mpeg,audio/ogg');});
    $$('[data-audio-delete]').forEach(b=>b.onclick=()=>mutate(()=>{const index=list.findIndex(v=>v.id===b.dataset.audioDelete);if(!isSound&&typeof authorRemoveVoiceDeclarations==='function')authorRemoveVoiceDeclarations(list[index]);list.splice(index,1);}));
    bindAudioUpgrade();
  }
  $$('[data-audio-tab]').forEach(b=>b.onclick=()=>{audioTab=b.dataset.audioTab;audioFilter='';audioLimit=100;renderVoices();});$('#audio-filter').onchange=e=>{audioFilter=e.target.value;audioLimit=100;rows();};
  $$('[data-audio-requirement]').forEach(b=>b.onclick=()=>importBriefAudio(b.dataset.audioRequirementKind,b.dataset.audioRequirement));
  $('#voice-upload').onclick=()=>upload(isSound?'sfx':'voice',ids=>list.push(...ids.map(asset=>({id:uid(),asset,name:S.p.assets[asset].name,text:'',usage:isSound?'skill_sfx':'other'}))),'audio/wav,audio/mpeg,audio/ogg');rows();
}
function effectSoundPanel(anim){const events=anim.soundEvents||[];return `<section class="effect-sounds"><div class="timeline-heading"><b>声音事件</b><span>${events.length} 个 · 播放特效时同步试听</span><button id="add-sound-event">＋ 添加声音</button></div><div class="hint">开始帧从 0 计，表示距当前特效起点的时间。原角色音效会按模板时间轴带入；喊声也可在这里添加。</div>${events.map(ev=>`<div class="sound-event"><label>开始帧<input type="number" min="0" max="4095" value="${ev.start}" data-event-start="${ev.id}"></label><select data-event-asset="${ev.id}"><option value="">${esc(ev.path||'未绑定声音')}</option>${Object.values(S.p.assets).filter(a=>a.mime.startsWith('audio/')).map(a=>`<option value="${a.id}" ${a.id===ev.asset?'selected':''}>${esc(a.name)}</option>`).join('')}</select><label>音量<input type="number" min="0" max="1" step="0.1" value="${ev.volume??1}" data-event-volume="${ev.id}"></label><label>次数（-1 循环）<input type="number" min="-1" max="100" value="${ev.loop??1}" data-event-loop="${ev.id}"></label><label>结束帧（-1 自然结束）<input type="number" min="-1" max="4096" value="${ev.end??-1}" data-event-end="${ev.id}"></label><button data-event-listen="${ev.id}">试听</button><button data-event-delete="${ev.id}">×</button></div>`).join('')}</section>`;}
function bindEffectSounds(anim){
  if(!$('#add-sound-event'))return;
  $('#add-sound-event').onclick=()=>{const first=Object.values(S.p.assets).find(a=>a.mime.startsWith('audio/'));if(!first)return toast('先在“声音与台词”中导入技能音效或角色语音',true);mutate(()=>{anim.soundEvents??=[];anim.soundEvents.push({id:uid(),asset:first.id,path:'',start:0,volume:1,enabled:true});});};
  for(const key of ['start','asset','volume','loop','end'])$$('[data-event-'+key+']').forEach(input=>input.onchange=()=>mutate(()=>{const ev=anim.soundEvents.find(e=>e.id===input.dataset['event'+key[0].toUpperCase()+key.slice(1)]);ev[key]=key==='asset'?(input.value||null):Number(input.value);},false));
  $$('[data-event-delete]').forEach(b=>b.onclick=()=>mutate(()=>anim.soundEvents.splice(anim.soundEvents.findIndex(e=>e.id===b.dataset.eventDelete),1)));
  $$('[data-event-listen]').forEach(b=>b.onclick=()=>{const ev=anim.soundEvents.find(e=>e.id===b.dataset.eventListen);if(!ev.asset)return toast('该声音尚未收录，请绑定音频',true);const a=new Audio(assetUrl(ev.asset));a.volume=ev.volume??1;S.audio.push(a);a.play().catch(e=>{if(e.name!=='AbortError'&&S.audio.includes(a))toast('音频无法播放',true);});});
}

function syncVoiceDeclaration(voice,changedField=''){
  if(S.p.voiceDeclarations!=null&&!Array.isArray(S.p.voiceDeclarations))throw Error('旧语音说明表格式无效，请先处理检查中的格式问题');
  S.p.voiceDeclarations??=[];
  const view=typeof authorVoiceView==='function'?authorVoiceView(voice):null;
  // Only an explicit edit reconciles the changed field. Keep the declaration's
  // other text/usage/entry and all unknown fields instead of overwriting them.
  if(changedField&&view?.d)for(const key of ['usage','text','entry'])if(key!==changedField&&view[key]!=null)voice[key]=view[key];
  const matches=view?.matches?.map(match=>match.d)||[];
  const legacy=S.p.voiceDeclarations.filter(item=>item&&typeof item==='object'&&(item.voiceId===voice.id||(item.asset===voice.asset&&(S.p.voices||[]).filter(v=>v.asset===voice.asset).length===1)));
  const rows=[...new Set([...matches,...legacy])];
  if(!rows.length){const row={voiceId:voice.id,asset:voice.asset};S.p.voiceDeclarations.push(row);rows.push(row);}
  for(const row of rows){Object.assign(row,{voiceId:voice.id,asset:voice.asset,usage:voice.usage,entry:voice.entry||'',text:voice.text||''});if(!row.file||legacy.includes(row))row.file=S.p.assets[voice.asset]?.name||'';}
  const brief=(S.p.productionBrief?.voices||[]).find(item=>item.id===voice.productionId);
  if(brief){brief.entry=voice.entry||'';brief.textJapanese=voice.text||'';brief.assetId=voice.asset;}
}
const voiceEntryLabels={ally:'加入角色 / 获取时',battle:'战斗中',home:'主界面',login:'登录时',words:'剧情对话'};
const audioProfileFields=[['targetLufs','目标音量（LUFS）',-70,0,null],['truePeakCeilingDbtp','峰值上限（dBTP）',-30,0,null],['toleranceLu','音量允许差值（LU）',0,20,1],['paddingToleranceSeconds','编码后时长允许差值（秒）',0,1,.08]];
function audioProfileUpdate(current,kind,values,references){
  if(!['voice','sfx'].includes(kind))throw Error('声音用途必须为语音或音效');
  if(current!==undefined&&(current===null||typeof current!=='object'||Array.isArray(current)))throw Error('已有声音设置格式异常，请交给制作方核验，原设置保留');
  const result=clone(current||{}),prior=result[kind];
  if(Object.hasOwn(result,kind)&&(prior===null||typeof prior!=='object'||Array.isArray(prior)))throw Error('已有语音或音效设置格式异常，原设置保留');
  const row={...(prior||{})};
  for(const [key,label,low,high,fallback] of audioProfileFields){
    const text=values[key];
    if(typeof text!=='string')throw Error(label+'必须使用普通数值填写');
    const value=text.trim()===''?null:Number(text);
    if(value===null&&fallback===null){row[key]=null;continue;}
    if(value===null||!Number.isFinite(value)||value<low||value>high)throw Error(label+'需在 '+low+' 至 '+high+' 之间');
    row[key]=value;
  }
  if(!Array.isArray(references)||references.length>30||references.some(id=>typeof id!=='string'))throw Error('参考音频最多选择 30 项');
  row.referenceAssetIds=[...references];result[kind]=row;return result;
}
function audioNumber(value,unit='',digits=2){return typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits)+unit:'待测 / 无有效读数';}
function audioMeasureMarkup(value){
  if(!value)return '<p class="notice">尚无完整解码读数，保留待核。</p>';
  return `<dl><dt>整体音量</dt><dd>${audioNumber(value.integratedLufs,' LUFS')}</dd><dt>最高峰值</dt><dd>${audioNumber(value.truePeakDbtp,' dBTP')}</dd><dt>削波样本</dt><dd>${Number.isInteger(value.clippedSamples)?value.clippedSamples===0?'未检测到削波':esc(String(value.clippedSamples))+' 个，请检查失真':'待核'}</dd><dt>完整解码时长</dt><dd>${audioNumber(value.decodedSeconds,' 秒',3)}</dd><dt>声道比较方式</dt><dd>${value.measurementChannels===1?'统一单声道'+(value.foldMethod==='L/2+R/2'?'（左右声道各取一半）':''): '声道待核'} · ${value.fullDecode===true?'已完整解码':'完整解码待核'}</dd></dl>`;
}
function audioChecksMarkup(checks){
  if(!checks)return '';
  const names={clipping:'削波',duration:'编码后时长',truePeak:'峰值上限',loudness:'目标音量'};
  return '<ul>'+Object.entries(names).map(([key,label])=>`<li>${label}：${checks[key]===true?'符合当前设置':checks[key]===false?'需调整':'未设置目标或读数待核'}</li>`).join('')+'</ul>';
}
function audioReportMarkup(report){
  const references=Object.entries(report.references||{}).map(([kind,ref])=>`<section class="form-card"><h3>${kind==='voice'?'语音':'音效'}参考</h3><p>已选 ${(ref.references||[]).length} 段 · 参考中位音量 ${audioNumber(ref.referenceMedianLufs,' LUFS')}。参考只用于比较，不自动替你设置目标。</p>${(ref.references||[]).map(row=>`<p>${esc(S.p.assets[row.asset]?.name||'待核参考音频')}：${row.error?esc(row.error):audioNumber(row.measure?.integratedLufs,' LUFS')}</p>`).join('')}</section>`).join('');
  const statuses={blocked:'测量受阻',handoff_only:'原稿可交接，封装待核',risk:'当前设置有风险',measured:'已测量，目标仍待核',profile_pass:'指标符合当前设置，听感与游戏仍待核'};
  return `<p>语音和音效分开比较。指标符合设置也需要试听；游戏入口、触发及原生封装仍待核。</p>${references}${(report.rows||[]).map(row=>`<section class="form-card"><h3>${esc(row.name||'未命名声音')}</h3><p>${statuses[row.status]||'待核'} · 游戏入口${row.pathStatus==='registered_evidence_supplied'?'已有登记依据，仍需验证':'待登记核验'}</p>${row.error?`<p class="notice">${esc(row.error)}</p>`:''}<h4>当前文件</h4>${audioMeasureMarkup(row.original)}${row.postEncodeDecode?'<h4>游戏存储格式回读</h4>'+audioMeasureMarkup(row.postEncodeDecode)+`<p>封装回读字节：${row.packagingRoundtrip===true?'一致，游戏播放仍待验':'待核'} · 与原声时长差 ${audioNumber(row.durationDeltaSeconds,' 秒',3)}</p>`:'<p>尚无游戏存储格式回读结果，不能当作游戏可用。</p>'}${audioChecksMarkup(row.checks)}${row.matchedReferenceDeltaLu!=null?`<p>与所选参考音量差 ${audioNumber(row.matchedReferenceDeltaLu,' LU')}</p>`:''}</section>`).join('')||'<p>没有已绑定的声音，可先导入原稿或在作者填写包说明需要协助。</p>'}`;
}
function acceptAudioProject(project){
  snapshot();S.p=project;S.dirty=false;S.generation=(S.generation||0)+1;
  if($('#undo'))$('#undo').disabled=!S.undo.length;
  if($('#redo'))$('#redo').disabled=true;
}
function bindAudioUpgrade(){
  const tab=audioTab,kind=tab==='sounds'?'sfx':'voice',rows=S.p[tab],profile=S.p.audioProfile?.[kind]||{};
  if(!$('#audio-review-open')){
    const references=Array.isArray(profile.referenceAssetIds)?profile.referenceAssetIds:[];
    const assets=Object.values(S.p.assets).filter(a=>a.mime?.startsWith('audio/'));
    const missing=references.filter(id=>!assets.some(a=>a.id===id));
    const field=([key,label,low,high,fallback])=>`<label>${label}<input data-audio-profile="${key}" type="number" min="${low}" max="${high}" step="0.01" value="${esc(profile[key]??fallback??'')}" placeholder="${fallback===null?'尚未确定，可留空':''}"></label>`;
    $('#content').insertAdjacentHTML('beforeend',`<section class="form-card"><h3>${kind==='voice'?'语音':'音效'}音量与试听候选</h3><p>先测原声，再按本角色意图填写目标。原声保留，候选不会自动替换。没有目标或参考时先交接协助，不套用其他角色的标准。</p><button id="audio-review-open">测量音量、峰值与时长</button><div class="field-row">${audioProfileFields.slice(0,2).map(field).join('')}</div><p class="hint">LUFS 数值越接近 0，整体声音越大；峰值上限用于检查尖峰和失真。目标还不确定时可先选择参考音频，听感与读数一起比较。</p><label>参考音频（最多 30 段）<select id="audio-profile-references" multiple size="${Math.max(2,Math.min(6,assets.length+missing.length))}" aria-label="按名称选择参考音频">${assets.map(a=>`<option value="${esc(a.id)}" ${references.includes(a.id)?'selected':''}>${esc(a.name||'未命名音频')}</option>`).join('')}${missing.map((id,i)=>`<option value="${esc(id)}" selected>第 ${i+1} 段参考未找到，待核</option>`).join('')}</select></label><p class="hint">可按住 Ctrl 多选；参考和候选统一单声道比较，左右声道各取一半，不改变原稿。</p><details><summary>可选：调整允许差值</summary><div class="field-row">${audioProfileFields.slice(2).map(field).join('')}</div></details><button id="audio-profile-save">保存本类声音设置</button></section>`);
  }
  $('#audio-profile-save').onclick=()=>busy('保存声音设置',async()=>{const values=Object.fromEntries($$('[data-audio-profile]').map(input=>[input.dataset.audioProfile,input.value])),references=[...$('#audio-profile-references').selectedOptions].map(option=>option.value);const value=audioProfileUpdate(S.p.audioProfile,kind,values,references);await saveNow();const next=clone(S.p);next.audioProfile=value;const saved=await api('/api/save',next);acceptAudioProject(saved);renderVoices();toast('声音设置已保存，原声保留');});
  $('#audio-review-open').onclick=()=>busy('完整解码与编码后测量',async()=>{await saveNow();const r=await api('/api/audio-review',{id:S.p.id});modal(`<h2>声音测量结果</h2>${audioReportMarkup(r)}`);});
  for(const voice of rows){
    const section=$(`[data-audio-name="${voice.id}"]`)?.closest('section');if(!section)continue;
    section.insertAdjacentHTML('beforeend',`${kind==='voice'?`<label>语音播放位置<select data-voice-entry="${voice.id}"><option value="">还不确定，交给制作方核验</option>${Object.entries(voiceEntryLabels).map(([entry,label])=>`<option value="${entry}" ${voice.entry===entry?'selected':''}>${label}</option>`).join('')}${voice.entry&&!Object.hasOwn(voiceEntryLabels,voice.entry)?`<option value="${esc(voice.entry)}" selected>已有特殊入口，保留待核</option>`:''}</select></label>`:''}<p class="hint">游戏触发与封装仍需核验；这里的用途选择用于制作交接。</p><details><summary>制作方：登记游戏声音入口依据（可留空）</summary><label>登记依据<input data-audio-evidence="${voice.id}" value="${esc(voice.registrationEvidence)}" placeholder="尚未确认时保留空白"></label></details><button data-audio-candidate="${voice.id}">生成音量候选并对比试听</button>${voice.usage==='join'?`<button data-entry-layout="${voice.id}">获取台词全文与排版候选</button>`:''}`);
    const current=()=>S.p[tab].find(row=>row.id===voice.id);
    const entry=section.querySelector('[data-voice-entry]');if(entry){if(typeof authorVoiceView==='function')entry.value=authorVoiceView(voice).entry;entry.onchange=()=>mutate(()=>{const row=current();row.entry=entry.value;syncVoiceDeclaration(row,'entry');});}
    const text=section.querySelector('[data-audio-text]');text.onchange=()=>mutate(()=>{const row=current();if(kind==='voice'&&typeof authorSyncVoiceFields==='function')authorSyncVoiceFields(row,'text',text.value);else row.text=text.value;if(kind==='voice')syncVoiceDeclaration(row,'text');});
    const usage=section.querySelector('[data-audio-usage]');usage.onchange=()=>mutate(()=>{const row=current();if(kind==='voice'&&typeof authorSyncVoiceFields==='function')authorSyncVoiceFields(row,'usage',usage.value);else row.usage=usage.value;if(kind==='voice')syncVoiceDeclaration(row,'usage');});
    section.querySelector('[data-audio-evidence]').onchange=event=>mutate(()=>current().registrationEvidence=event.target.value,false);
    section.querySelector('[data-audio-candidate]').onclick=()=>busy('保留原声并生成独立候选',async()=>{
      await saveNow();const source=current(),r=await api('/api/audio-candidate',{id:S.p.id,revision:S.p.revision,asset:source.asset,kind});acceptAudioProject(r.project);
      const c=r.candidate;modal(`<h2>候选已生成，原声保留</h2><p>候选尚未应用。先分别试听，再决定是否使用；原声仍保存在工程中，可用撤销恢复。</p><section class="form-card"><h3>原声</h3><audio controls preload="none" src="${assetUrl(c.originalAsset)}"></audio>${audioMeasureMarkup(c.before)}</section><section class="form-card"><h3>候选</h3><audio controls preload="none" src="${assetUrl(c.candidateAsset)}"></audio>${audioMeasureMarkup(c.postEncodeDecode)}<p>与原声时长差 ${audioNumber(c.durationDeltaSeconds,' 秒',3)}；游戏入口、触发和封装仍待核。</p>${audioChecksMarkup({clipping:c.postEncodeDecode?.clippedSamples===0,duration:Math.abs(c.durationDeltaSeconds)<=c.profile.paddingToleranceSeconds,truePeak:c.postEncodeDecode?.truePeakDbtp==null?null:c.postEncodeDecode.truePeakDbtp<=c.profile.truePeakCeilingDbtp,loudness:c.postEncodeDecode?.integratedLufs==null?null:Math.abs(c.postEncodeDecode.integratedLufs-c.profile.targetLufs)<=c.profile.toleranceLu})}</section><button id="candidate-apply">使用此候选，保留原声</button><button id="candidate-keep-original">继续使用原声</button>`);
      $('#candidate-keep-original').onclick=()=>{$('#modal').close();renderVoices();};
      $('#candidate-apply').onclick=()=>{const target=current();mutate(()=>{target.candidateOf=target.candidateOf||c.originalAsset;if(kind==='voice'&&typeof authorReplaceVoiceAsset==='function')authorReplaceVoiceAsset(target,c.candidateAsset);else target.asset=c.candidateAsset;if(kind==='voice')syncVoiceDeclaration(target,'asset');});$('#modal').close();};
    });
    const layout=section.querySelector('[data-entry-layout]');if(layout)layout.onclick=()=>openEntryLayout(current());
  }
}
function entryChangesMarkup(changes){
  const names={delete:'删除',insert:'增加',replace:'替换'},visible=text=>esc(text.replace(/\r/g,'［回车］').replace(/\n/g,'［换行］').replace(/ /g,'［空格］'));
  return changes.length?'<ol>'+changes.map(change=>`<li><strong>${names[change.operation]||'修改'}</strong>：${change.original?`原文“${visible(change.original)}”`: '原文此处为空'} → ${change.candidate?`候选“${visible(change.candidate)}”`:'候选此处为空'}</li>`).join('')+'</ol>':'<p>字词与换行均未改变。</p>';
}
function entryOriginalText(voice,project){
  if(voice.entryLayout&&Object.hasOwn(voice.entryLayout,'original'))return voice.entryLayout.original;
  if(voice.text?.trim())return voice.text;
  const brief=(project.productionBrief?.voices||[]).find(row=>row.id===voice.productionId);
  return brief?.textJapanese||'';
}
function openEntryLayout(voice){
  const original=entryOriginalText(voice,S.p),candidate=voice.entryLayout?.candidate??original;
  if(!original.trim()){
    modal('<h2>获取台词全文尚未提供</h2><p>请在声音条目补充完整台词，或到作者填写包说明暂无配音、需要协助或沿用参考。空台词不能当作已完成的排版。</p><button id="entry-go-production">去作者填写包说明</button>');
    $('#entry-go-production').onclick=()=>{$('#modal').close();S.page='production';render();};return;
  }
  modal(`<h2>获取台词全文与近似排版</h2><p>保留全文，候选不会覆盖原文。这里估算换行与气泡；游戏字体、首次获取显示和完整台词仍需实际核验。</p>${voice.entry?'':'<p class="notice">语音播放位置尚未说明，请补充或在作者填写包申请协助，原生入口保持待核。</p>'}<label>保留完整原文<textarea id="entry-original" rows="8" readonly>${esc(original)}</textarea></label><label>排版候选（可调整换行和字词）<textarea id="entry-candidate" rows="8">${esc(candidate)}</textarea></label><button id="entry-remove-breaks">候选去手动换行（保留字词）</button><button id="entry-preview">更新近似预览与逐条变化</button><div id="entry-preview-result" aria-live="polite"></div><label><input type="checkbox" id="entry-author-confirmed" ${voice.entryLayout?.authorConfirmed?'checked':''}>我已逐条确认这份候选的字词变化</label><button id="entry-layout-save">仅保存排版候选，保留原文</button>`);
  let previewSequence=0;
  const show=()=>busy('估算气泡与原文差异',async()=>{const submitted=$('#entry-candidate').value,sequence=++previewSequence,r=await api('/api/entry-layout',{original,candidate:submitted});if(sequence!==previewSequence||!$('#entry-preview-result')||$('#entry-candidate').value!==submitted)return;$('#entry-preview-result').innerHTML=`<p>原文 ${r.originalCharacters} 字符 · 候选 ${r.candidateCharacters} 字符 · 估算 ${r.lineCount} 行 · ${r.overflow?'超出估算边界，请调整候选或申请协助':'仍需原生核验'}${r.wordingChanged?' · 字词变化需稿主确认':''}</p><div style="background:white;color:#222;border-radius:18px;padding:14px;max-width:360px;min-height:116px;box-sizing:content-box;font:20px/26px Microsoft YaHei,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere">${esc(r.lines.join('\n'))}</div><h3>逐条变化</h3>${entryChangesMarkup(r.changes)}`;});
  $('#entry-candidate').oninput=()=>{$('#entry-author-confirmed').checked=false;previewSequence++;$('#entry-preview-result').textContent='候选已修改，请更新预览再逐条确认变化。';};
  $('#entry-preview').onclick=show;$('#entry-remove-breaks').onclick=()=>{$('#entry-candidate').value=$('#entry-candidate').value.replace(/[\r\n]/g,'');$('#entry-author-confirmed').checked=false;show();};
  $('#entry-layout-save').onclick=()=>{const next={...(voice.entryLayout||{}),original,candidate:$('#entry-candidate').value,authorConfirmed:$('#entry-author-confirmed').checked};mutate(()=>{const row=S.p.voices.find(row=>row.id===voice.id);row.entryLayout=next;},false);$('#modal').close();};show();
}

// Declaration edits also update the corresponding optional production brief.
if(typeof document!=='undefined'&&typeof document.addEventListener==='function')document.addEventListener('change',event=>{
  const input=event.target,row=input?.closest?.('[data-author-kind="voice"]');if(!row||!input.dataset.authorField||!S.p||typeof authorCurrentVoice!=='function')return;
  const view=authorCurrentVoice(row.dataset.authorKey);if(!view?.v)return;
  const brief=(S.p.productionBrief?.voices||[]).find(item=>item.id===view.v.productionId);if(!brief)return;
  brief.textJapanese=view.text;brief.entry=view.entry;brief.assetId=view.v.asset;
  if(input.dataset.authorField==='entry')view.v.entry=view.entry;
});
