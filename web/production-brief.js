'use strict';
const PB_STATUS=[['author_package','作者填写包'],['maker_review','制作方核验'],['asset_production','资源制作'],['data_implementation','数据实现'],['practice_battle','练习战验收'],['release_handoff','发布整合']];
const PB_ITEM_STATUS=[['missing','尚未提供'],['provided','已关联文件'],['reuse_official','计划复用'],['needs_review','待确认'],['not_applicable','不适用']];
const PB_AUTHOR_POLICY=[['unmarked','直接填写或提供文件'],['needs_help','请协助制作'],['cannot_provide','暂时无法提供'],['explicit_reuse','明确复用'],['maker_derive','由母版派生'],['not_applicable','不适用并说明理由'],['maker_review','请制作方确认'],['author_pending','稍后补充']];
const PB_SOURCE=[['new_recording','新录制'],['reuse_official','复用已有声音'],['to_generate','请协助制作'],['not_applicable','不适用']];
const PB_NATIVE=[['unknown','待核实'],['native_supported','原生支持'],['client_adaptation','需客户端适配'],['needs_verification','待制作方核验']];
const PB_REVIEW=[['unreviewed','未确认'],['pass','已通过'],['risk','有风险'],['not_applicable','不适用']];
const PB_REQUIRED_AUTHOR=new Set(['author.characterName','author.title','author.role','author.race','author.baseForm','author.evolvedForm']);
const PB_REQUIRED_PLANS=new Set(['plans.activeSkill.name','plans.activeSkill.authorDescription','plans.pf.name','plans.pf.authorDescription','plans.leader.name','plans.leader.authorDescription']);
const pbPath=path=>path.split('.').reduce((value,key)=>value==null?undefined:value[key],S.p.productionBrief);
const pbValue=value=>Array.isArray(value)?value.join(', '):(value??'');
function pbAssign(path,value){const parts=path.split('.');let target=S.p.productionBrief;for(const key of parts.slice(0,-1)){if(target[key]==null)target[key]={};target=target[key];}target[parts.at(-1)]=value;}
function pbMirror(path){
  if(path==='author.characterName')return {get:()=>S.p.name,set:v=>{S.p.name=v;}};
  const identity=path.match(/^author\.(title|element|role|race)$/);
  if(identity)return {get:()=>S.p.identity?.[identity[1]],set:v=>{S.p.identity??={};S.p.identity[identity[1]]=v;}};
  const plan=path.match(/^plans\.(activeSkill|pf|leader|abilities\.(\d+))\.(name|authorDescription)$/);
  if(!plan)return null;
  const key=plan[3]==='authorDescription'?'description':'name',group=plan[1],index=plan[2];
  const object=create=>{if(create)S.p.gameplay??=typeof newGameplayDesign==='function'?newGameplayDesign():{skill:{},leader:{},abilities:[]};const g=S.p.gameplay;if(!g)return null;if(index!==undefined){const slot=S.p.productionBrief.plans.abilities[Number(index)].slot;if(create)g.abilities??=[];let row=g.abilities?.find(x=>x.slot===slot);if(!row&&create){row={slot,name:'',description:''};g.abilities.push(row);}return row;}const field=group==='activeSkill'?'skill':group;if(create)g[field]??={name:'',description:''};return g[field];};
  return {get:()=>group==='activeSkill'?(S.p.skill?.[key]??object(false)?.[key]):object(false)?.[key],set:v=>{object(true)[key]=v;if(group==='activeSkill'){S.p.skill??={};S.p.skill[key]=v;}}};
}
function pbSyncEdited(path,value){pbMirror(path)?.set(value);}
function pbSet(path,value){mutate(()=>{pbAssign(path,value);pbSyncEdited(path,value);});}
function pbRequired(path,explicit=false){return explicit||PB_REQUIRED_AUTHOR.has(path)||PB_REQUIRED_PLANS.has(path);}
function pbBadge(required,text=required?'需要说明':'可选'){return `<span class="pb-badge ${required?'required':'optional'}">${esc(text)}</span>`;}
function pbLabel(path,label,required=false){return `<label for="pb-${path.replaceAll('.','-')}">${esc(label)} ${pbBadge(pbRequired(path,required))}</label>`;}
function pbInput(path,label,type='text',extra='',required=false){return `<div class="field">${pbLabel(path,label,required)}<input data-pb-path="${esc(path)}" id="pb-${path.replaceAll('.','-')}" type="${type}" value="${esc(pbValue(pbPath(path)))}" ${extra}></div>`;}
function pbText(path,label,extra='',required=false){return `<div class="field">${pbLabel(path,label,required)}<textarea data-pb-path="${esc(path)}" id="pb-${path.replaceAll('.','-')}" ${extra}>${esc(pbValue(pbPath(path)))}</textarea></div>`;}
function pbSelect(path,label,options){return `<div class="field">${pbLabel(path,label)}<select data-pb-path="${esc(path)}" id="pb-${path.replaceAll('.','-')}">${options.map(([value,text])=>`<option value="${esc(value)}" ${String(value)===String(pbPath(path))?'selected':''}>${esc(text)}</option>`).join('')}</select></div>`;}
function pbTextState(value,policy={}){const reason=String(policy.reason||'').trim(),reference=String(policy.reference||'').trim(),state=policy.state||'unmarked';return {authorComplete:!!value||(!['unmarked','author_pending'].includes(state)&&!!reason&&(!['explicit_reuse','maker_derive'].includes(state)||!!reference)),makerPending:state!=='unmarked'};}
function pbPolicyFields(prefix,item,kind){const state=['resources','voices','sounds'].includes(kind)?pbRowGuidance(item,kind):pbTextState(item.name?.trim()&&item.authorDescription?.trim(),item.authorPolicy);return `<div class="author-policy">${pbSelect(prefix+'.authorPolicy.state','这项如何完成',PB_AUTHOR_POLICY)}${pbText(prefix+'.authorPolicy.reason','具体说明：希望的结果、困难与可接受的调整','rows="2" placeholder="例如：我没有命中特效，请协助制作紫色闪光，可参考已上传的技能画稿。"')}${pbInput(prefix+'.authorPolicy.reference','已有参考、母版名称或希望复用的角色')}<p class="hint" data-pb-feedback="${prefix}" data-pb-feedback-kind="${kind}">${state.authorComplete?'作者意图已说明':'可以补充内容，或说明希望协助的部分'} · ${state.makerPending?'制作方待确认':'接入与实际表现仍需核验'}。说明不会制造素材或游戏验收结果。</p></div>`;}
function pbIdentityPolicy(key,label){const prefix='authorPolicy.identity.'+key;return `<details><summary>${esc(label)}暂未确定，写协助说明</summary>${pbSelect(prefix+'.state','这项如何完成',PB_AUTHOR_POLICY)}${pbText(prefix+'.reason','详细理由与希望的结果','rows="2"')}${pbInput(prefix+'.reference','已有参考（没有可留空）')}</details>`;}
function pbPlan(path,title,plan){const core=['plans.activeSkill','plans.pf','plans.leader'].includes(path);return `<section class="form-card production-plan"><h3>${esc(title)} ${pbBadge(core,core?'填写意图或协助说明':'按需填写')}</h3><p>用“何时、对谁、做什么、持续多久”描述。不知道数值或无法完成时，选择协助并写清想法。</p>${pbInput(path+'.name','名称','text','placeholder="例如：月影守护"')}${pbText(path+'.authorDescription','给制作方的自然语言说明','rows="3" placeholder="例如：受到攻击后，为全队提升攻击力 10 秒。"')}${pbPolicyFields(path,plan,'plan')}<details><summary>补充表现意图（可选）</summary>${pbInput(path+'.trigger','何时发动')}${pbInput(path+'.target','作用于谁')}${pbInput(path+'.range','表现范围')}${pbInput(path+'.hits','段数 / 次数')}${pbInput(path+'.multiplier','倍率 / 数值')}${pbInput(path+'.duration','持续多久')}${pbInput(path+'.cooldown','冷却或刷新要求')}${pbInput(path+'.statusIcon','状态与图标意图')}</details></section>`;}
function pbAssetPreview(id,kind){const asset=S.p.assets[id];if(!asset)return '<p class="notice">之前关联的文件现已缺失，请重新选择。</p>';return kind==='resources'?`<img src="${assetUrl(id)}" alt="${esc(asset.name)}" style="max-width:100px;max-height:100px"><span>${esc(asset.name)}</span>`:`<p>${esc(asset.name)}</p><audio controls preload="none" src="${assetUrl(id)}"></audio>`;}
function pbResourceRow(item,index){const prefix='resources.'+index;return `<section class="form-card production-resource-card"><div><h3>${esc(item.label)} ${pbBadge(item.required,item.required?'需说明用途':'可选')}</h3><p>${esc(item.frameHint||'可提供文件、复用参考，或详细说明需要协助的部分。')}</p><div>${(item.assetIds||[]).map(id=>pbAssetPreview(id,'resources')).join('')||'<p>尚未关联图片</p>'}</div><button data-pb-pick="${prefix}">选择已有图片</button><button data-pb-upload="${prefix}">上传并关联</button><button data-pb-unlink="${prefix}">移除本项关联</button>${pbSelect(prefix+'.status','素材状态',PB_ITEM_STATUS)}${pbPolicyFields(prefix,item,'resources')}${pbText(prefix+'.notes','用途与制作备注','rows="2"')}</div></section>`;}
const PB_ENTRIES=[['','用途待确认'],['ally','加入、强化、进化或角色详情'],['battle','战斗中播放'],['home','主界面播放'],['login','登录播放'],['words','剧情语料']];
function pbAudioRow(item,index,kind='voices'){const prefix=kind+'.'+index;const options=PB_ENTRIES.some(([id])=>id===item.entry)?PB_ENTRIES:[...PB_ENTRIES,[item.entry,'保留原有入口（制作方待确认）']];return `<section class="form-card production-resource-card"><div><h3>${esc(item.label)} ${pbBadge(item.required,item.required?'文件或协助说明':'可选')}</h3>${item.assetId?pbAssetPreview(item.assetId,kind):'<p>尚未关联声音</p>'}<button data-pb-pick="${prefix}">选择已有声音</button><button data-pb-upload="${prefix}">上传并关联</button><button data-pb-unlink="${prefix}">移除本项关联</button>${pbSelect(prefix+'.status','素材状态',PB_ITEM_STATUS)}${kind==='voices'?pbSelect(prefix+'.entry','希望在哪里播放',options):''}${pbText(prefix+'.textJapanese',kind==='voices'?'完整台词原文（无台词请说明）':'声音效果说明','rows="2"')}${pbPolicyFields(prefix,item,kind)}${pbText(prefix+'.notes','制作备注','rows="2"')}</div></section>`;}
function pbRowGuidance(item,kind){
  const trim=value=>String(value??'').trim(),policy=item.authorPolicy||{},state=policy.state||'unmarked',status=item.status,assets=S.p.assets||{};
  const ids=kind==='resources'?(item.assetIds||[]):(item.assetId?[item.assetId]:[]),supplied=['provided','reuse_official'].includes(status);
  const linksValid=ids.every(id=>Object.hasOwn(assets,id)&&(!assets[id]?.mime||assets[id].mime.startsWith(kind==='resources'?'image/':'audio/'))),valid=ids.length>0&&linksValid;
  let authorComplete=supplied&&valid,makerPending=supplied;
  const voiceContentRequired=kind==='voices'&&(status==='provided'||(status==='reuse_official'&&ids.length>0));
  if(voiceContentRequired&&(!trim(item.entry)||!trim(item.textJapanese)))authorComplete=false;
  const brokenProvided=(status==='provided'&&!authorComplete)||!linksValid||(voiceContentRequired&&!authorComplete);
  if(state==='unmarked'){
    if(status==='not_applicable'){authorComplete=Boolean(trim(item.notes));makerPending=true;}
    else if(status==='reuse_official'){makerPending=true;}
    else if(['missing','needs_review'].includes(status)){authorComplete=false;makerPending=status==='needs_review';}
    const voice=S.p.productionBrief?.authorPolicy||{};
    if(kind==='voices'&&status==='missing'&&['none','reuse'].includes(voice.voiceMode)){authorComplete=Boolean(trim(voice.voiceReason))&&(voice.voiceMode==='none'||Boolean(trim(voice.voiceReference)));makerPending=true;}
  }else if(state==='author_pending'){authorComplete=false;}
  else {authorComplete=(['explicit_reuse','maker_derive'].includes(state)?Boolean(trim(policy.reference)):Boolean(trim(policy.reason)))&&!brokenProvided;makerPending=true;}
  return {authorComplete,makerPending,integrationVerified:false};
}
function pbProgress(b){const author=[...PB_REQUIRED_AUTHOR],done=author.filter(path=>{const key=path.split('.')[1];return pbTextState(String(pbPath(path)||'').trim(),b.authorPolicy?.identity?.[key]).authorComplete;}).length;const plans=['activeSkill','pf','leader'],planDone=plans.filter(key=>pbTextState(b.plans[key].name?.trim()&&b.plans[key].authorDescription?.trim(),b.plans[key].authorPolicy).authorComplete).length;const resources=b.resources.filter(x=>x.required),audio=[...b.voices.map(x=>[x,'voices']),...b.sounds.map(x=>[x,'sounds'])].filter(([x])=>x.required);return {author:[done,author.length],plans:[planDone,3],resources:[resources.filter(x=>pbRowGuidance(x,'resources').authorComplete).length,resources.length],voices:[audio.filter(([x,k])=>pbRowGuidance(x,k).authorComplete).length,audio.length]};}
function pbSummary(b){const p=pbProgress(b);return `<section class="production-required-summary"><h3>作者意图与协助范围</h3><p>允许复用、母版派生、无配音和具体协助说明。文件收到、作者意图说明与游戏可用分别记录。任何阶段都能保存工程交接。</p><div class="required-summary-grid">${[['角色信息',p.author],['主动技能 / PF / 队长技',p.plans],['图片与动作意图',p.resources],['声音意图',p.voices]].map(([name,[done,total]])=>`<div class="required-summary-card"><strong>${name}</strong><span>${done} / ${total}</span></div>`).join('')}</div></section>`;}
function pbConflicts(){const paths=[...PB_REQUIRED_AUTHOR,'author.element',...['activeSkill','leader','pf'].flatMap(key=>['name','authorDescription'].map(field=>'plans.'+key+'.'+field)),...(S.p.productionBrief.plans.abilities||[]).flatMap((row,index)=>['name','authorDescription'].map(field=>'plans.abilities.'+index+'.'+field))];return paths.filter(path=>{const mirror=pbMirror(path);return mirror&&String(mirror.get()??'')!==String(pbPath(path)??'');});}
function renderProductionBrief(){
  const opened=[...document.querySelectorAll('#content details[open]')].map(node=>node.querySelector('summary')?.textContent),b=S.p.productionBrief,conflicts=pbConflicts();
  $('#content').innerHTML=header('作者填写包','说明想做怎样的角色，选择真实素材或提出具体协助需求。','<button id="production-export" class="primary">保存并下载制作交接</button>')+pbSummary(b)+
  (conflicts.length?`<section class="form-card"><h3>其他设计页与填写包有不同内容</h3><p>旧值完整保留。逐项选择采用哪一版；只同步设计文字，原生词条不会被覆盖。</p>${conflicts.map(path=>`<div class="notice"><p><strong>${esc(pbFieldTitle(path))}</strong><br>其他设计页：${esc(pbMirror(path).get()||'空白')}<br>填写包：${esc(pbPath(path)||'空白')}</p><button data-pb-use-other="${path}">采用其他页内容</button><button data-pb-use-brief="${path}">采用填写包内容</button></div>`).join('')}</section>`:'')+
  `<section class="form-card"><h3>角色基本信息</h3><div class="field-row">${pbInput('author.characterName','角色名')}${pbInput('author.title','角色资料头衔')}${pbSelect('author.element','属性',['火','水','雷','风','光','暗'].map(x=>[x,x]))}${pbInput('author.role','职责 / 战斗定位')}${pbInput('author.race','种族')}</div>${pbInput('author.baseForm','进化前是什么样子')}${pbInput('author.evolvedForm','进化后如何变化（可写沿用基础形态）')}${[['characterName','角色名'],['title','头衔'],['role','定位'],['race','种族'],['baseForm','进化前'],['evolvedForm','进化后']].map(([key,label])=>pbIdentityPolicy(key,label)).join('')}${pbText('author.growth','成长与培养意图（可暂留空）','rows="2"')}${pbText('author.leaderPosition','作为队长希望有什么特点','rows="2"')}${pbText('author.memberPosition','作为队员希望有什么特点','rows="2"')}</section>`+
  `<section><h3>技能与能力意图</h3><p>先说明主动技能、强化弹射和队长技；没有完整方案也能写协助说明。六个能力槽按需填写。</p><div class="form-layout">${pbPlan('plans.activeSkill','主动技能',b.plans.activeSkill)}${pbPlan('plans.pf','强化弹射（PF）',b.plans.pf)}${pbPlan('plans.leader','队长技',b.plans.leader)}</div><div class="gameplay-abilities">${b.plans.abilities.map((plan,index)=>pbPlan('plans.abilities.'+index,'能力 '+plan.slot,plan)).join('')}</div></section>`+
  `<details class="production-section"><summary>图片与动作：选择文件或说明如何补充</summary><p>选择已有素材即可关联，不需要查找编号。母版可以派生多个小图；实际帧序请在像素动作页面制作。</p>${b.resources.map(pbResourceRow).join('')}</details>`+
  `<details class="production-section"><summary>语音与音效：文件、全文和用途</summary><section class="form-card"><h3>整体配音意图</h3>${pbSelect('authorPolicy.voiceMode','角色配音',[['unmarked','尚未确定'],['custom','提供自定义配音'],['none','无配音'],['reuse','复用已有配音']])}${pbText('authorPolicy.voiceReason','整体理由与协助需求','rows="2"')}${pbInput('authorPolicy.voiceReference','复用参考名称')}<p>无配音声明只覆盖未提供的角色语音；音效另行说明。</p></section><h3>角色语音</h3>${b.voices.map((item,index)=>pbAudioRow(item,index,'voices')).join('')}<h3>技能与战斗音效</h3>${b.sounds.map((item,index)=>pbAudioRow(item,index,'sounds')).join('')}</details>`+
  `<section class="form-card"><h3>交接说明</h3>${pbText('notes','希望制作方继续完成什么','rows="3"')}<p>交接文件包含当前文字、真实素材关联与待核范围。完整素材请同时导出工程；离线预览不代表游戏内验收。</p><button id="production-download">保存并下载制作交接</button><button id="production-project">导出包含素材的完整工程</button><button id="production-run-check">查看当前待办</button><div id="production-check-result"></div></section>`;
  for(const node of document.querySelectorAll('#content details'))if(opened.includes(node.querySelector('summary')?.textContent))node.open=true;
  bindProductionBrief();
}
function pbApplyAudioRecord(record,item,kind,editedField=''){
  const declaration=kind==='voices'&&typeof authorVoiceView==='function'?authorVoiceView(record):null;
  // Selecting a recording is not an edit of the confirmed script or usage.
  if(declaration?.d)for(const key of ['text','usage','entry'])record[key]=declaration[key];
  if(record.asset!==item.assetId){
    if(kind==='voices'&&typeof authorReplaceVoiceAsset==='function')authorReplaceVoiceAsset(record,item.assetId);
    else record.asset=item.assetId;
  }
  const field=editedField==='textJapanese'?'text':editedField;
  if(['text','entry'].includes(field)){
    const value=item[editedField]??'';
    if(kind==='voices'&&typeof authorSyncVoiceFields==='function')authorSyncVoiceFields(record,field,value);
    else record[field]=value;
  }
  if(kind==='voices'&&typeof syncVoiceDeclaration==='function')syncVoiceDeclaration(record,field||'asset');
  else {item.textJapanese=record.text??'';item.entry=record.entry??'';}
}
function pbAudioRecord(prefix,editedField=''){
  const item=pbPath(prefix),kind=prefix.split('.')[0];if(kind==='resources')return;
  const record=S.p[kind]?.find(row=>row.productionId===item.id);if(!record)return;
  pbApplyAudioRecord(record,item,kind,editedField);
}
function pbBindAssets(prefix,ids){
  const item=pbPath(prefix),kind=prefix.split('.')[0];
  if(kind==='resources'){
    item.assetIds=ids;if(['portrait_base','portrait_evolved'].includes(item.id)&&ids[0]){S.p.portraits??={};S.p.portraits[item.id==='portrait_base'?'base':'evolved']=ids[0];}
  }else {
    item.assetId=ids[0]||'';item.filename=S.p.assets[ids[0]]?.name||'';
    if(ids[0]){
      S.p[kind]??=[];let record=S.p[kind].find(row=>row.productionId===item.id);
      if(!record){
        const uses={acquisition:'join',home_base:'home',home_evolved:'home',skill:'skill_voice',pf:'power_flip',victory:'win',detail:'other',enhancement:'other',defeat:'battle',damage:'outhole',down:'outhole'};
        record={id:uid(),productionId:item.id,name:item.label,usage:uses[item.id]||item.usage,text:item.textJapanese??'',entry:item.entry??''};S.p[kind].push(record);
      }
      pbApplyAudioRecord(record,item,kind);
    }
  }
  item.status=ids.length?'provided':'missing';
}
function pbPickAssets(prefix){const kind=prefix.split('.')[0],item=pbPath(prefix),list=Object.values(S.p.assets).filter(a=>a.mime?.startsWith(kind==='resources'?'image/':'audio/')),selected=new Set(kind==='resources'?item.assetIds:(item.assetId?[item.assetId]:[]));modal(`<h2>选择${kind==='resources'?'图片':'声音'} · ${esc(item.label)}</h2><input id="pb-asset-search" type="search" placeholder="搜索文件名"><div id="pb-asset-options"></div><button id="pb-asset-confirm" class="primary">关联所选文件</button>`);const show=()=>{const query=$('#pb-asset-search').value.trim().toLowerCase();$('#pb-asset-options').innerHTML=list.filter(a=>a.name.toLowerCase().includes(query)).map(a=>`<label class="asset-choice"><input type="${kind==='resources'?'checkbox':'radio'}" name="pb-assets" value="${a.id}" ${selected.has(a.id)?'checked':''}>${pbAssetPreview(a.id,kind)}</label>`).join('')||'<p>没有匹配素材，可以关闭后选择上传。</p>';$$('#pb-asset-options input').forEach(input=>input.onchange=()=>{if(kind!=='resources')selected.clear();if(input.checked)selected.add(input.value);else selected.delete(input.value);});};$('#pb-asset-search').oninput=show;$('#pb-asset-confirm').onclick=()=>{if(!selected.size)return toast('请先选择文件',true);if(selected.size>100)return toast('每项最多关联100张图片，请按用途分组',true);$('#modal').close();mutate(()=>pbBindAssets(prefix,[...selected]));};show();}
function bindProductionBrief(){
  $$('[data-pb-path]').forEach(input=>input.onchange=()=>{const path=input.dataset.pbPath;mutate(()=>{pbAssign(path,input.value);pbSyncEdited(path,input.value);if(/^(voices|sounds)\.\d+\.(entry|textJapanese)$/.test(path))pbAudioRecord(path.split('.').slice(0,2).join('.'),path.split('.').at(-1));},false);pbRefreshFeedback();});
  const download=()=>busy('保存当前填写并准备交接',async()=>{await saveNow();location.href='/api/production-handoff?id='+encodeURIComponent(S.p.id);});
  $('#production-export').onclick=download;$('#production-download').onclick=download;$('#production-project').onclick=()=>$('#export').click();
  $$('[data-pb-pick]').forEach(button=>button.onclick=()=>pbPickAssets(button.dataset.pbPick));
  $$('[data-pb-upload]').forEach(button=>button.onclick=()=>{const prefix=button.dataset.pbUpload,kind=prefix.split('.')[0],item=pbPath(prefix),category=kind==='resources'?({portrait:'portrait',pixel:'pixel',skill:'effect',pf:'effect'}[item.group]||'image'):kind==='voices'?'voice':'sfx';upload(category,ids=>pbBindAssets(prefix,kind==='resources'?ids:ids.slice(0,1)),kind==='resources'?'image/png':'audio/wav,audio/mpeg,audio/ogg');});
  $$('[data-pb-unlink]').forEach(button=>button.onclick=()=>mutate(()=>{const prefix=button.dataset.pbUnlink,item=pbPath(prefix);if(prefix.startsWith('resources.'))item.assetIds=[];else item.assetId='';item.status='missing';}));
  $$('[data-pb-use-other]').forEach(button=>button.onclick=()=>pbSet(button.dataset.pbUseOther,pbMirror(button.dataset.pbUseOther).get()??''));
  $$('[data-pb-use-brief]').forEach(button=>button.onclick=()=>mutate(()=>pbSyncEdited(button.dataset.pbUseBrief,pbPath(button.dataset.pbUseBrief)??'')));
  $('#production-run-check').onclick=()=>busy('检查当前填写',async()=>{await saveNow();const result=await api('/api/check',{id:S.p.id});$('#production-check-result').innerHTML=result.issues.filter(item=>item.page==='production').map(item=>`<p>${esc(item.text)}</p>`).join('')||'<p>作者填写包没有待补提示；制作方接入仍需确认。</p>';});
}

function pbRefreshFeedback(){const summary=document.querySelector('.production-required-summary');if(summary)summary.outerHTML=pbSummary(S.p.productionBrief);for(const node of document.querySelectorAll('[data-pb-feedback]')){const item=pbPath(node.dataset.pbFeedback),kind=node.dataset.pbFeedbackKind,state=kind==='plan'?pbTextState(item.name?.trim()&&item.authorDescription?.trim(),item.authorPolicy):pbRowGuidance(item,kind);node.textContent=(state.authorComplete?'作者意图已说明':'可以补充内容，或说明希望协助的部分')+' · '+(state.makerPending?'制作方待确认':'接入与实际表现仍需核验')+'。说明不会制造素材或游戏验收结果。';}}

function pbFieldTitle(path){const fields={characterName:'角色名',title:'角色资料头衔',element:'属性',role:'战斗定位',race:'种族'},parts=path.split('.');if(parts[0]==='author')return fields[parts[1]]||'角色信息';const name=parts[1]==='abilities'?'能力 '+(Number(parts[2])+1):({activeSkill:'主动技能',pf:'强化弹射',leader:'队长技'}[parts[1]]||'玩法');return name+(parts.at(-1)==='name'?'名称':'说明');}
