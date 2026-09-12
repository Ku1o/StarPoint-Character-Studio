'use strict';
let nativeCatalog=null, nativeTab='data',nativeRenderId=0;
const renderDesignNotes=renderGameplay;
renderGameplay=function(){
  if(!S.p.nativeGameplay || nativeTab==='notes'){
    renderDesignNotes();
    const banner=document.createElement('section');banner.className='native-intro';
    banner.innerHTML=`<div><strong>${S.p.nativeGameplay?'已载入可编辑的游戏数据':'载入角色定义，开始编辑能力词条'}</strong><p>技能版本、队长技与六槽能力使用 MOD 的同一套规则；设计说明可继续保存在下方。</p></div><div class="page-actions"><button id="native-install">导入旧版定义 ZIP</button><button id="native-enter" class="primary">${S.p.nativeGameplay?'打开游戏数据':'选择参考角色定义'}</button></div>`;
    $('#content').prepend(banner);
    $('#native-install').onclick=installDefinition;
    $('#native-enter').onclick=()=>{if(S.p.nativeGameplay){nativeTab='data';renderGameplay();}else chooseDefinition();};
    return;
  }
  renderNative();
};
function installDefinition(){const input=document.createElement('input');input.type='file';input.accept='.zip';input.onchange=()=>{const f=input.files[0];if(!f)return;busy('导入角色定义包',async()=>{if(f.size>48*1024*1024)throw Error('这是大型资源包，请将 templates 和 definitions 文件夹直接解压到程序目录；此入口仅用于旧版小型定义 ZIP');await api('/api/definition-install',{data:await file64(f)});toast('角色定义包已安装');await chooseDefinition();});};input.click();}
async function chooseDefinition(){
  try{
    const library=await api('/api/definitions');
    if(!library.installed){modal('<h2>安装角色定义包</h2><p>将完整角色资源包中的 templates 和 definitions 文件夹一起解压到程序目录。此处也支持导入旧版的小型角色定义 ZIP。</p><div class="modal-actions"><button id="native-install-now" class="primary">选择定义包 ZIP</button></div>');$('#native-install-now').onclick=installDefinition;return;}
    const source=S.p.template?.id;
    const choices=source?library.entries.filter(c=>String(c.id)===String(source)):library.entries;
    modal(`<h2>${source?'补齐当前模板的角色定义':'选择玩法参考角色'}</h2><p>载入真实技能、队长技与能力条目，图片和已有设计保持保留。定义版本 ${esc(library.version)}。</p>${source?'':field('搜索角色名或编号','native-search','')}<div id="native-choices" class="native-choices"></div>`);
    function list(query=''){$('#native-choices').innerHTML=choices.filter(c=>(c.name+c.id+c.code).toLowerCase().includes(query.toLowerCase())).slice(0,80).map(c=>`<button data-definition="${esc(c.id)}"><strong>${esc(c.name)}</strong><small>${esc(c.id)} · ${esc(c.code)}</small></button>`).join('')||'<p>当前定义包没有匹配角色，请检查模板与定义包版本。</p>';$$('[data-definition]').forEach(b=>b.onclick=()=>busy('载入原始角色定义',async()=>{await saveNow();const p=await api('/api/definition-attach',{id:S.p.id,revision:S.p.revision,character:b.dataset.definition});S.p=p;S.generation++;S.dirty=false;nativeTab='data';$('#modal').close();render();}));}
    list();if($('#native-search'))$('#native-search').oninput=e=>list(e.target.value);
  }catch(e){toast(e.message,true);}
}
async function nativeChange(operation,slot,index,spec){
  return busy('校验并保存游戏数据',async()=>{await saveNow();const previous=clone(S.p);const p=await api('/api/native-edit',{id:S.p.id,revision:S.p.revision,operation,slot,index,spec});S.undo.push(previous);S.redo=[];S.p=p;S.generation++;S.dirty=false;$('#modal').close();render();toast('已保存，原始定义和未编辑字段已保留');});
}
async function renderNative(){
  const pid=S.p.id, request=++nativeRenderId, scroll=captureEditorScroll();
  $('#content').innerHTML=header('技能与能力','编辑实际条目，中文说明与游戏数据同步更新。')+'<div class="empty">读取角色定义…</div>';
  try{
    await saveNow();const [report,catalog]=await Promise.all([api('/api/native-gameplay?id='+pid),nativeCatalog?Promise.resolve(nativeCatalog):api('/api/ability-catalog')]);nativeCatalog=catalog;
    if(!S.p||S.p.id!==pid||S.page!=='gameplay'||nativeTab!=='data'||request!==nativeRenderId)return;
    $('#content').innerHTML=header('技能与能力',`参考 ${report.source.name} · 定义 ${report.version}`,`<button id="native-notes">设计备注</button><button id="native-export" class="primary">导出 MOD 制作工程</button>`)+
      `<div class="native-intro"><div><strong>真实条目编辑</strong><p>将条件、触发方式和效果拆开组合，也可从词条库单独取材。每个能力槽可包含多条效果。游戏接入仍需检查资源、编号与行为。</p></div><span class="tag">MOD 与独立版共用工程</span></div>`+
      `<section class="form-card native-skills"><h3>主动技能版本</h3>${report.skills.map((s,i)=>`<div class="native-skill-row"><div><strong>${esc(s.fields[0])}</strong><small>${esc(s.inner_key)} · 能量 ${esc(s.fields[4])} → ${esc(s.fields[5])}</small><p>${esc(s.fields[1])}</p></div><button data-skill-edit="${i}">编辑名称与能量</button></div>`).join('')}</section>`+
      `<div class="native-groups">${report.groups.map(group=>`<section class="form-card ${group.slot==='leader'?'native-leader':''}"><div class="section-title"><h3>${group.slot==='leader'?'队长技':'能力 '+group.slot}</h3><div class="page-actions"><button data-native-compose="${group.slot}" class="primary">＋ 自由组合</button><button data-native-library="${group.slot}">从词条库取材</button><button data-native-add="${group.slot}">＋ 添加效果</button></div></div><div>${group.rows.map(row=>`<div class="native-row"><p>${esc(row.description||'原始条目（展开查看）')}</p>${row.issues.length?'<p class="native-warning">原始条目存在校验提示，已保留原值。</p>':''}<div class="page-actions"><button data-native-decompose="${group.slot}:${row.index}">拆解与组合</button><button data-native-transfer="${group.slot}:${row.index}">复制 / 移动</button><button data-native-edit="${group.slot}:${row.index}" ${row.editable?'':'disabled'}>调整数值</button><button class="quiet" data-native-remove="${group.slot}:${row.index}">删除</button><details><summary>原始数据</summary><pre>${esc(JSON.stringify(row.row))}</pre></details></div></div>`).join('')||'<p class="hint">此槽暂无效果，可添加条目。</p>'}</div></section>`).join('')}</div>`+
      `<p class="footer-note">编辑记录随 .wfchar.zip 工程保存；在 MOD 的角色工坊入口打开后可继续制作。已保留来源成长数据；技能与声音的表现请在“技能制作”中查看，完整战斗运行预览仍待接入。</p>`;
    restoreEditorScroll(scroll);
    $$('[data-native-library]').forEach(b=>b.onclick=()=>openAbilityLibrary(b.dataset.nativeLibrary==='leader'?'leader':Number(b.dataset.nativeLibrary)));
    $('#native-notes').onclick=()=>{nativeTab='notes';renderGameplay();};$('#native-export').onclick=()=>$('#export').click();
    const parse=value=>{const [slot,index]=value.split(':');return [slot==='leader'?slot:Number(slot),Number(index)];};
    $$('[data-native-compose]').forEach(b=>b.onclick=()=>openAbilityComposition(b.dataset.nativeCompose==='leader'?'leader':Number(b.dataset.nativeCompose)));
    $$('[data-native-decompose]').forEach(b=>b.onclick=()=>openAbilityComposition(...parse(b.dataset.nativeDecompose)));
    $$('[data-native-transfer]').forEach(b=>b.onclick=()=>transferAbilityRow(...parse(b.dataset.nativeTransfer)));
    $$('[data-native-edit]').forEach(b=>b.onclick=()=>{const [slot,index]=parse(b.dataset.nativeEdit);const row=report.groups.find(g=>g.slot===slot).rows[index];editNativeRow(slot,row);});
    $$('[data-native-remove]').forEach(b=>b.onclick=()=>{const [slot,index]=parse(b.dataset.nativeRemove);modal(`<h2>删除此效果条目</h2><p>其他条目不受影响，保存后可以撤销。</p><div class="modal-actions"><button id="native-remove-ok">删除条目</button></div>`);$('#native-remove-ok').onclick=()=>nativeChange('delete',slot,index,{});});
    $$('[data-native-add]').forEach(b=>b.onclick=()=>addNativeRow(b.dataset.nativeAdd==='leader'?'leader':Number(b.dataset.nativeAdd)));
    $$('[data-skill-edit]').forEach(b=>b.onclick=()=>{const index=Number(b.dataset.skillEdit),s=report.skills[index];modal(`<h2>编辑技能版本</h2>${field('名称','native-skill-name',s.fields[0])}${textField('说明','native-skill-text',s.fields[1])}<div class="field-row">${field('初始能量','native-energy',s.fields[4],'number','min="1" max="9999"')}${field('满级能量','native-energy-max',s.fields[5],'number','min="1" max="9999"')}</div><p class="hint">技能程序与其他原始字段保留。</p><div class="modal-actions"><button id="native-skill-save" class="primary">保存此版本</button></div>`);$('#native-skill-save').onclick=()=>nativeChange('skill',null,index,{name:$('#native-skill-name').value,description:$('#native-skill-text').value,energy:$('#native-energy').value,energyMax:$('#native-energy-max').value});});
  }catch(e){if(S.p?.id===pid)$('#content').innerHTML=header('技能与能力','读取角色定义时遇到问题')+`<div class="notice">${esc(e.message)}</div>`;}
}
function editNativeRow(slot,row){
  const unit={pct:'%',count:'次',x:'倍',raw:'原始整数'}[row.unit];
  modal(`<h2>调整${slot==='leader'?'队长技':'能力 '+slot}</h2><p>${esc(row.description)}</p><div class="field-row">${field('初始数值（'+unit+'）','native-value',row.value,'number','step="any"')}${field('满级数值（'+unit+'）','native-value-max',row.valueMax,'number','step="any"')}</div>${row.mode==='0'?field('持续时间（秒；留空保留原值）','native-duration',row.duration,'number','step="any" min="0"'):''}${slot==='leader'?'':`<label class="check-row"><input id="native-main" type="checkbox" ${row.mainOnly?'checked':''}>仅主位生效</label>`}<p class="hint">只修改这里填写的数值与主位条件。其他触发、引用和扩展字段原样保留。</p><div class="modal-actions"><button id="native-row-save" class="primary">保存条目</button></div>`);
  $('#native-row-save').onclick=()=>nativeChange('patch',slot,row.index,{value:$('#native-value').value,valueMax:$('#native-value-max').value,...($('#native-duration')?{duration:$('#native-duration').value}:{}),...(slot!=='leader'?{mainOnly:$('#native-main').checked}:{})});
}
function addNativeRow(slot){
  const cat=nativeCatalog;
  modal(`<h2>添加${slot==='leader'?'队长技效果':'能力 '+slot+' 效果'}</h2><p>选择触发条件与效果，工具生成实际游戏条目。</p>${selectField('什么时候发动','native-trigger','battle_start',cat.triggers.map(t=>[t.id,t.name]))}${selectField('产生什么效果','native-effect','atk',[])}<div class="field-row">${field('初始数值','native-add-value',10,'number','step="any"')}${field('满级数值','native-add-max',20,'number','step="any"')}</div><p id="native-unit" class="hint"></p><div class="field-row">${selectField('作用对象','native-target','0',Object.entries(cat.targets))}${selectField('角色组 / 属性','native-group','',cat.groups.map(g=>[g.id,g.name]))}</div>${field('触发阈值（按所选条件填写百分比或次数）','native-threshold','','number','step="any"')}${field('持续时间（秒；留空沿用默认）','native-add-duration','','number','step="any" min="0"')}${selectField('附加前置条件','native-precondition','',cat.preconditions_common.map(p=>[p.kind,p.name]))}${field('前置条件阈值（%）','native-precondition-threshold','','number','step="any"')}<label class="check-row"><input type="checkbox" id="native-add-main">仅主位生效</label><div id="native-add-description" class="notice">保存后会显示按实际数据生成的中文说明。</div><div class="modal-actions"><button id="native-add-save" class="primary">添加并校验</button></div>`);
  function effects(){const t=cat.triggers.find(t=>t.id===$('#native-trigger').value);const options=cat.effects.filter(e=>e.mode===t.mode&&e.kind!=='629');$('#native-effect').innerHTML=options.map(e=>`<option value="${esc(e.id)}">${esc(e.name)}</option>`).join('');$('#native-threshold').disabled=!t.threshold;$('#native-add-duration').disabled=t.mode!=='instant';unit();}
  function unit(){const fx=cat.effects.find(e=>e.id===$('#native-effect').value);$('#native-unit').textContent='数值单位：'+({pct:'百分比（填 10 即 10%）',count:'次数',x:'倍率',raw:'原始整数'}[fx.unit]||fx.unit);}
  $('#native-precondition').onchange=()=>{$('#native-precondition-threshold').disabled=!cat.preconditions_common.find(p=>p.kind===$('#native-precondition').value)?.threshold;};$('#native-precondition').onchange();$('#native-trigger').onchange=effects;$('#native-effect').onchange=unit;effects();if(slot==='leader')$('#native-add-main').closest('label').hidden=true;
  $('#native-add-save').onclick=()=>nativeChange('add',slot,null,{trigger_id:$('#native-trigger').value,effect_id:$('#native-effect').value,value:$('#native-add-value').value,value_max:$('#native-add-max').value,target:$('#native-target').value,groups:$('#native-group').value,threshold:$('#native-threshold').disabled?null:$('#native-threshold').value,mainOnly:$('#native-add-main').checked,duration:$('#native-add-duration').disabled?null:$('#native-add-duration').value,precondition_kind:$('#native-precondition').value,precondition_threshold:$('#native-precondition-threshold').disabled?null:$('#native-precondition-threshold').value});
}
