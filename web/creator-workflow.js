'use strict';

// Author actions share the existing project and save/undo pipeline. Internal
// resource identities and imported implementation records stay untouched.
function creatorSync(path,value){
  const p=S.p,b=p.productionBrief;
  if(!b)return;
  const identities={name:'characterName',title:'title',element:'element',race:'race',role:'role'};
  if(path==='name')b.author.characterName=value;
  else if(path.startsWith('identity.')){const key=path.slice(9);if(identities[key])b.author[identities[key]]=value;}
  else if(path.startsWith('skill.')){const key=path.slice(6),target=key==='description'?'authorDescription':key;b.plans.activeSkill[target]=value;if(p.gameplay)p.gameplay.skill[key]=value;}
}
function creatorNavigate(page,id=null){stop();S.page=page;S.selected=id;S.tick=0;render();}
function downloadStudioReport(name,value){
  const blob=new Blob([typeof value==='string'?value:JSON.stringify(value,null,2)],{type:typeof value==='string'?'text/plain;charset=utf-8':'application/json'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function creatorRows(rows,empty='暂时没有这类问题'){
  return rows?.length?`<ul class="creator-report-list">${rows.slice(0,100).map(row=>`<li><strong>${esc(row.label||row.logical||row.file||row.source||row.domain||'待核项目')}</strong><p>${esc(row.reason||row.text||'需要接入方确认')}</p></li>`).join('')}</ul>${rows.length>100?`<p>另有 ${rows.length-100} 项，完整记录随报告保留。</p>`:''}`:`<p>${esc(empty)}</p>`;
}
function renderCreatorGuide(){
  const p=S.p,b=p.productionBrief,assets=Object.values(p.assets),plans=b?.plans||{};
  const cards=[
    ['identity','角色是谁','名字、人物设定、署名和素材使用许可。',p.name||'尚未命名'],
    ['portraits','角色长什么样','上传立绘，在画面中调整裁切；已有图片可以复用。',`${assets.filter(a=>a.mime==='image/png').length} 张图片已收到`],
    ['animations','角色怎样动','选择动作、导入帧图、调整位置和播放速度。',`${p.animations.filter(a=>a.clips?.length||a.nativeFrames?.length).length} 个动作有画稿`],
    ['gameplay','角色能做什么','用中文选择触发、目标与效果，或详细描述想法。',plans.activeSkill?.authorDescription?'已有技能说明':'可以先写想法'],
    ['effects','技能怎样表现','把动作、特效和声音放进时间轴，播放检查。',`${p.effects.length} 个特效 · ${p.scene.tracks.length} 条预览内容`],
    ['voices','角色说什么','选择声音用途、试听录音、保留完整台词。',`${p.voices.length} 条声音记录`],
    ['production','缺项怎样处理','逐项选择提供、复用或请协助，并说明具体情况。','没有现成素材也可以交接'],
    ['checks','保存并交接','查看可读的待处理清单，导出可继续编辑的工程。','接收者能继续完善']
  ];
  $('#content').innerHTML=header('从这里开始制作角色','不需要填写代码。按手头的素材先做能做的部分，随时保存。')+`<section class="form-card"><h3>有原稿包或参考工程</h3><p>原稿 ZIP 在“角色设定”接收；可编辑角色工程在首页打开。原始文件会保留，选择素材后才用于制作。</p><p>无法提供图片、录音或玩法细节时，在“缺项怎样处理”中说明原因、参考和希望获得的协助。</p></section><div class="creator-step-grid">${cards.map(([page,title,description,status],i)=>`<button class="creator-step" data-creator-go="${page}"><span class="tag">${i+1}</span><h3>${title}</h3><p>${description}</p><small>${esc(status)}</small></button>`).join('')}</div><p class="hint">工坊保存设定、素材和可播放预览。游戏里的伤害、条件及资源接入仍要由接入方核验，未验证的项目会留在交接清单里。</p>`;
  $$('[data-creator-go]').forEach(button=>button.onclick=()=>creatorNavigate(button.dataset.creatorGo));
}

const CREATOR_TRIGGERS=[['skill','使用技能时'],['always','持续生效'],['battle_start','战斗开始时'],['hit','命中敌人时'],['damage','受到伤害时'],['power_flip','发动强化弹射时'],['custom','其他情况（在说明中写清）']];
const CREATOR_TARGETS=[['self','自己'],['party','全队'],['element_party','同属性队友（不含自己）'],['battle_combo','本次战斗连击'],['enemy','目标敌人'],['custom','其他目标（在说明中写清）']];
const CREATOR_EFFECTS=[['attack_up','攻击力提高'],['skill_damage_up','技能伤害提高'],['direct_damage_up','直接攻击伤害提高'],['power_flip_up','强化弹射伤害提高'],['heal','恢复生命'],['skill_gauge_up','增加技能槽'],['combo_add','增加连击数'],['damage','造成伤害'],['custom','其他效果（在说明中写清）']];
const CREATOR_CONDITIONS=[['none','不加此条件'],['hp_at_least','自身游戏判定生命比例至少'],['hp_at_most','自身游戏判定生命比例至多'],['combo_at_least','当前连击数至少'],['combo_at_most','当前连击数至多'],['has_barrier','自己已有屏障']];
const CREATOR_DETAILS=[['unmarked','使用上面的普通卡片'],['active_skill','复杂主动技能'],['special','特殊能力或形态变化'],['summon','召唤物或跟随物'],['skill_reuse','复用或再次施放技能'],['damage','特殊伤害'],['custom','其他特殊机制']];
const CREATOR_DETAIL_FIELDS={reference:'已有角色、技能或素材参考',targets:'作用目标与范围',sequence:'动作、命中、特效与声音的先后时点',damage:'伤害类别、计算基准和段数',repeat:'冷却、次数、重复触发、打断与结束方式',appearance:'外观与动作素材',count:'同时存在数量与重复召唤规则',lifetime:'存活多久、怎样退场、是否跨阶段保留',behavior:'怎样移动、碰撞和攻击',element:'伤害属性与耐性规则',recovery:'结束、被打断和切换阶段时怎样恢复'};
const CREATOR_DETAIL_SCOPE={active_skill:['reference','targets','sequence','damage','repeat'],special:['reference','appearance','sequence','behavior','recovery','repeat'],summon:['reference','appearance','count','lifetime','behavior','sequence'],skill_reuse:['reference','targets','repeat','sequence'],damage:['damage','targets','element','sequence'],custom:['reference','behavior','sequence','repeat']};
async function openCreatorReuseReference(planKey){
  await saveNow();const pid=S.p.id,revision=S.p.revision,result=await api('/api/author-reuse-options',{id:pid}),options=result.options||[];
  modal(`<h2>选择工程已有参考</h2><p>可以先看动作、特效或试听声音，再选择制作参考。这里只记录复用意图，原技能、原稿和声音保留；游戏行为仍由制作方核对。</p>${field('按名称查找','creator-reuse-search','')}<div id="creator-reuse-options">${options.map((item,index)=>`<section class="notice" data-reuse-option="${index}"><strong>${esc(item.label)}</strong><p>${item.kind==='skill'?'已有技能版本':item.kind==='animation'?'已有角色动作':item.kind==='effect'?'已有特效':item.kind==='sound'?'已有声音':'已有制作参考'}</p><div class="reference-choice-actions"><button data-reuse-preview="${index}">${item.kind==='sound'?'试听这个声音':'查看预览'}</button><button data-reuse-choose="${index}">选择这个参考</button></div></section>`).join('')||'<p>尚未找到可选参考。可以先填写希望复用的角色或表现，并申请协助。</p>'}</div>`);
  $('#creator-reuse-search').oninput=()=>{const query=$('#creator-reuse-search').value.trim().toLocaleLowerCase();$$('[data-reuse-option]').forEach(node=>node.hidden=!options[Number(node.dataset.reuseOption)].label.toLocaleLowerCase().includes(query));};
  const choose=async(option)=>{
    if(S.p.id!==pid||S.p.revision!==revision)throw Error('工程已更新，请重新选择复用参考');
    const plans=S.p.productionBrief.plans,plan=planKey.startsWith('ability')?plans.abilities[Number(planKey.slice(7))]:plans[planKey];
    mutate(()=>{const details=plan.authorCardDraft?.details||{};plan.authorCardDraft={...(plan.authorCardDraft||{}),details:{...details,mechanic:details.mechanic&&details.mechanic!=='unmarked'?details.mechanic:planKey==='activeSkill'?'active_skill':'custom',reference:details.reference||option.label,referenceChoice:option.id,referenceDigest:option.identity.sha256}};},false);
    await saveNow();$('#modal').close();renderCreatorGameplay();toast('参考已记入方案；原素材保留，接入仍待核');
  };
  $$('[data-reuse-choose]').forEach(button=>button.onclick=()=>busy('保存所选复用参考',()=>choose(options[Number(button.dataset.reuseChoose)])));
  $$('[data-reuse-preview]').forEach(button=>button.onclick=()=>busy('读取所选参考的原始声画',()=>{
    const option=options[Number(button.dataset.reusePreview)];
    return openReferencePreview(option,pid,revision,{choose:()=>choose(option),back:()=>openCreatorReuseReference(planKey)});
  }));
}

function creatorMechanicSentence(details,ordinary){
  if(!details)return ordinary;
  const title=CREATOR_DETAILS.find(([key])=>key===details.mechanic)?.[1]||'特殊机制';
  const provided=(CREATOR_DETAIL_SCOPE[details.mechanic]||[]).filter(key=>typeof details[key]==='string'&&details[key].trim()).map(key=>`${CREATOR_DETAIL_FIELDS[key]}：${details[key].trim()}`);
  return `${title}：${provided.join('；')||'具体要求待补充或申请协助'}。`;
}

function renderCreatorGameplay(){
  const b=S.p.productionBrief,plans=b.plans;
  const entries=[['activeSkill','主动技能'],['leader','队长技能'],['pf','强化弹射'],...plans.abilities.map((row,i)=>['ability'+i,'能力 '+row.slot])];
  const key=S.creatorPlan&&entries.some(([k])=>k===S.creatorPlan)?S.creatorPlan:'activeSkill';S.creatorPlan=key;
  const plan=key.startsWith('ability')?plans.abilities[Number(key.slice(7))]:plans[key],label=entries.find(([k])=>k===key)[1],draft=plan.authorCardDraft||{};
  $('#content').innerHTML=header('技能与能力','先做清楚的玩法方案；已有角色定义时还能用可视化词条编辑实际条目。')+`<div class="creator-plan-tabs">${entries.map(([k,l])=>`<button data-creator-plan="${k}" class="${key===k?'primary':''}">${l}</button>`).join('')}</div><section class="form-card"><h3>${label} · 中文方案</h3>${field('名称（可以之后再定）','creator-plan-name',plan.name)}${textField('想要的行为和特别要求','creator-plan-description',plan.authorDescription)}<p>可以直接写想法，也可以用下面的卡片组成一句说明。卡片不会修改已有游戏条目。</p><div class="field-row">${selectField('什么时候发生','creator-trigger','skill',CREATOR_TRIGGERS)}${selectField('影响谁','creator-target','self',CREATOR_TARGETS)}</div>${selectField('产生什么效果','creator-effect','attack_up',CREATOR_EFFECTS)}${selectField('重复触发时怎样处理','creator-stacking','unmarked',[['unmarked','尚未确定，先请协助'],['single','只保留一层（不叠加）']])}<div id="creator-heal-basis-wrap">${selectField('治疗按什么计算','creator-heal-basis','unmarked',[['unmarked','尚未确定，先请协助'],['maximum_hp','按目标的最大生命值比例']])}</div><label class="check-row"><input type="checkbox" id="creator-main-only">这条能力仅在主位生效</label><div class="field-row">${field('数值（例如 20% 或 2倍；可留空）','creator-amount','')}${field('持续多久（例如 10秒；可留空）','creator-time','')}</div><button id="creator-compose" class="primary">把这张卡片加入说明</button><p id="creator-composition-preview" class="hint">用中文填写，不需要输入脚本。特殊机制请在上面的说明里描述。</p>${textField('暂时无法确定或提供的部分（写明情况、参考和希望的协助）','creator-plan-help',plan.authorPolicy?.reason||'')}<button id="creator-request-help">保存为待协助方案</button><p class="hint">这里记录作者的要求，游戏行为由接入方实现并验证。已有定义和未改动的技术字段会保留。</p></section><section class="form-card"><h3>已有玩法参考</h3><p>可从参考工程继续编辑真实词条；缺少参考素材包时仍可保存上面的方案。</p><button id="creator-reference">选择参考角色玩法</button>${S.p.nativeGameplay?'<button id="creator-native-data">编辑已有词条</button>':''}</section>`;
  $$('[data-creator-plan]').forEach(button=>button.onclick=()=>{S.creatorPlan=button.dataset.creatorPlan;renderCreatorGameplay();});
  const sync=(field,value)=>{plan[field]=value;if(typeof pbSyncEdited==='function')pbSyncEdited(`plans.${key.startsWith('ability')?'abilities.'+Number(key.slice(7)):key}.${field}`,value);else if(key==='activeSkill'){S.p.skill[field==='name'?'name':'description']=value;if(S.p.gameplay?.skill)S.p.gameplay.skill[field==='name'?'name':'description']=value;}};
  bindValue('#creator-plan-name',value=>sync('name',value));bindValue('#creator-plan-description',value=>sync('authorDescription',value));
  for(const [id,key] of [['trigger','trigger'],['target','target'],['effect','effect'],['amount','amount'],['time','duration'],['stacking','stacking'],['heal-basis','healBasis']]){if(draft[key]!==undefined)$('#creator-'+id).value=draft[key];bindValue('#creator-'+id,value=>{plan.authorCardDraft={...(plan.authorCardDraft||{}),[key]:value};});}
  $('#creator-main-only').checked=draft.mainOnly===true;
  $('#creator-main-only').closest('label').insertAdjacentHTML('beforebegin',`<details class="form-card" id="creator-conditions"><summary>附加条件（可选）</summary><p>在发动时检查下面的条件，全部满足才发动。生命比例请填百分比（沿用游戏生命判定，含已有的生命比例修正），连击数请填整数，已有屏障不用数值。发动后的增益不会因条件变化自动撤销；需要其他规则时写在方案里。</p>${[0,1].map(index=>`<div class="field-row">${selectField('条件 '+(index+1),'creator-condition-'+index,'none',CREATOR_CONDITIONS)}${field('条件数值（例如 80% 或 20）','creator-condition-value-'+index,'')}</div>`).join('')}</details>`);
  const currentConditions=()=>[0,1].map(index=>({kind:$('#creator-condition-'+index).value,value:$('#creator-condition-'+index).value==='has_barrier'?'':$('#creator-condition-value-'+index).value.trim()})).filter(condition=>condition.kind!=='none');
  for(const index of [0,1]){
    const condition=draft.conditions?.[index];
    if(condition){$('#creator-condition-'+index).value=condition.kind;$('#creator-condition-value-'+index).value=condition.value||'';}
    for(const suffix of ['','-value']){const node=suffix?$('#creator-condition-value-'+index):$('#creator-condition-'+index);bindValue('#'+node.id,()=>{plan.authorCardDraft={...(plan.authorCardDraft||{}),conditions:currentConditions()};});}
    const showConditionValue=()=>{$('#creator-condition-value-'+index).closest('.field').hidden=['none','has_barrier'].includes($('#creator-condition-'+index).value);};
    $('#creator-condition-'+index).addEventListener('change',showConditionValue);showConditionValue();
  }
  $('#creator-conditions').insertAdjacentHTML('afterend',`<details class="form-card" id="creator-complex-details"><summary>复杂玩法：补充说明或请求协助</summary><p>召唤物、特殊伤害和技能复用可以用下面的中文问题说明。选了特殊机制的卡片会交给制作方核对，不能只套用普通效果而丢掉特别要求。没有画稿时可以写复用参考或请协助。</p>${selectField('希望制作什么','creator-mechanic','unmarked',CREATOR_DETAILS)}${Object.entries(CREATOR_DETAIL_FIELDS).map(([key,label])=>`<div data-creator-detail="${key}">${textField(label,'creator-detail-'+key,'')}</div>`).join('')}</details>`);
  const currentDetails=()=>{const mechanic=$('#creator-mechanic').value;if(mechanic==='unmarked')return null;return {...(plan.authorCardDraft?.details||{}),mechanic,...Object.fromEntries((CREATOR_DETAIL_SCOPE[mechanic]||[]).map(field=>[field,$('#creator-detail-'+field).value.trim()]))};};
  $('#creator-complex-details').insertAdjacentHTML('beforeend',`<button id="creator-reuse-select">从工程中选择复用参考</button><p class="hint">${draft.details?.referenceChoice?'已选择工程参考，预览时继续核验。':'可以点选工程已有的技能、动作、特效或声音；没有合适参考时，填写想法或申请协助即可。'}参考选择不会改变原技能或素材。</p>`);
  $('#creator-reuse-select').onclick=()=>busy('查看工程已有的复用参考',()=>openCreatorReuseReference(key));
  $('#creator-mechanic').value=draft.details?.mechanic||'unmarked';
  for(const key of Object.keys(CREATOR_DETAIL_FIELDS)){$('#creator-detail-'+key).value=draft.details?.[key]||'';bindValue('#creator-detail-'+key,()=>{plan.authorCardDraft={...(plan.authorCardDraft||{}),details:{...(plan.authorCardDraft?.details||{}),...currentDetails()}};});}
  bindValue('#creator-mechanic',()=>{plan.authorCardDraft={...(plan.authorCardDraft||{}),details:{...(plan.authorCardDraft?.details||{}),mechanic:$('#creator-mechanic').value}};});
  const showDetails=()=>{const visible=CREATOR_DETAIL_SCOPE[$('#creator-mechanic').value]||[];$$('[data-creator-detail]').forEach(node=>node.hidden=!visible.includes(node.dataset.creatorDetail));};
  $('#creator-mechanic').addEventListener('change',showDetails);showDetails();
  $('#creator-main-only').closest('label').hidden=!key.startsWith('ability');
  $('#creator-main-only').onchange=()=>mutate(()=>{plan.authorCardDraft={...(plan.authorCardDraft||{}),mainOnly:$('#creator-main-only').checked};},false);
  const showHeal=()=>{
    const effect=$('#creator-effect').value,combo=effect==='combo_add',gauge=effect==='skill_gauge_up';
    $('#creator-heal-basis-wrap').hidden=effect!=='heal';
    $('#creator-stacking').closest('.field').hidden=combo||gauge;$('#creator-time').closest('.field').hidden=combo||gauge;
    $('label[for="creator-amount"]').textContent=combo?'增加多少次连击（1–9999 的整数）':'数值（例如 20% 或 2倍；可留空）';
    $('#creator-amount').placeholder=combo?'增加的整数次数，例如 10':'例如 20%';
    $('#creator-composition-preview').textContent=combo?'连击请选择“本次战斗连击”作为目标，填写 1–9999 的整数；这是一次增加，没有持续时间。':gauge?'填写基础最大技能槽的增加比例，例如 15%（最多100%），沿游戏原有的获取限制；持续充能或其他特殊要求可以申请协助。':'用中文填写，不需要输入脚本。特殊机制请在上面的说明里描述。';
  };
  $('#creator-effect').addEventListener('change',showHeal);showHeal();
  bindValue('#creator-plan-help',reason=>{plan.authorPolicy={...(plan.authorPolicy||{}),state:reason.trim()?'needs_help':'unmarked',reason};});
  $('#creator-compose').onclick=()=>mutate(()=>{const label=(choices,value)=>choices.find(([key])=>key===value)?.[1]||'待核条件',amount=$('#creator-amount').value.trim(),time=['combo_add','skill_gauge_up'].includes($('#creator-effect').value)?'':$('#creator-time').value.trim(),conditions=currentConditions();const conditional=conditions.length?'，且'+conditions.map(condition=>label(CREATOR_CONDITIONS,condition.kind)+(condition.kind==='has_barrier'?'':' '+(condition.value||'待确定'))).join('、同时'):'';const details=currentDetails();const line=creatorMechanicSentence(details,`${label(CREATOR_TRIGGERS,$('#creator-trigger').value)}${conditional}，让${label(CREATOR_TARGETS,$('#creator-target').value)}${label(CREATOR_EFFECTS,$('#creator-effect').value)}${amount?' '+amount:''}${time?'，持续 '+time:''}。`);sync('authorDescription',[plan.authorDescription,line].filter(Boolean).join('\n'));plan.authorCards??=[];plan.authorCards.push({trigger:$('#creator-trigger').value,target:$('#creator-target').value,effect:$('#creator-effect').value,amount,duration:time,stacking:['combo_add','skill_gauge_up'].includes($('#creator-effect').value)?'unmarked':$('#creator-stacking').value,healBasis:$('#creator-heal-basis').value,mainOnly:$('#creator-main-only').checked,...(conditions.length?{conditions}:{}),...(details?{details}:{}),text:line});});
  $('#creator-request-help').onclick=()=>busy('保存协助说明',async()=>{const reason=$('#creator-plan-help').value.trim();if(!reason)return toast('请写明希望协助的具体情况',true);if(reason.length>4000)throw Error('协助说明请控制在 4000 字以内');mutate(()=>{plan.authorPolicy={...(plan.authorPolicy||{}),state:'needs_help',reason};},false);await saveNow();renderCreatorGameplay();toast('协助说明已保存；仍保留为接入待核');});
  if(typeof appendAuthorIntegrationControls==="function")appendAuthorIntegrationControls();
  $('#creator-reference').onclick=chooseDefinition;if($('#creator-native-data'))$('#creator-native-data').onclick=()=>{nativeTab='data';renderNative();};
}
