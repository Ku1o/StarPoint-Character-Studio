'use strict';
const AbilityBlocks=(()=>{
  const type=name=>name.replace(/[123]$/,'');
  function extract(meta,kind,row,name){const fields=meta.block_fields[type(name)]||[[0,name,'']];return {type:type(name),values:fields.map(([off,key])=>[key,row[meta.kinds[kind].blocks[name]+off]])};}
  function insert(meta,kind,row,name,part){if(type(name)!==part.type)throw Error('请选择相同类型的组件，例如条件替换条件、效果替换效果');const values=new Map(part.values),out=row.slice();for(const [off,key] of meta.block_fields[type(name)]||[[0,name,'']])if(values.has(key))out[meta.kinds[kind].blocks[name]+off]=values.get(key);return out;}
  return {extract,insert,type};
})();
if(typeof module!=='undefined')module.exports=AbilityBlocks;
let abilityEditorMeta=null,abilityClipboard=null;
const ABILITY_BLOCK_NAMES={precondition1:'前置条件 1',precondition2:'前置条件 2',precondition3:'前置条件 3',instant_trigger:'什么时候触发',instant_precontent:'触发前消耗',instant_delay:'延迟发动',instant_content:'产生什么效果',during_accumulation_trigger:'累计条件',during_trigger:'在哪种状态下生效',even_if_owner_dead:'倒下后是否生效',during_content:'产生什么效果',opening:'开幕效果'};
const ABILITY_ENUMS={precondition:'precondition',instant_trigger:'trigger',during_accumulation_trigger:'trigger',during_trigger:'during_trigger',instant_content:'instant_content',during_content:'during_content'};
async function openAbilityComposition(slot,index=null,resume=null){
  try{
    await saveNow();
    const pid=S.p.id,[meta,data]=await Promise.all([abilityEditorMeta?Promise.resolve(abilityEditorMeta):api('/api/ability-editor'),resume?Promise.resolve(resume):api('/api/ability-row-draft',{id:pid,slot,index})]);abilityEditorMeta=meta;
    const kind=data.kind,layout=meta.kinds[kind],bases=layout.blocks,blank=S.p.nativeGameplay.source.data.blankRows[kind];
    let row=clone(data.row),serial=0,timer,valid=false;
    const label=slot==='leader'?'队长技':'能力 '+slot;
    modal(`<div class="ability-composer"><h2>${index===null?'自由组合':'拆解与组合'} · ${label}</h2><p>一条效果由条件、触发方式和效果组件组成。每块可以独立修改或取材；需要多种效果时，在同一能力槽继续添加条目。</p><div class="ability-composer-top">${selectField('生效方式','ability-mode',row[layout.trigger_col],[['0','触发时发动'],['1','满足条件期间'],['2','开幕效果']])}${kind==='ability'?`<label class="check-row"><input id="ability-main-only" type="checkbox" ${row[1]==='false'?'checked':''}>仅主位生效</label>`:''}</div><div id="ability-components"></div><details class="ability-extra"><summary>条目标识与扩展设置</summary><div id="ability-head" class="ability-fields"></div><p class="hint">专属条件、动作路径和觉醒门槛会保留；引用新内容时仍需完成对应的游戏接入。</p></details><div class="ability-composer-preview"><strong>组合后的效果</strong><p id="ability-row-description">正在生成说明…</p><p id="ability-row-issues" class="notice" hidden></p><div class="modal-actions"><button id="ability-row-cancel">取消</button><button id="ability-row-save" class="primary" disabled>${index===null?'添加这一条效果':'保存这一条效果'}</button></div></div></div>`);
    const dialog=$('#modal'),root=$('.ability-composer');const active=()=>dialog.open&&S.p?.id===pid&&$('.ability-composer')===root;
    dialog.addEventListener('close',()=>clearTimeout(timer),{once:true});
    function refresh(){clearTimeout(timer);const request=++serial;valid=false;$('#ability-row-save').disabled=true;timer=setTimeout(async()=>{try{const value=await api('/api/ability-row-preview',{kind,row:clone(row)});if(!active()||request!==serial)return;valid=value.valid;$('#ability-row-description').textContent=value.description||'尚无可描述效果';$('#ability-row-issues').hidden=!value.issues.length;$('#ability-row-issues').textContent=value.issues.join('；');$('#ability-row-save').disabled=!valid;}catch(e){if(active()&&request===serial){$('#ability-row-issues').hidden=false;$('#ability-row-issues').textContent=e.message;}}},180);}
    function setCell(i,value){row[i]=String(value);refresh();}
    function optionsFor(block,key){
      const type=AbilityBlocks.type(block),category=key==='kind'?ABILITY_ENUMS[type]:null;
      if(category){const usage=(meta.usage[{trigger:'instant_trigger'}[category]||category]||{})[kind==='leader_ability'?'leader':'ability']||{};return Object.entries(meta.enums[category]).map(([v,o])=>[v,o.cn||o.en,usage[v]||0]).sort((a,b)=>b[2]-a[2]);}
      let small=key==='target'?'target':key==='trigger_puller'?(['instant_trigger','during_accumulation_trigger'].includes(block)?'instant_puller':'during_puller'):key==='element'?'element':key==='multiply_trigger'?'multiply':key==='kind'&&block==='opening'?'opening':key==='kind'&&block==='instant_precontent'?'precontent':null;
      if(small)return Object.entries(meta.small[small]);
      if(key.includes('character_groups'))return [['','不限'],...Object.entries(meta.groups)];
      if(['by_each_trigger_puller','even_if_owner_dead'].includes(key))return [['false','否'],['true','是']];
      if(key==='cancelable')return [['','沿用默认'],['0','可驱散'],['1','不可驱散']];
      return null;
    }
    function numericUnit(block,key){
      if(/^frame\./.test(key))return ['秒',6000000];
      if(/^number\./.test(key))return ['次',100000];
      if(key==='instant_delay')return ['秒',1];
      if(/^strength/.test(key)){const mode=block==='during_content'?'during':'instant',fx=nativeCatalog?.effects.find(f=>f.mode===mode&&f.kind===row[bases[block]]);return fx?.unit==='pct'?['%',1000]:fx?.unit==='x'?['倍',100000]:fx?.unit==='count'?['次',100000]:['原始值',1];}
      if(/^threshold/.test(key)){const mode=block==='during_trigger'?'during':'instant',t=nativeCatalog?.triggers.find(t=>t.mode===mode&&t.kind===row[bases[block]]);return t?.threshold==='pct'?['%',1000]:t?.threshold==='count'?['次',100000]:['原始值',1];}
      return ['原始值',1];
    }
    function fieldEditor(block,off,key,description,parent){
      const i=bases[block]+off,wrap=document.createElement('label');wrap.className='ability-cell';wrap.dataset.column=i;wrap.title=description||key;
      description=({kind:ABILITY_BLOCK_NAMES[block],trigger_puller:'由谁触发',target:'作用对象','target.character_groups':'限定目标角色组','trigger_puller.character_groups':'限定触发角色组','threshold.power1':'初始阈值','threshold.first_max':'满级阈值','strength.power1':'初始数值','strength.first_max':'满级数值','frame.power1':'初始持续时间','frame.first_max':'满级持续时间'})[key]||description;
      const title=document.createElement('span');title.textContent=description||key;wrap.append(title);
      const options=optionsFor(block,key);
      if(options&&!key.includes('character_groups')){
        const select=document.createElement('select');select.id='ability-cell-'+i;select.setAttribute('aria-label',description||key);
        const entries=options.map(([v,label])=>[String(v),label]);if(!entries.some(([v])=>v===row[i]))entries.unshift([row[i],row[i]||'空值']);
        const fill=q=>{select.replaceChildren();for(const [value,label] of entries)if(value===row[i]||!q||(value+' '+label).toLowerCase().includes(q.toLowerCase())){const option=new Option(label+(value!==''?' · '+value:''),value);select.add(option);}select.value=row[i];};
        if(entries.length>14){const search=document.createElement('input');search.type='search';search.placeholder='搜索名称或编号';search.setAttribute('aria-label','搜索 '+(description||key));search.oninput=()=>fill(search.value.trim());wrap.append(search);}
        fill('');select.onchange=()=>{setCell(i,select.value);if(key==='kind'){const scroll=dialog.scrollTop;renderBlocks();dialog.scrollTop=scroll;}};wrap.append(select);
      }else{
        const input=document.createElement('input');input.id='ability-cell-'+i;input.setAttribute('aria-label',description||key);input.spellcheck=false;
        if(options){input.value=row[i];const list=document.createElement('datalist');list.id='ability-options-'+i;for(const [value,label] of options){const option=new Option(label,value);list.append(option);}input.setAttribute('list',list.id);wrap.append(list);input.placeholder='不限；多个角色组用 / 连接';input.oninput=()=>setCell(i,input.value.trim());}
        else if(/strength|threshold|^frame\.|^number\.|^instant_delay$/.test(key)){
          const [unit,factor]=numericUnit(block,key),numeric=/^-?\d+(\.\d+)?$/.test(row[i]);input.value=numeric?String(Number(row[i])/factor):row[i];
          const units=document.createElement('select');units.className='ability-unit';units.setAttribute('aria-label',(description||key)+' 单位');for(const [name,mul] of [['原始值',1],['%',1000],['次 / 倍',100000],['秒（动画帧）',6000000]])units.add(new Option(name,String(mul)));units.value=String(factor);title.textContent+='（'+unit+'）';
          input.oninput=()=>{const text=input.value.trim(),number=Number(text)*Number(units.value);if(text===''||text==='(None)'){input.setCustomValidity('');setCell(i,text);}else if(Number.isFinite(number)&&Math.abs(number-Math.round(number))<1e-6){input.setCustomValidity('');setCell(i,String(Math.round(number)));}else{input.setCustomValidity('数值或精度无效');valid=false;$('#ability-row-save').disabled=true;}};
          units.onchange=()=>{if(/^-?\d+(\.\d+)?$/.test(row[i]))input.value=String(Number(row[i])/Number(units.value));title.textContent=description||key;};wrap.append(units);
        }else{input.value=row[i];input.oninput=()=>setCell(i,input.value.trim());}
        wrap.append(input);
      }
      parent.append(wrap);
    }
    function blockSection(name,parent,collapsed=false){
      const section=document.createElement(collapsed?'details':'section');section.className='ability-component';section.dataset.abilityBlock=name;
      const heading=document.createElement(collapsed?'summary':'h3');heading.textContent=ABILITY_BLOCK_NAMES[name];section.append(heading);
      const tools=document.createElement('div');tools.className='ability-component-tools';
      for(const [text,action] of [['从词条库取这一块','take'],['复制组件','copy'],['粘贴组件','paste'],['重置组件','reset']]){const button=document.createElement('button');button.type='button';button.textContent=text;button.dataset.blockAction=action;if(action==='paste')button.disabled=abilityClipboard?.type!==AbilityBlocks.type(name);button.onclick=()=>{if(action==='copy'){abilityClipboard=AbilityBlocks.extract(meta,kind,row,name);$$('[data-block-action="paste"]').forEach(b=>b.disabled=AbilityBlocks.type(b.closest('[data-ability-block]').dataset.abilityBlock)!==abilityClipboard.type);toast('已复制 '+ABILITY_BLOCK_NAMES[name]);}else if(action==='paste'||action==='reset'){row=AbilityBlocks.insert(meta,kind,row,name,action==='paste'?abilityClipboard:AbilityBlocks.extract(meta,kind,blank,name));const scroll=dialog.scrollTop;renderBlocks();dialog.scrollTop=scroll;refresh();}else{const resumeData={kind,row:clone(row),revision:data.revision};openAbilityLibrary(slot,{onChoose:(entry,sourceRow)=>{resumeData.row=AbilityBlocks.insert(meta,kind,row,name,AbilityBlocks.extract(meta,entry.kind,sourceRow,name));openAbilityComposition(slot,index,resumeData);},onBack:()=>openAbilityComposition(slot,index,resumeData),component:ABILITY_BLOCK_NAMES[name],componentBlock:name});}};tools.append(button);}section.append(tools);
      const main=document.createElement('div');main.className='ability-fields';section.append(main);
      const more=document.createElement('details');more.className='ability-more';more.innerHTML='<summary>更多参数与专属引用</summary>';const advanced=document.createElement('div');advanced.className='ability-fields';more.append(advanced);
      for(const [off,key,description] of meta.block_fields[AbilityBlocks.type(name)]||[[0,name,'']]){const basic=off===0||['target','trigger_puller','target.character_groups','trigger_puller.character_groups','strength.power1','strength.first_max','strength1.power1','strength1.first_max','threshold.power1','threshold.first_max','threshold1.power1','threshold1.first_max','frame.power1','frame.first_max'].includes(key);fieldEditor(name,off,key,description,basic?main:advanced);}if(advanced.childElementCount)section.append(more);parent.append(section);
    }
    function renderBlocks(){const root=$('#ability-components');root.replaceChildren();const pre=document.createElement('details');pre.className='ability-preconditions';pre.innerHTML='<summary>前置条件 · 最多组合 3 个</summary>';for(const name of ['precondition1','precondition2','precondition3'])blockSection(name,pre);root.append(pre);
      const mode=row[layout.trigger_col];for(const name of mode==='0'?['instant_trigger','instant_content','instant_precontent','instant_delay']:mode==='1'?['during_trigger','during_content','during_accumulation_trigger','even_if_owner_dead']:['opening'])blockSection(name,root,['instant_precontent','instant_delay','during_accumulation_trigger','even_if_owner_dead'].includes(name));}
    for(const [column,description] of layout.head){const i=Number(column.slice(1));if(i===layout.trigger_col||(kind==='ability'&&i===1))continue;const label=document.createElement('label');label.className='ability-cell';label.textContent=description;const input=document.createElement('input');input.value=row[i];input.oninput=()=>setCell(i,input.value);label.append(input);$('#ability-head').append(label);}
    $('#ability-mode').onchange=e=>{setCell(layout.trigger_col,e.target.value);renderBlocks();};if($('#ability-main-only'))$('#ability-main-only').onchange=e=>setCell(1,e.target.checked?'false':'true');
    $('#ability-row-cancel').onclick=()=>dialog.close();
    $('#ability-row-save').onclick=()=>busy('校验并保存组合效果',async()=>{if(!active()||!valid)return;if(root.querySelector(':invalid'))throw Error('请修正数值字段');await saveNow();const previous=clone(S.p),p=await api('/api/ability-row-apply',{id:pid,revision:data.revision,slot,index,row});S.undo.push(previous);S.redo=[];S.p=p;S.generation++;S.dirty=false;dialog.close();render();toast('效果组合已保存');});
    renderBlocks();refresh();
  }catch(e){toast(e.message,true);}
}
async function transferAbilityRow(slot,index){
  const choices=slot==='leader'?[['leader','队长技']]:[1,2,3,4,5,6].map(n=>[n,'能力 '+n]);
  modal(`<h2>复制或移动这一条效果</h2><p>可将不同条目放入同一能力槽，组合成完整能力。</p>${selectField('操作','ability-transfer-action','copy',[['copy','复制一份'],['move','移动原条目']])}${selectField('放入槽位','ability-transfer-slot',slot,choices)}${field('插入位置（从 1 开始，留空放在末尾）','ability-transfer-position','','number','min="1" max="129"')}<div class="modal-actions"><button id="ability-transfer-save" class="primary">保存</button></div>`);
  $('#ability-transfer-save').onclick=()=>busy('保存效果条目',async()=>{await saveNow();const target=$('#ability-transfer-slot').value==='leader'?'leader':Number($('#ability-transfer-slot').value),dest=target==='leader'?S.p.nativeGameplay.leader:S.p.nativeGameplay.abilities[target-1],value=$('#ability-transfer-position').value,position=value===''?dest.rows.length:Number(value)-1,previous=clone(S.p),p=await api('/api/ability-row-transfer',{id:S.p.id,revision:S.p.revision,slot,index,target,position,copy:$('#ability-transfer-action').value==='copy'});S.undo.push(previous);S.redo=[];S.p=p;S.generation++;S.dirty=false;$('#modal').close();render();});
}
