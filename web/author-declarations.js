'use strict';
// Optional author intent. Rendering never migrates or confirms old data.
const authorUiUses=[
  ['square','方形头像','脸部特写，眼睛与发饰不要贴边。','none'],
  ['thumb_party_main','编队主位','头、胸、腰可见；例如保留手中武器，避免只剩脸。','rounded'],
  ['skill_cutin','技能插入图','宽幅半身动作；例如召唤物也要入镜，请禁止从母版自动裁切。','none'],
  ['battle_control_board','技能指引','竖向头胸构图；锥形会裁掉两侧，脸与武器留在中间。','cone'],
  ['cutin_skill_chain','技能连锁','脸部特写；六边形会裁掉角落，发饰不要贴到边缘。','hexagon']
];
const authorMasks=[['','未标注 · 请确认'],['auto','按官方用途自动遮罩'],['none','不加遮罩 / 使用原图形状'],['rounded','圆角矩形'],['cone','锥形 / 水滴形'],['hexagon','六边形'],['circle','圆形']];
const authorEntries=[['','未标注 · 请确认'],['ally','加入 / 进化（ally）'],['battle','战斗（battle）'],['home','主页（home）'],['login','登录（login）'],['words','剧情语料（words）']];
const authorOrigins=[['','未标注 · 请确认'],['reuse','复用现有特效'],['reskin','重皮 · 模板 + 配色 / 贴图'],['original','原创 · 四件套 / 骨架']];
const authorCompanionSlots=new Set(['skill_ready','special_land','special_pose']);
const authorBaseSlots=new Set(['neutral','walk_front','walk_back','kachidoki','into_coffin','ghost_raise','ghost_neutral','revive']);
function authorText(v){return typeof v==='string'?v:'';}
function authorObject(v){return !!v&&typeof v==='object'&&!Array.isArray(v);}
function authorMarked(v){return typeof v==='string'&&!!v.trim();}
function authorTri(v){return v===true?'true':v===false?'false':v==null||v===''?'':'__invalid__';}
function authorTriValue(v){return v==='true'?true:v==='false'?false:'';}
function authorFieldId(kind,key,field){return 'author-'+kind+'-'+encodeURIComponent(key)+'-'+field;}
function authorField(kind,key,field,label,value,{options=null,rows=0,placeholder='',max=500,reference=false}={}){
  const id=authorFieldId(kind,key,field),attr=`id="${esc(id)}" data-author-field="${esc(field)}"`;
  let control;
  if(options){const selected=value==null?'':value,known=options.some(([v])=>v===selected);control=`<select ${attr}>${!known?'<option value="__invalid__" selected>旧值需确认：'+esc(value)+'</option>':''}${options.map(([v,t])=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(t)}</option>`).join('')}</select>`;}
  else if(rows)control=`<textarea ${attr} rows="${rows}" maxlength="${max}" placeholder="${esc(placeholder)}">${esc(authorText(value))}</textarea>`;
  else control=`<input ${attr} type="text" maxlength="${max}" value="${esc(authorText(value))}" placeholder="${esc(placeholder)}">`;
  const invalid=!options&&value!=null&&typeof value!=='string';
  return `<div class="field author-field"><label for="${esc(id)}">${esc(label)}${reference?' <span class="author-reference">旧数据 / 模板参考 · 尚未确认</span>':''}</label>${control}${invalid?'<small class="author-warning">旧值类型无效；重新填写后才会替换，未自动转成文字。</small>':''}</div>`;
}
function authorTriField(kind,key,field,label,value,yes,no){
  const options=[['','未标注 · 请确认'],['true',yes],['false',no]],selected=authorTri(value);
  if(selected==='__invalid__')options.unshift(['__invalid__','旧值需确认：'+String(value)]);
  return authorField(kind,key,field,label,selected,{options});
}
function authorRow(kind,key,title,body,extra=''){
  return `<section class="author-declaration-row" data-author-kind="${esc(kind)}" data-author-key="${esc(key)}" tabindex="-1"><div class="author-row-head"><h4>${esc(title)}</h4>${extra}</div>${body}</section>`;
}
function authorAnimationSource(anim){
  const counts={plain:0,composite:0,unknown:0};let inferred=0;
  const clips=Array.isArray(anim.clips)?anim.clips:[];
  for(const clip of clips){
    if(!authorObject(clip))continue;
    const a=authorObject(S.p.assets)&&typeof clip.asset==='string'?S.p.assets[clip.asset]:null;
    let variant='unknown';
    if(authorObject(a)){
      const names=['name','file','sourceFile','sourceName','logical'].map(key=>a[key]).filter(name=>typeof name==='string'&&name.length>0);
      // Match studio_core.clip_variant: real companion filenames outrank editable labels.
      const composite=names.some(name=>{const stem=name.replace(/\.[^.]*$/s,'').toLowerCase();return ['_sp','_summon','_fx','_eff','_glow'].some(suffix=>stem.endsWith(suffix));});
      if(composite){variant='composite';if(a.variant!=='composite')inferred++;}
      else if(a.variant==='plain'||a.variant==='composite')variant=a.variant;
      else if(!['effect','ui','unknown'].includes(a.variant)&&names.length){variant='plain';inferred++;}
    }
    counts[variant]++;
  }
  const kind=counts.plain&&counts.composite?'mixed':counts.composite?'composite':counts.plain&&!counts.unknown?'plain':'unknown';
  return {kind,counts,inferred,label:({plain:'纯本体（plain）',composite:'合成帧（composite）',mixed:'混合（mixed）',unknown:'未识别 / 尚无画稿'})[kind]};
}
function authorAnimationBadge(anim){const v=authorAnimationSource(anim);return `<span class="author-source author-source-${v.kind}">来源：${esc(v.label)}</span>`;}
function authorAnimationRow(anim){
  const key=anim.id,source=authorAnimationSource(anim),preset=typeof pixelPresets!=='undefined'?pixelPresets.find(p=>p.slot===anim.slot):null;
  const suggested=!authorMarked(anim.purpose)&&typeof anim.purpose!=='number'?authorText(preset?.purpose):'',purpose=authorMarked(anim.purpose)?anim.purpose:suggested||anim.purpose;
  const required=authorCompanionSlots.has(anim.slot),flag=authorTri(anim.includesCompanion);
  const conflict=source.counts.composite&&flag==='false',baseRisk=source.counts.composite&&authorBaseSlots.has(anim.slot)&&(flag!=='true'||!authorMarked(anim.companionNote));
  let hint=required?'技能准备、获取登场和获取定格都要明确选“带 / 不带”，不能由画稿代替回答。':'例如：待机与移动只画本体；两只召唤物仅在释放技能时出现。';
  if(conflict||baseRisk)hint='所选画稿含合成帧。若确实带附属物，请选“带”并写明时机；若不带，请回动作页替换成纯本体帧。说明不会自动替换画稿。';
  const holds=(anim.clips||[]).map(c=>c.hold).join(' / '),play=({loop:'循环',once:'播放一次',pass:'衔接下一段',stop:'首帧停留'})[anim.kind]||'待确认';
  return authorRow('animation',key,anim.name||anim.slot||'未命名动作',
    `<p class="author-hint ${conflict||baseRisk?'author-warning':''}">${esc(hint)}</p><p class="author-source-detail">${esc(anim.slot||'自定义动作')} · ${esc((anim.clips||[]).length)} 段画稿 · ${esc(play)}${holds?' · 每段停留 '+esc(holds)+' tick':''}${source.inferred?' · 文件名推断仅供核对，不代表作者已确认':''}${source.counts.unknown?' · 有未识别来源，请核对画稿':''}</p>`+
    authorField('animation',key,'purpose','用途说明',purpose,{rows:2,placeholder:'例如：技能蓄满时举起法杖；从第 3 段开始召唤物入镜。',reference:!!suggested})+
    (suggested?`<button data-author-adopt-purpose="${esc(key)}" class="quiet">采用模板用途参考</button>`:'')+
    authorTriField('animation',key,'includesCompanion',required?'是否包含召唤物 / 附属物 · 请明确二选一':'是否包含召唤物 / 附属物',anim.includesCompanion,'带 · 有召唤物 / 附属物','不带 · 仅角色本体')+
    authorField('animation',key,'companionNote','附属物说明 / 出现时机',anim.companionNote,{rows:2,placeholder:'例如：仅技能准备第 3–8 段出现两只召唤物；获取演出不带。'}),authorAnimationBadge(anim));
}
function authorUiRow(form,slot){
  const key=form+':'+slot,decl=S.p.uiDeclarations?.[key],d=authorObject(decl)?decl:{},spec=S.p.uiImages?.[key],legacy=S.p.crops?.[key];
  const aid=spec?.asset||(legacy?S.p.portraits?.[form]:null)||S.p.uiSources?.[key],asset=S.p.assets?.[aid],use=authorUiUses.find(x=>x[0]===slot);
  const title=(form==='evolved'?'进化':'基础')+' · '+(use?.[1]||slots[slot]?.[0]||slot),current=spec?.mode==='crop'||legacy?'从母版裁剪':asset?'独立 / 模板图片':'未绑定图片，可先写说明';
  const oldNote=!authorMarked(d.note)&&authorMarked(spec?.note)?spec.note:'';
  return authorRow('ui',key,title,
    `<p class="author-hint">${esc(use?.[2]||'写清需要保留的构图内容，避免重要部分被遮罩裁掉。')}</p><p class="author-source-detail">${esc(current)}${asset?' · '+esc(asset.name):''}${spec?.mask?' · 现有遮罩 '+esc(spec.mask)+'（仅当前设置，不等于作者声明）':''}</p>`+
    (decl!=null&&!authorObject(decl)?'<p class="author-warning">旧用途说明不是有效记录；编辑字段后将重新建立此条说明。</p>':'')+
    authorTriField('ui',key,'autoCrop','允许从母版自动裁切？',d.autoCrop,'允许 · 可从母版自动裁切','禁止 · 请使用独立替换图')+
    authorField('ui',key,'mask','形状遮罩意图',d.mask,{options:authorMasks})+
    authorField('ui',key,'note','取景 / 遮罩补充',oldNote||d.note,{rows:2,max:2000,reference:!!oldNote,placeholder:'例如：召唤物必须完整入镜，禁止母版自动裁切；沿用官方锥形，脸居中。'})+
    `<button data-author-edit-ui="${esc(key)}" class="quiet">去选图 / 调整构图 →</button>`);
}
function authorEffectRow(effect){return authorRow('effect',effect.id,effect.name||'未命名特效',
  '<p class="author-hint">复用写角色和特效；重皮写模板与配色；原创写贴图、图集、parts、timeline 四件套或骨架。只有概念图时请说明“仅作参考”。</p>'+
  authorField('effect',effect.id,'origin','特效来源',effect.origin,{options:authorOrigins})+
  authorField('effect',effect.id,'originNote','来源 / 改动说明',effect.originNote,{rows:2,placeholder:'例如：复用凉月召唤特效，仅把主色改为紫色；动作与时序不变。'})+
  `<button data-author-edit-effect="${esc(effect.id)}" class="quiet">去查看 / 编辑特效 →</button>`);}
function authorPath(v){return authorText(v).replaceAll('\\','/').replace(/^\.\//,'');}
function authorVoiceAliases(v){const a=S.p.assets?.[v.asset]||{};return new Set([v.id,v.asset,v.sourceFile,v.logical,v.name,a.name,a.file].filter(authorMarked).map(authorPath));}
function authorVoiceMatches(v){
  const aliases=authorVoiceAliases(v),voices=Array.isArray(S.p.voices)?S.p.voices:[];
  return (Array.isArray(S.p.voiceDeclarations)?S.p.voiceDeclarations:[]).map((d,index)=>({d,index})).filter(({d})=>{
    if(!authorObject(d))return false;const refs=[d.id,d.asset,d.file].filter(authorMarked).map(authorPath);
    if(!refs.length||!refs.every(r=>aliases.has(r)))return false;
    return voices.filter(x=>refs.every(r=>authorVoiceAliases(x).has(r))).length===1;
  });
}
function authorVoiceView(v,d=null){
  const matches=authorVoiceMatches(v);d=d||matches[0]?.d;const asset=S.p.assets?.[v.asset]||{};
  const usage=authorMarked(d?.usage)?d.usage:authorText(v.usage),text=authorMarked(d?.text)?d.text:authorText(v.text);
  let suggested='';for(const path of [v.sourceFile,v.logical,asset.name]){const parts=authorPath(path).split('/');if(parts[0]==='voice')parts.shift();if(authorEntries.some(([e])=>e&&e===parts[0])){suggested=parts[0];break;}}
  suggested=suggested||({join:'ally',evolution:'ally',home:'home',login:'login',story_words:'words',battle_start:'battle',skill_voice:'battle',skill_ready:'battle',power_flip:'battle',attack:'battle',outhole:'battle',win:'battle',battle:'battle'})[usage]||'';
  const conflicts=['usage','text'].filter(k=>authorMarked(d?.[k])&&authorMarked(v[k])&&d[k]!==v[k]);
  return {v,d,matches,usage,text,entry:d?.entry??'',reused:d?.reused??'',suggested,conflicts};
}
function authorVoiceRows(){
  const result=[],used=new Set();
  for(const v of S.p.voices||[]){const view=authorVoiceView(v);for(const m of view.matches)used.add(m.index);result.push({...view,key:'voice:'+v.id});
    for(const m of view.matches.slice(1))result.push({...authorVoiceView(v,m.d),key:'declaration:'+m.index,index:m.index,duplicate:true});}
  for(const [index,d] of (Array.isArray(S.p.voiceDeclarations)?S.p.voiceDeclarations:[]).entries())if(authorObject(d)&&!used.has(index))result.push({key:'declaration:'+index,index,d,v:null,matches:[],usage:d.usage??'',text:d.text??'',entry:d.entry??'',reused:d.reused??'',suggested:'',conflicts:[]});
  return result;
}
function authorVoiceExtras(v){
  const view=authorVoiceView(v),key='voice:'+v.id;
  return `<div class="author-voice-extras" data-author-kind="voice" data-author-key="${esc(key)}">`+authorVoiceEntryFields(view,key)+
    (view.conflicts.length?'<p class="author-warning">旧语音表与声音记录不一致；此处按语音表预填。修改台词 / 用途或点击确认后，两处将统一。</p><button data-author-sync-voice="'+esc(key)+'">确认采用此处台词与用途</button>':'')+'</div>';
}
function authorVoiceEntryFields(view,key){return '<div class="author-two-fields">'+
  authorField('voice',key,'entry','语音入口',view.entry,{options:authorEntries})+
  authorTriField('voice',key,'reused','是否复用模板语音？',view.reused,'复用 · 沿用已有录音','不复用 · 新录音 / 替换录音')+'</div>'+
  (!authorMarked(view.entry)&&view.suggested?`<p class="author-reference">文件路径 / 用途参考：${esc(view.suggested)}，尚未确认。<button data-author-adopt-entry="${esc(key)}">采用入口参考</button></p>`:'');}
function authorVoiceRow(view){
  const {key,v,d}=view,asset=S.p.assets?.[v?.asset||d?.asset],file=v?.sourceFile||asset?.name||d?.file||v?.name||'尚未填写文件';
  return authorRow('voice',key,file,
    (view.duplicate?'<p class="author-warning">同一条声音存在重复登记。确认内容后撤回多余说明，避免接收者看到两套台词。</p>':'')+
    (view.conflicts.length?'<p class="author-warning">旧语音表与声音记录的用途 / 台词不一致。按语音表预填；修改任一说明或确认后，会同步两处台词与用途。</p>':'')+
    (!v?'<p class="author-hint">尚未匹配到声音记录。请填写准确文件路径，或选择工程中的录音；不需要重复导入。</p>':'')+
    (!v?authorField('voice',key,'asset','绑定工程中的录音',d?.asset,{options:[['','使用下方文件路径'],...Object.entries(S.p.assets||{}).filter(([,a])=>a.mime?.startsWith('audio/')).map(([id,a])=>[id,a.name||id])]})+authorField('voice',key,'file','文件路径',d?.file,{max:500,placeholder:'例如：voice/ally/join.mp3'}):`<p class="author-source-detail">${esc(v.name||'录音')} · 已绑定 ${esc(asset?.name||v.asset)}</p>`)+
    authorVoiceEntryFields(view,key)+
    authorField('voice',key,'usage','用途（与声音列表共用）',view.usage,{max:500,placeholder:'例如：join（加入）、skill_voice（技能喊声）、home（主页问候）'})+
    authorField('voice',key,'text','台词文字（与声音列表共用）',view.text,{rows:3,max:2000,reference:!!v&&!d,placeholder:'完整台词；没有文字时请明确写“暂无台词”。'})+
    (view.conflicts.length?`<button data-author-sync-voice="${esc(key)}">确认采用此处台词与用途</button>`:'')+
    (view.index!=null?`<button data-author-remove-voice="${esc(key)}" class="quiet">撤回此条说明（不删除录音）</button>`:''));
}
function authorNotesRow(){const old=!authorMarked(S.p.authorNotes)&&authorMarked(S.p.notes)?S.p.notes:'';return authorRow('notes','project','整体素材说明',
  '<p class="author-hint">例如：基础与进化共用像素动作；UI 技能插入图单独绘制；其余语音复用模板。写清哪些新画、哪些沿用、哪些仍待补齐。</p>'+
  authorField('notes','project','authorNotes','给接收者的整体说明',old||S.p.authorNotes,{rows:4,max:12000,reference:!!old,placeholder:'例如：新增两张立绘；技能特效沿用模板但改紫色；召唤物只在技能与获取演出出现。'})+
  (old?'<button data-author-adopt-notes class="quiet">采用已有工程备注</button>':''));}
function authorGroup(kind,title,rows,empty=''){return `<details class="author-declaration-group" data-author-group="${esc(kind)}"><summary>${esc(title)} <span>${rows.length} 项</span></summary><div class="author-group-body">${rows.join('')||'<p class="author-hint">'+esc(empty)+'</p>'}</div></details>`;}
function authorDeclarationsPanel(){
  if(!S.p)return '';const voices=authorVoiceRows();
  return '<section class="author-declarations" aria-label="素材说明"><div class="author-panel-head"><div><h3>素材说明</h3><p>直接说明每张画稿、特效和录音怎么用，不用编辑 JSON。</p></div><button data-author-expand>展开全部说明</button></div><p class="author-panel-intro">“未标注”不等于“不带 / 不允许”。旧数据和文件名只作参考，不会自动变成你的确认。说明随工程保存；补齐后重新检查。</p>'+
    authorGroup('animation','动作与附属物',(S.p.animations||[]).map(authorAnimationRow),'尚无动作，请先在“像素动作”添加。')+
    authorGroup('ui','五类重点界面图', ['base','evolved'].flatMap(form=>authorUiUses.map(([slot])=>authorUiRow(form,slot))))+
    authorGroup('effect','技能特效来源',(S.p.effects||[]).map(authorEffectRow),'尚无特效；如果沿用某角色的特效，请先载入对应模板。')+
    authorGroup('voice','语音对照',voices.map(authorVoiceRow).concat('<button data-author-add-voice>＋ 登记一条语音说明</button>'))+
    authorGroup('notes','整体备注',[authorNotesRow()])+'</section>';
}
function renderAuthorDeclarations(container=$('#author-declarations-mount')){if(!container)return false;container.innerHTML=authorDeclarationsPanel();wireAuthorDeclarations(container);return true;}
function authorRefreshContainer(container,key=''){
  const open=[...container.querySelectorAll('[data-author-group][open]')].map(e=>e.dataset.authorGroup),top=window.scrollY;
  renderAuthorDeclarations(container);for(const group of container.querySelectorAll('[data-author-group]'))group.open=open.includes(group.dataset.authorGroup);
  if(key)focusAuthorDeclaration({kind:'voice',id:key},container);else window.scrollTo({top});
}
function authorCurrentVoice(key){return authorVoiceRows().find(v=>v.key===key);}
function authorSetVoice(view,field,value){
  if(!view)return;let d=view.d;
  if(!d){S.p.voiceDeclarations??=[];d={asset:view.v.asset,entry:'',usage:'',text:'',reused:''};S.p.voiceDeclarations.push(d);}
  const usage=field==='usage'?value:authorText(view.usage),text=field==='text'?value:authorText(view.text);
  d.usage=usage;d.text=text;if(field)d[field]=value;
  if(view.v){view.v.usage=usage;view.v.text=text;for(const m of view.matches){m.d.usage=usage;m.d.text=text;}}
  // An asset reference alone is unambiguous; never leave an old mismatching file path.
  if(field==='asset'&&value){delete d.file;delete d.id;}
}
function authorSyncVoiceFields(v,key,value){const view=authorVoiceView(v);v[key]=value;for(const m of view.matches)m.d[key]=value;}
function authorReplaceVoiceAsset(v,newAsset){const matches=authorVoiceMatches(v);v.asset=newAsset;for(const {d} of matches){d.asset=newAsset;if(d.file)d.file=authorText(S.p.assets?.[newAsset]?.name);}}
function authorRemoveVoiceDeclarations(v){const remove=new Set(authorVoiceMatches(v).map(m=>m.index));if(Array.isArray(S.p.voiceDeclarations))S.p.voiceDeclarations=S.p.voiceDeclarations.filter((d,i)=>!remove.has(i));}
function authorSetField(kind,key,field,value){
  if(kind==='animation'||kind==='effect'){const item=S.p[kind==='animation'?'animations':'effects'].find(a=>a.id===key);if(item)item[field]=value;}
  else if(kind==='ui'){if(S.p.uiDeclarations!=null&&!authorObject(S.p.uiDeclarations))throw Error('旧用途说明表格式无效，请先处理检查中对应的格式问题。');S.p.uiDeclarations??={};if(!authorObject(S.p.uiDeclarations[key]))S.p.uiDeclarations[key]={autoCrop:'',mask:'',note:''};S.p.uiDeclarations[key][field]=value;}
  else if(kind==='voice')authorSetVoice(authorCurrentVoice(key),field,value);
  else if(kind==='notes')S.p.authorNotes=value;
}
function wireAuthorDeclarations(container=$('#content')){
  if(!container)return;
  for(const input of container.querySelectorAll('[data-author-field]'))input.onchange=()=>{
    if(input.value==='__invalid__')return;const row=input.closest('[data-author-kind]');
    const field=input.dataset.authorField,tri=['includesCompanion','autoCrop','reused'].includes(field),value=tri?authorTriValue(input.value):input.value;
    try{mutate(()=>authorSetField(row.dataset.authorKind,row.dataset.authorKey,field,value),false);authorSyncVisibleFields(container,row.dataset.authorKind,row.dataset.authorKey,field);}catch(e){toast(e.message,true);}
  };
  for(const b of container.querySelectorAll('[data-author-adopt-purpose]'))b.onclick=()=>{const row=b.closest('[data-author-kind]'),input=row.querySelector('[data-author-field="purpose"]');mutate(()=>authorSetField('animation',row.dataset.authorKey,'purpose',input.value),false);b.remove();row.querySelector('.author-reference')?.remove();};
  for(const b of container.querySelectorAll('[data-author-adopt-entry]'))b.onclick=()=>{const view=authorCurrentVoice(b.dataset.authorAdoptEntry)||authorVoiceView((S.p.voices||[]).find(v=>'voice:'+v.id===b.dataset.authorAdoptEntry));if(view?.suggested){mutate(()=>authorSetVoice(view,'entry',view.suggested),false);const input=b.closest('[data-author-kind]').querySelector('[data-author-field="entry"]');input.value=view.suggested;b.parentElement.remove();}};
  for(const b of container.querySelectorAll('[data-author-sync-voice]'))b.onclick=()=>{mutate(()=>authorSetVoice(authorCurrentVoice(b.dataset.authorSyncVoice),'',null),false);const warning=b.previousElementSibling;if(warning?.classList.contains('author-warning'))warning.remove();b.remove();};
  for(const b of container.querySelectorAll('[data-author-adopt-notes]'))b.onclick=()=>{mutate(()=>S.p.authorNotes=authorText(S.p.notes),false);b.remove();container.querySelector('[data-author-kind="notes"] .author-reference')?.remove();};
  for(const b of container.querySelectorAll('[data-author-edit-ui]'))b.onclick=()=>{[S.form,S.slot]=b.dataset.authorEditUi.split(':');S.page='portraits';render();};
  for(const b of container.querySelectorAll('[data-author-edit-effect]'))b.onclick=()=>{S.page='effects';S.selected=b.dataset.authorEditEffect;render();};
  for(const b of container.querySelectorAll('[data-author-add-voice]'))b.onclick=()=>{if(S.p.voiceDeclarations!=null&&!Array.isArray(S.p.voiceDeclarations))return toast('旧语音说明表格式无效，请先处理对应格式问题。',true);let key;mutate(()=>{S.p.voiceDeclarations??=[];key='declaration:'+S.p.voiceDeclarations.length;S.p.voiceDeclarations.push({file:'',entry:'',usage:'',text:'',reused:''});},false);authorRefreshContainer(container,key);};
  for(const b of container.querySelectorAll('[data-author-remove-voice]'))b.onclick=()=>{const view=authorCurrentVoice(b.dataset.authorRemoveVoice);if(view?.index==null)return;mutate(()=>S.p.voiceDeclarations.splice(view.index,1),false);authorRefreshContainer(container);};
  for(const b of container.querySelectorAll('[data-author-expand]'))b.onclick=()=>{const groups=[...container.querySelectorAll('[data-author-group]')],expand=groups.some(g=>!g.open);groups.forEach(g=>g.open=expand);b.textContent=expand?'收起全部说明':'展开全部说明';};
}
function authorSyncVisibleFields(container,kind,key,field){
  const rows=[...container.querySelectorAll('[data-author-kind]')].filter(row=>row.dataset.authorKind===kind&&row.dataset.authorKey===key);
  if(kind==='voice'){const view=authorCurrentVoice(key);if(view?.v){for(const input of container.querySelectorAll('[data-audio-text]'))if(input.dataset.audioText===view.v.id)input.value=view.text;for(const input of container.querySelectorAll('[data-audio-usage]'))if(input.dataset.audioUsage===view.v.id)input.value=view.usage;}}
  if(field==='purpose'||field==='authorNotes')for(const row of rows)row.querySelector('.author-reference')?.remove();
}
function authorIssueTarget(issue={}){
  if(typeof issue==='string')issue={id:issue};const code=authorText(issue.code),location=authorText(issue.location||issue.position),page=issue.page;let kind=issue.kind||issue.declarationKind,id=authorText(issue.id||issue.key);
  if(!kind)kind=/^ui_|uiDeclarations|uiImages|crops/.test(code+' '+location)||page==='portraits'?'ui':/^voice_|voices|voiceDeclarations/.test(code+' '+location)||page==='voices'?'voice':/^effect_|effects/.test(code+' '+location)||page==='effects'?'effect':/authorNotes/.test(location)||page==='identity'?'notes':'animation';
  if(kind==='ui'){id=issue.form&&issue.slot?issue.form+':'+issue.slot:id;const found=location.match(/(?:base|evolved):[a-z_0-9]+/);if(!id&&found)id=found[0];}
  if(kind==='voice'&&!id.startsWith('voice:')&&!id.startsWith('declaration:')){
    const views=authorVoiceRows(),view=views.find(v=>v.v&&(v.v.id===id||v.v.asset===id))||views.find(v=>v.d&&(v.d.asset===id||v.d.file===id));
    if(view)id=view.key;else{const m=location.match(/voiceDeclarations\[(\d+)\]/);if(m)id='declaration:'+m[1];}
  }
  if(kind==='animation'||kind==='effect'){
    const list=S.p[kind==='animation'?'animations':'effects']||[],item=list.find(a=>a.id===id||a.slot===id)||list.find(a=>(a.clips||[]).some(c=>c.asset===id));
    if(item)id=item.id;else{const m=location.match(/(?:animations|effects)\[(\d+)\]/);if(m)id=list[Number(m[1])]?.id||id;}
  }
  if(kind==='notes')id='project';return {kind,id,field:issue.field||(location.split('.').pop())};
}
function focusAuthorDeclaration(issue,container=$('#author-declarations-mount')||$('#content')){
  if(!container||!S.p)return false;const target=authorIssueTarget(issue),rows=[...container.querySelectorAll('[data-author-kind]')],row=rows.find(r=>r.dataset.authorKind===target.kind&&r.dataset.authorKey===target.id);
  const group=container.querySelector('[data-author-group="'+target.kind+'"]');if(group)group.open=true;
  if(!row){if(group){group.scrollIntoView({block:'center'});group.querySelector('summary')?.focus();}return false;}
  for(let p=row.parentElement;p&&p!==container;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
  container.querySelectorAll('.author-focus').forEach(e=>e.classList.remove('author-focus'));row.classList.add('author-focus');row.scrollIntoView({block:'center'});
  const input=[...row.querySelectorAll('[data-author-field]')].find(e=>e.dataset.authorField===target.field)||row.querySelector('[data-author-field]');(input||row).focus({preventScroll:true});return true;
}
function openAuthorDeclarationIssue(issue){const container=$('#author-declarations-mount');if(!container)return false;if(!container.querySelector('.author-declarations'))renderAuthorDeclarations(container);return focusAuthorDeclaration(issue,container);}
